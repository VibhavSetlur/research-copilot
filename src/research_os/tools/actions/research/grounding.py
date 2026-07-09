"""Grounded reasoning — ReAct + PROV-O + CoVe + Reflexion lessons.

The AI's most-common failure mode is acting without showing the
evidence it acted on. This module gives the project four append-only
records that make every decision auditable:

* **Thought log** (ReAct) — ``.os_state/thoughts/thoughts.jsonl``
  (new canonical path; legacy: ``workspace/.thoughts/thoughts.jsonl``)
  appends one `{thought, action, observation}` entry per non-trivial
  step. Mirrors Yao et al. 2022's trajectory format so the trace
  reads as the model intended it.
* **Grounding registry** — ``workspace/.grounding/grounding.jsonl``
  binds each `decision_id` to a PROV-O record listing the entities
  (papers, datasets, context files, web sources) the decision
  rested on, with `cited_text` spans where applicable.
* **Verification log** (CoVe) — ``workspace/.grounding/verifications.jsonl``
  carries the verification questions the AI generated for each
  claim plus the verified answers and `supports: bool`. A claim is
  considered grounded only when all its verifications hold.
* **Lessons log** (Reflexion) — ``.os_state/lessons/lessons.jsonl``
  (new canonical path; see ``research/lessons.py``) captures
  `{trial_id, outcome, reflection}` after every step so later runs
  can prepend the relevant prior lessons to context.

All four are line-delimited JSON so they round-trip cleanly into
the dashboard, into the audit reports, and into the model's prompt
context. They are intentionally NOT inlined into ``state_ledger.json``
— that file stays small; these grow as the project does.

Backward-compatible path resolution for thoughts
-------------------------------------------------
* **New canonical path**: ``.os_state/thoughts/thoughts.jsonl``
* **Legacy path**: ``workspace/.thoughts/thoughts.jsonl``

On **write**: if the new path does not exist yet but the legacy path
does, legacy contents are migrated first (idempotent). Writes then
go to the new path.

On **read**: use the new path if it exists; else fall back to legacy.

Integration with the existing audit chain
-----------------------------------------
`tool_verify(scope='project')` walks every `mem_log(kind='decision')` entry in
`workspace/analysis.md` and confirms a matching grounding record
exists. A decision without grounding is a BLOCKER for the master
quality audit (alongside hallucinated claims, missing figures,
stub conclusions). This is the structural fix for "AI made a call
but didn't show its work".
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("research_os.grounding")


# ---------------------------------------------------------------------------
# File-layout helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_NEW_THOUGHTS_SUBPATH = Path(".os_state") / "thoughts" / "thoughts.jsonl"
_OLD_THOUGHTS_SUBPATH = Path("workspace") / ".thoughts" / "thoughts.jsonl"


def _migrate_thoughts_if_needed(root: Path, new_path: Path) -> None:
    """One-time migration: copy legacy thought records to the new path.

    Idempotent — if the new path already exists (even empty) we skip,
    so a second call never duplicates records.
    """
    old_path = root / _OLD_THOUGHTS_SUBPATH
    if not old_path.exists() or new_path.exists():
        return
    try:
        content = old_path.read_text(encoding="utf-8", errors="replace")
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(content, encoding="utf-8")
        logger.debug(
            "thoughts: migrated %s → %s", old_path.relative_to(root),
            new_path.relative_to(root),
        )
    except Exception as exc:  # pragma: no cover — best-effort migration
        logger.warning("thoughts: migration failed (%s); writes go to new path anyway", exc)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.touch()


def _thoughts_write_path(root: Path) -> Path:
    """Return the path to write thoughts to, running migration first if needed."""
    new_path = root / _NEW_THOUGHTS_SUBPATH
    _migrate_thoughts_if_needed(root, new_path)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    return new_path


def _thoughts_read_path(root: Path) -> Path:
    """Return the path to read thoughts from (new if exists, else legacy)."""
    new_path = root / _NEW_THOUGHTS_SUBPATH
    if new_path.exists():
        return new_path
    old_path = root / _OLD_THOUGHTS_SUBPATH
    return old_path


def _thoughts_log(root: Path) -> Path:
    """Return the canonical write path for thoughts (runs migration if needed)."""
    return _thoughts_write_path(root)


def _grounding_log(root: Path) -> Path:
    p = root / "workspace" / ".grounding" / "grounding.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _verifications_log(root: Path) -> Path:
    p = root / "workspace" / ".grounding" / "verifications.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _append_jsonl(path: Path, record: dict) -> None:
    with open(path, "a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------------------
# Thought log (ReAct)
# ---------------------------------------------------------------------------


_ALLOWED_KINDS = {
    "thought",       # internal reasoning
    "plan",          # multi-step plan summary
    "action",        # external tool call about to be made
    "observation",   # result of the action
    "reflection",    # post-hoc self-critique
    "decision",      # committed methodological choice
}


def thought_log(
    root: Path,
    *,
    kind: str,
    content: str,
    step_id: str | None = None,
    decision_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one ReAct-style trace entry.

    Parameters
    ----------
    kind: thought | plan | action | observation | reflection | decision
    content: the entry body (short prose).
    step_id: numbered step context (optional).
    decision_id: link to a decision in the grounding log (optional).
    metadata: free-form structured fields (model, tool name, etc).
    """
    if kind not in _ALLOWED_KINDS:
        return {
            "status": "error",
            "message": f"kind must be one of {sorted(_ALLOWED_KINDS)}",
        }
    if not content or not content.strip():
        return {"status": "error", "message": "content is required"}
    rec = {
        "trace_id": str(uuid.uuid4())[:12],
        "ts": _now(),
        "kind": kind,
        "content": content.strip(),
        "step_id": step_id,
        "decision_id": decision_id,
        "metadata": metadata or {},
    }
    write_path = _thoughts_log(root)
    _append_jsonl(write_path, rec)
    return {"status": "success", **rec,
            "log_path": str(write_path.relative_to(root))}


def thought_trace(
    root: Path,
    *,
    step_id: str | None = None,
    decision_id: str | None = None,
    tail: int = 50,
) -> dict[str, Any]:
    """Read the recent thought trace, optionally filtered."""
    entries = _read_jsonl(_thoughts_read_path(root))
    if step_id:
        entries = [e for e in entries if e.get("step_id") == step_id]
    if decision_id:
        entries = [e for e in entries if e.get("decision_id") == decision_id]
    return {
        "status": "success",
        "n_total": len(entries),
        "entries": entries[-tail:],
    }


# ---------------------------------------------------------------------------
# Grounding registry (PROV-O)
# ---------------------------------------------------------------------------


_SOURCE_TYPES = {
    "paper",          # peer-reviewed publication; citation_key from literature/
    "preprint",       # arXiv / bioRxiv / SSRN
    "dataset",        # data file in inputs/raw_data or external
    "context_file",   # prose note in inputs/context/ or step's context/
    "web",            # web page (URL + accessed_at)
    "workspace_artefact",  # an output file from another step
    "tool_research",  # a tool_research_method / tool_research_tool report
    "prior_decision", # another decision_id this one builds on
}


def grounding_register(
    root: Path,
    *,
    decision_id: str | None = None,
    claim: str,
    sources: list[dict[str, Any]],
    step_id: str | None = None,
    confidence: str = "medium",
    notes: str = "",
) -> dict[str, Any]:
    """Bind a decision/claim to the evidence that informed it.

    sources: list of dicts shaped::

        {"type": "paper", "citation_key": "smith2023", "doi": "...",
         "cited_text": "We found that …", "page": 4}
        {"type": "context_file", "path": "inputs/context/intake.md",
         "cited_text": "primary outcome is X"}
        {"type": "web", "url": "https://...", "accessed_at": "2026-05-28",
         "cited_text": "..."}
        {"type": "workspace_artefact", "path": "workspace/02_eda/outputs/.../table.csv",
         "cited_text": "row 7 col 'mean' = 12.3"}
    """
    if not claim.strip():
        return {"status": "error", "message": "claim is required"}
    if not sources:
        return {
            "status": "error",
            "message": "at least one source is required — a grounded "
            "decision cites at least one paper / context file / dataset / "
            "tool report. To record an exploratory hunch without "
            "evidence, use tool_thought_log kind='thought' instead.",
        }
    for s in sources:
        if s.get("type") not in _SOURCE_TYPES:
            return {
                "status": "error",
                "message": (
                    f"source type must be one of {sorted(_SOURCE_TYPES)}; "
                    f"got '{s.get('type')}'"
                ),
            }
    if confidence not in {"low", "medium", "high"}:
        return {
            "status": "error",
            "message": "confidence must be low | medium | high",
        }

    decision_id = decision_id or f"d_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"
    record = {
        # PROV-O JSON-LD shell.
        "@context": {"prov": "http://www.w3.org/ns/prov#"},
        "@type": "prov:Activity",
        "@id": f"ros:decision/{decision_id}",
        "decision_id": decision_id,
        "claim": claim.strip(),
        "step_id": step_id,
        "registered_at": _now(),
        "confidence": confidence,
        "notes": notes.strip(),
        "prov:used": [
            {**s, "@type": "prov:Entity"} for s in sources
        ],
        "prov:wasAssociatedWith": {
            "@type": "prov:Agent",
            "@id": "ros:agent/research_os",
        },
    }
    _append_jsonl(_grounding_log(root), record)
    return {
        "status": "success",
        "decision_id": decision_id,
        "n_sources": len(sources),
        "log_path": str(_grounding_log(root).relative_to(root)),
        "record": record,
    }


def grounding_for_decision(
    root: Path, decision_id: str,
) -> dict[str, Any] | None:
    """Return the most-recent grounding record for ``decision_id``."""
    matches = [
        r for r in _read_jsonl(_grounding_log(root))
        if r.get("decision_id") == decision_id
    ]
    return matches[-1] if matches else None


# ---------------------------------------------------------------------------
# CoVe verification log
# ---------------------------------------------------------------------------


def _substrate_check(
    root: Path, evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Check a verification's cited source ACTUALLY backs the claim.

    The old behaviour recorded ``supports: true`` exactly as the model
    asserted, with no check against the cited file — a self-asserted
    pass. This binds the assertion to the substrate:

      * The cited ``path`` must resolve under the project root (no path
        traversal, must exist, must be a readable file).
      * Where the verification carries a value/locator to look for
        (``cited_text`` / ``locator`` / ``anchor`` / ``expected`` /
        ``token``), that token must be present in the file's text. For
        numeric tokens, a tolerant numeric match (±0.5% rel) also counts
        so "0.84" matches a corpus "0.8401".

    Returns a verdict dict::

        {"substrate": "confirmed" | "missing_token" | "missing_file"
                      | "no_path" | "no_locator" | "unreadable",
         "checked_path": <rel or None>,
         "locator": <str or None>,
         "detail": <str>}

    ``no_path`` / ``no_locator`` are NOT failures on their own — a
    verification can legitimately cite a reasoning chain rather than a
    file. They downgrade the claim to ``unverified`` (we couldn't
    substantiate it), not to a hard contradiction.
    """
    if not isinstance(evidence, dict):
        return {"substrate": "no_path", "checked_path": None,
                "locator": None,
                "detail": "no evidence object on this verification"}
    rel = evidence.get("path") or evidence.get("file") or evidence.get("source")
    if not rel or not isinstance(rel, str):
        return {"substrate": "no_path", "checked_path": None,
                "locator": None,
                "detail": "verification carries no file path to check"}
    # Resolve safely under root; reject traversal that escapes the project.
    try:
        target = (root / rel).resolve()
        root_resolved = root.resolve()
        target.relative_to(root_resolved)
    except (ValueError, OSError):
        return {"substrate": "missing_file", "checked_path": rel,
                "locator": None,
                "detail": f"path does not resolve under project root: {rel}"}
    if not target.is_file():
        return {"substrate": "missing_file", "checked_path": rel,
                "locator": None,
                "detail": f"cited file not found: {rel}"}

    # The locator: the token/anchor the claim says lives in this file.
    locator = None
    for key in ("cited_text", "locator", "anchor", "expected", "token", "quote"):
        v = evidence.get(key)
        if v not in (None, ""):
            locator = str(v)
            break

    try:
        body = target.read_text(errors="replace")
    except OSError:
        return {"substrate": "unreadable", "checked_path": rel,
                "locator": locator,
                "detail": f"cited file could not be read: {rel}"}

    if locator is None:
        # File exists but the verification gave us nothing to look for.
        # Existence alone is weak grounding → unverified, not confirmed.
        return {"substrate": "no_locator", "checked_path": rel,
                "locator": None,
                "detail": (
                    "cited file exists but no cited_text/locator/anchor "
                    "given to substantiate the claim against it"
                )}

    if _token_present(locator, body):
        return {"substrate": "confirmed", "checked_path": rel,
                "locator": locator,
                "detail": f"locator found in {rel}"}
    return {"substrate": "missing_token", "checked_path": rel,
            "locator": locator,
            "detail": (
                f"locator not present in cited file {rel} — the source "
                "does not contain the quoted text/value"
            )}


def _token_present(locator: str, body: str) -> bool:
    """Is ``locator`` present in ``body`` (verbatim, normalized, or numeric)?

    Three passes, cheapest first:
      1. Verbatim substring (case-sensitive).
      2. Whitespace-normalized, case-folded substring — quotes copied
         from a file often differ only in run-length whitespace/case.
      3. Numeric tolerant match — if the locator is a bare number, look
         for any number in the body within ±0.5% relative difference.
    """
    loc = locator.strip()
    if not loc:
        return False
    if loc in body:
        return True
    norm_loc = re.sub(r"\s+", " ", loc).strip().lower()
    norm_body = re.sub(r"\s+", " ", body).lower()
    if norm_loc and norm_loc in norm_body:
        return True
    # Numeric tolerant match for a bare numeric locator.
    num = _as_number(loc)
    if num is not None:
        for m in re.finditer(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", body, flags=re.I):
            cand = _as_number(m.group(0))
            if cand is None:
                continue
            denom = max(abs(num), abs(cand), 1e-12)
            if abs(cand - num) / denom <= 0.005:
                return True
    return False


def _as_number(tok: str) -> float | None:
    t = tok.strip().replace(",", "")
    if t.endswith("%"):
        t = t[:-1]
    try:
        return float(t)
    except ValueError:
        return None


def claim_verify(
    root: Path,
    *,
    claim: str,
    verifications: list[dict[str, Any]],
    decision_id: str | None = None,
    step_id: str | None = None,
) -> dict[str, Any]:
    """Record CoVe-style verification questions + answers for one claim.

    verifications shaped::

        {"question": "Are variances unequal across the two groups?",
         "answer":   "Levene p < 0.01 → yes",
         "evidence": {"type": "workspace_artefact",
                       "path": ".../residuals.csv",
                       "cited_text": "Levene p = 0.003"},
         "supports": true}

    PROVENANCE-BOUND VERIFICATION
    -----------------------------
    Recording ``supports`` exactly as the model asserts would be a
    self-grading pass. Instead, each verification is checked against its
    cited substrate (see :func:`_substrate_check`):

      * ``supports: true`` is only honoured when the cited file resolves
        AND the claimed token/anchor is actually present in it. A
        verification claiming support whose source does not contain the
        token is downgraded — the recorded ``supports`` becomes ``false``
        and the substrate verdict explains why.
      * A verification with no checkable path/locator is kept as the
        model stated it but flagged ``unverifiable`` — the overall
        verdict for such a claim becomes ``unverified`` (not
        ``verified``), so it can never masquerade as substantiated.

    Resulting per-claim ``verdict``:
      * ``verified``     — every verification supports AND was confirmed
                           against its substrate.
      * ``unverified``   — at least one supporting verification could not
                           be substantiated (no path / no locator) but
                           none was outright contradicted.
      * ``needs_revision`` — at least one verification does not support,
                           OR a claimed-support verification's source
                           does NOT contain the cited token.
    """
    if not verifications:
        return {
            "status": "error",
            "message": "at least one verification entry required",
        }

    checked: list[dict[str, Any]] = []
    n_supports = 0
    n_confirmed = 0
    n_unverifiable = 0
    n_contradicted = 0
    for v in verifications:
        v = dict(v)
        asserted = v.get("supports") is True
        sub = _substrate_check(root, v.get("evidence"))
        v["substrate_check"] = sub
        verdict_sub = sub["substrate"]
        if asserted:
            if verdict_sub == "confirmed":
                n_confirmed += 1
                v["supports"] = True
            elif verdict_sub in ("no_path", "no_locator"):
                # Asserted but not substantiable — keep the assertion but
                # mark it unverifiable; it can't count as confirmed.
                v["supports_unverified"] = True
                v["supports"] = False
                n_unverifiable += 1
            else:
                # missing_file / missing_token / unreadable / missing →
                # the cited source contradicts the asserted support.
                v["supports"] = False
                v["substrate_contradiction"] = True
                n_contradicted += 1
        else:
            # Model itself said this does not support the claim.
            v["supports"] = False
        if v.get("supports") is True:
            n_supports += 1
        checked.append(v)

    n_total = len(verifications)
    if n_contradicted > 0 or n_confirmed < (n_total - n_unverifiable):
        verdict = "needs_revision"
    elif n_unverifiable > 0:
        verdict = "unverified"
    else:
        verdict = "verified"

    rec = {
        "ts": _now(),
        "claim": claim.strip(),
        "decision_id": decision_id,
        "step_id": step_id,
        "verifications": checked,
        "n_total": n_total,
        "n_supports": n_supports,
        "n_confirmed": n_confirmed,
        "n_unverifiable": n_unverifiable,
        "n_contradicted": n_contradicted,
        "verdict": verdict,
    }
    _append_jsonl(_verifications_log(root), rec)
    return {"status": "success", **rec,
            "log_path": str(_verifications_log(root).relative_to(root))}


# ---------------------------------------------------------------------------
# Grounding verification — audit gate
# ---------------------------------------------------------------------------


_DECISION_BLOCK_RE = re.compile(
    r"###\s+Decision\s*[·-]\s*(?P<ts>[^\n]+?)\n+(?P<body>(?:.|\n)*?)"
    r"(?=^###\s|^\[\d{4}-\d{2}-\d{2}|\Z)",
    re.MULTILINE,
)


def _decisions_in_analysis_md(root: Path) -> list[dict[str, str]]:
    analysis = root / "workspace" / "analysis.md"
    if not analysis.exists():
        return []
    text = analysis.read_text()
    out: list[dict[str, str]] = []
    for m in _DECISION_BLOCK_RE.finditer(text):
        body = m.group("body").strip()
        ctx_match = re.search(r"\*\*Context\*\*:\s*(.+)", body)
        sel_match = re.search(r"\*\*Selected\*\*:\s*(.+)", body)
        rat_match = re.search(r"\*\*Rationale\*\*:\s*(.+)", body)
        lit_match = re.search(r"\*\*Linked literature\*\*:\s*(.+)", body)
        key = hashlib.sha256(body.encode()).hexdigest()[:12]
        out.append({
            "decision_key": key,
            "ts": m.group("ts").strip(),
            "context": (ctx_match.group(1) if ctx_match else "")[:200],
            "selected": (sel_match.group(1) if sel_match else "")[:200],
            "rationale": (rat_match.group(1) if rat_match else "")[:300],
            "linked_literature": lit_match.group(1) if lit_match else "",
        })
    return out


def _check_output(root: Path, item: Any, min_bytes: int) -> dict[str, Any] | None:
    """Resolve one declared expected_output and check it exists + is non-empty.

    Returns {path, status: present|empty|missing, bytes, next_action} or None
    when the declaration carries no usable path.
    """
    if isinstance(item, dict):
        path_str = (item.get("path") or "").strip()
    elif isinstance(item, str):
        # "path: human description" — split only when the left side looks like a
        # path (no spaces) so a bare descriptive string isn't truncated.
        if ":" in item and " " not in item.split(":", 1)[0]:
            path_str = item.split(":", 1)[0].strip()
        else:
            path_str = item.strip()
    else:
        path_str = ""
    if not path_str:
        return None

    # Many protocols annotate the path: "workspace/x.log (only on failures)" or
    # "COLLABORATOR.md   top-level, share-safe". Strip a trailing parenthetical
    # or a 2+-space-separated description so we resolve the bare path, and skip
    # entries that are prose rather than a path.
    path_str = re.split(r"\s{2,}|\s+\(", path_str, maxsplit=1)[0].strip()
    if not path_str or path_str.startswith("("):
        return None
    if "/" not in path_str and "." not in path_str and "*" not in path_str:
        return None  # descriptive prose, not a checkable path

    def _size_of(m: Path) -> int:
        if m.is_file():
            return m.stat().st_size
        if m.is_dir():
            return sum(f.stat().st_size for f in m.rglob("*") if f.is_file())
        return 0

    # Defensive: expected_output paths come from (trusted) protocol YAML, but
    # must never resolve outside the project root.
    if ".." in Path(path_str).parts:
        return {
            "path": path_str, "status": "missing", "bytes": 0,
            "next_action": f"INVALID: `{path_str}` escapes the project root.",
        }

    if "*" in path_str or "{" in path_str:
        expanded = path_str.replace("{step_number}", "??").replace("{step_name}", "*")
        matches = [m for m in root.glob(expanded.lstrip("/"))]
        if not matches:
            return {
                "path": path_str, "status": "missing", "bytes": 0,
                "next_action": (
                    f"MISSING: no file matches `{path_str}` — re-run the step "
                    "that produces it before logging the protocol completed."
                ),
            }
        # A match may be a file OR a populated directory (e.g. workspace/*/scripts).
        total = sum(_size_of(m) for m in matches)
        if total >= min_bytes:
            return {
                "path": path_str, "status": "present",
                "bytes": total, "matches": len(matches), "next_action": None,
            }
        return {
            "path": path_str, "status": "empty", "bytes": total, "matches": len(matches),
            "next_action": (
                f"EMPTY: {len(matches)} match(es) for `{path_str}` but they hold "
                f"< {min_bytes}B — regenerate the content (bump a version if a "
                "prior good copy exists)."
            ),
        }

    p = root / path_str
    if not p.exists():
        return {
            "path": path_str, "status": "missing", "bytes": 0,
            "next_action": (
                f"MISSING: `{path_str}` was never created — re-run the step that "
                "produces it before logging the protocol completed."
            ),
        }
    if p.is_file():
        size = p.stat().st_size
    else:
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    if size < min_bytes:
        return {
            "path": path_str, "status": "empty", "bytes": size,
            "next_action": (
                f"EMPTY ({size}B): `{path_str}` exists but has no real content — "
                "regenerate it (bump a version if a prior good copy exists)."
            ),
        }
    return {"path": path_str, "status": "present", "bytes": size, "next_action": None}


def _logged_protocols(root: Path) -> list[str]:
    """Distinct protocols seen in the execution log, oldest→newest."""
    from research_os.tools.actions.protocol import PROTOCOL_LOG_FILE

    log = root / ".os_state" / PROTOCOL_LOG_FILE
    out: list[str] = []
    if not log.exists():
        return out
    for line in log.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        # The log writes 'protocol'; tolerate 'protocol_name' for safety.
        name = e.get("protocol") or e.get("protocol_name")
        if name:
            if name in out:
                out.remove(name)
            out.append(name)
    return out


def _active_protocol(root: Path) -> str | None:
    ap = root / ".os_state" / "active_plan.json"
    if not ap.exists():
        return None
    try:
        return (json.loads(ap.read_text()) or {}).get("primary_protocol")
    except Exception:
        return None


def verify_outputs(
    root: Path,
    *,
    scope: str = "protocol",
    protocol_name: str | None = None,
    min_bytes: int = 1,
) -> dict[str, Any]:
    """Verify declared ``expected_outputs`` exist AND are non-empty.

    The "did the work actually land?" gate, distinct from claim grounding.
    Every protocol declares ``expected_outputs``; this resolves each against
    the filesystem (glob-aware) and returns a per-output verdict plus a
    ``next_action`` telling the AI to regenerate (and bump a version) rather
    than log ``completed`` over a missing or empty file.

    scope:
      * ``protocol`` (default) — check ``protocol_name`` (or the active /
        most-recently-logged protocol).
      * ``project``           — union of expected_outputs across every
        protocol seen in the execution log.
    """
    from research_os.tools.actions.protocol import load_protocol

    if scope not in {"protocol", "project", "step"}:
        return {"status": "error", "message": f"unknown scope '{scope}'"}
    # 'step' has no first-class log key yet → treated as a single-protocol check.
    protos: list[str] = []
    if protocol_name:
        protos = [protocol_name]
    elif scope == "project":
        protos = _logged_protocols(root)
        active = _active_protocol(root)
        if active and active not in protos:
            protos.append(active)
    else:
        active = _active_protocol(root)
        if active:
            protos = [active]
        else:
            logged = _logged_protocols(root)
            protos = logged[-1:] if logged else []
    protos = [p for p in protos if p]
    if not protos:
        return {
            "status": "error",
            "message": (
                "no protocol to verify — pass protocol_name=, or run a protocol "
                "first so it lands in the execution log / active_plan."
            ),
        }

    items: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    checked_protos: list[str] = []
    for pname in protos:
        try:
            data = load_protocol(pname)
        except Exception:
            continue
        checked_protos.append(pname)
        for raw in data.get("expected_outputs", []) or []:
            res = _check_output(root, raw, min_bytes)
            if res is None or res["path"] in seen_paths:
                continue
            seen_paths.add(res["path"])
            items.append(res)

    present = sum(1 for i in items if i["status"] == "present")
    empty = sum(1 for i in items if i["status"] == "empty")
    missing = sum(1 for i in items if i["status"] == "missing")
    total = len(items)
    all_passed = empty == 0 and missing == 0
    if total == 0:
        guidance = (
            "No expected_outputs declared for the checked protocol(s) — nothing "
            "to verify. (This is fine for advisory / no-output protocols.)"
        )
    elif all_passed:
        guidance = (
            f"All {total} declared output(s) present + non-empty. Safe to log "
            "this protocol completed."
        )
    else:
        guidance = (
            f"{missing} missing + {empty} empty of {total} declared output(s). "
            "DO NOT log this protocol 'completed' — regenerate the gaps (bump a "
            "version where a prior good copy exists), then re-run "
            "tool_verify(scope='outputs')."
        )
    return {
        "status": "success",
        "scope": scope,
        "protocols_checked": checked_protos,
        "total": total,
        "present": present,
        "empty": empty,
        "missing": missing,
        "all_passed": all_passed,
        "items": items,
        "guidance": guidance,
    }


def grounding_verify(root: Path) -> dict[str, Any]:
    """Check every analysis.md decision has a grounding record.

    Strategy:
      * Read every Decision block in workspace/analysis.md.
      * If the block declared a linked literature key, treat that as
        sufficient lightweight grounding.
      * Otherwise look up by `decision_key` (sha-256 prefix of the
        block body) in workspace/.grounding/grounding.jsonl.
      * Decisions without either are flagged as UNGROUNDED — a
        master-audit blocker.

    Writes ``workspace/logs/grounding_audit.md``.
    """
    decisions = _decisions_in_analysis_md(root)
    if not decisions:
        return {
            "status": "success",
            "n_decisions": 0,
            "message": "No decisions found in workspace/analysis.md.",
        }

    grounding = _read_jsonl(_grounding_log(root))
    # Index grounding records by claim-prefix so the AI can ground a
    # decision by re-quoting the rationale (decision_id matching is
    # done inline below).
    grounded_claims = {
        g.get("claim", "")[:60].lower() for g in grounding
    }

    grounded: list[dict[str, str]] = []
    ungrounded: list[dict[str, str]] = []
    for d in decisions:
        has_inline_citation = bool(d.get("linked_literature", "").strip())
        has_registry_record = any(
            d["decision_key"] in (g.get("decision_id") or "")
            or d["rationale"][:60].lower() in grounded_claims
            or d["selected"][:60].lower() in grounded_claims
            for g in grounding
        )
        if has_inline_citation or has_registry_record:
            grounded.append(d)
        else:
            ungrounded.append(d)

    # Write report.
    logs = root / "workspace" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out = logs / "grounding_audit.md"
    lines = [
        "# Grounding audit",
        "",
        f"- Total decisions: {len(decisions)}",
        f"- Grounded: {len(grounded)}",
        f"- Ungrounded: {len(ungrounded)}",
        "",
    ]
    if ungrounded:
        lines.append("## Ungrounded decisions")
        for d in ungrounded[:20]:
            lines.append(f"- **{d['ts']}**: {d['selected'][:120]}")
            lines.append(f"  - Rationale: {d['rationale'][:160]}")
            lines.append(
                "  - Fix: call tool_ground(mode='explicit', decision_id=<id>, "
                "claim=\"...\", sources=[{type: paper|context_file|web, …}])"
            )
        if len(ungrounded) > 20:
            lines.append(f"…and {len(ungrounded) - 20} more.")
        lines.append("")
    out.write_text("\n".join(lines) + "\n")

    return {
        "status": "error" if ungrounded else "success",
        "n_decisions": len(decisions),
        "n_grounded": len(grounded),
        "n_ungrounded": len(ungrounded),
        "ungrounded": [
            {"ts": d["ts"], "selected": d["selected"]} for d in ungrounded
        ],
        "report_path": str(out.relative_to(root)),
        "advice": (
            f"{len(ungrounded)} decision(s) carry no grounding record. "
            "For each, call tool_ground(mode='explicit', ...) binding the decision "
            "to the inputs/context/literature that informed it. Or "
            "include a `linked_literature` key in the original "
            "mem_log(kind='decision') call."
            if ungrounded
            else "All decisions in analysis.md are grounded."
        ),
    }


# ---------------------------------------------------------------------------
# Convenience: ground a decision against an inputs/context file directly.
# ---------------------------------------------------------------------------


def ground_from_context(
    root: Path,
    *,
    decision_id: str | None = None,
    claim: str,
    context_paths: list[str],
    cited_excerpts: list[str] | None = None,
    confidence: str = "medium",
) -> dict[str, Any]:
    """Shortcut: build a grounding record from inputs/context/ files.

    Pulls each path's content, picks the matching ``cited_excerpts`` (or
    the first 240 chars), and registers a grounding entry.
    """
    sources: list[dict[str, Any]] = []
    for i, rel in enumerate(context_paths):
        p = root / rel
        if not p.exists():
            return {
                "status": "error",
                "message": f"context file not found: {rel}",
            }
        text = p.read_text(errors="replace")
        cited = (
            (cited_excerpts[i] if cited_excerpts and i < len(cited_excerpts)
             else text[:240])
        ).strip()
        sources.append({
            "type": "context_file",
            "path": rel,
            "cited_text": cited[:400],
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
        })
    return grounding_register(
        root, decision_id=decision_id, claim=claim,
        sources=sources, confidence=confidence,
    )


__all__ = [
    "claim_verify",
    "grounding_for_decision",
    "grounding_register",
    "grounding_verify",
    "ground_from_context",
    "thought_log",
    "thought_trace",
]
