"""Protocol loader, pipeline ordering, and execution log.

A protocol is a YAML file under ``src/research_os/protocols/`` describing a
sequence of steps the AI should take. Each protocol has:

* ``id``, ``name``, ``description``     — metadata
* ``trigger``                            — when the AI should run it
* ``prerequisites``                      — what must be true before running
* ``steps``                              — ordered list of {id, name, description}
* ``expected_outputs``                   — file paths the protocol should produce
* ``next_protocol``                      — what runs after (or null for terminal)
* ``on_failure``                         — fallback protocol when expected outputs missing

Light mode (``model_profile=small``) auto-trims verbose blocks
(``examples``, ``rationale``, ``model_adaptations``) inside the loader so that
small models don't drown in tokens. There is no separate ``light/`` folder —
all protocols are single source of truth.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import msgpack
import yaml

from research_os.protocols.schema import Protocol

logger = logging.getLogger("research_os.tools.protocol")

PROTOCOLS_DIR = Path(__file__).parent.parent.parent / "protocols"
BUNDLE_PATH = PROTOCOLS_DIR / "_protocols.bundle"
PROTOCOL_LOG_FILE = "protocol_execution_log.jsonl"
DEPRECATIONS_LOG_FILE = "deprecations.log"


# ---------------------------------------------------------------------------
# ProtocolRegistry — single-source reader for the compiled _protocols.bundle
# ---------------------------------------------------------------------------
#
# P1 Protocol Unification: one Pydantic model validates every protocol, one
# build script (scripts/build_protocols.py) compiles them into ONE msgpack
# ``_protocols.bundle``. This registry is the single runtime reader — the
# router, gate engine, precondition verifier, semantic layer, and listers
# all go through it instead of parsing YAML or five JSON sidecars.


class _RegistryData:
    """The decoded bundle plus pack-contributed routing entries (immutable)."""

    __slots__ = (
        "schema_version",
        "source_hash",
        "hierarchy",
        "shortcut_intents",
        "protocols",
        "gates",
        "gate_built_from",
        "preconditions",
    )

    def __init__(self, bundle: dict[str, Any]) -> None:
        self.schema_version: str = bundle.get("schema_version", "3.0")
        self.source_hash: str = bundle.get("source_hash", "")
        self.hierarchy: dict[str, Any] = bundle.get("hierarchy", {}) or {}
        self.shortcut_intents: dict[str, Any] = bundle.get("shortcut_intents", {}) or {}
        self.protocols: dict[str, Any] = dict(bundle.get("protocols", {}) or {})
        self.gates: list[dict] = list(bundle.get("gates", []) or [])
        self.gate_built_from: list[str] = list(bundle.get("gate_built_from", []) or [])
        self.preconditions: dict[str, list[dict]] = dict(
            bundle.get("preconditions", {}) or {}
        )


class ProtocolRegistry:
    """Read the compiled bundle; serve typed protocols + derived views.

    All methods are classmethods over a process-lifetime cache. Call
    :meth:`reload` (test hook) after rebuilding the bundle.
    """

    _data: _RegistryData | None = None
    _lock = threading.Lock()

    # ── loading ──────────────────────────────────────────────────────
    @classmethod
    def _load(cls) -> _RegistryData:
        if cls._data is not None:
            return cls._data
        with cls._lock:
            if cls._data is not None:
                return cls._data
            bundle = cls._read_bundle()
            data = _RegistryData(bundle)
            cls._merge_pack_router_entries(data)
            cls._data = data
            return data

    @staticmethod
    def _read_bundle() -> dict[str, Any]:
        """Decode _protocols.bundle. Fail-safe to an empty shape.

        The bundle ships in the package; a missing/garbage bundle yields an
        empty registry (callers keep behaving, just with nothing to route),
        which preflight's check_bundle_fresh turns into a hard CI failure.
        """
        try:
            raw = BUNDLE_PATH.read_bytes()
            data = msgpack.unpackb(raw, raw=False)
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            logger.warning("_protocols.bundle missing — run build_protocols.py")
        except Exception as exc:  # noqa: BLE001
            logger.warning("_protocols.bundle unreadable: %s", exc)
        return {
            "schema_version": "3.0",
            "source_hash": "",
            "hierarchy": {},
            "shortcut_intents": {},
            "protocols": {},
            "gates": [],
            "gate_built_from": [],
            "preconditions": {},
        }

    @staticmethod
    def _merge_pack_router_entries(data: _RegistryData) -> None:
        """Fold pack-contributed routing entries into the protocols map."""
        try:
            from research_os.plugins.loader import pack_router_entries

            for pid, entry in (pack_router_entries() or {}).items():
                if isinstance(entry, dict):
                    merged = dict(entry)
                    merged.setdefault("id", pid.split("/")[-1])
                    data.protocols.setdefault(pid, merged)
        except Exception as exc:  # noqa: BLE001
            logger.debug("pack router-entry merge skipped: %s", exc)

    @classmethod
    def reload(cls) -> None:
        """Drop the cache so a rebuilt bundle is picked up (test hook)."""
        with cls._lock:
            cls._data = None

    # ── typed protocol access ────────────────────────────────────────
    @classmethod
    def get_protocol(cls, name: str) -> Protocol:
        """Return the fully-validated ``Protocol`` model for ``name``.

        Reads the protocol body YAML from disk (core or pack) and validates
        it against the model. The bundle holds the compact routing view; the
        full body (steps, descriptions, …) is loaded from source so callers
        that need the whole protocol get it typed.
        """
        file = _find_protocol_file(name)
        if not file:
            from research_os.server.errors import RoError

            raise RoError(
                what=f"Protocol '{name}' not found",
                why=f"no YAML at {PROTOCOLS_DIR}/{name}.yaml or in installed packs",
                next_action="call sys_protocol_list to see the live catalog.",
            )
        raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        return Protocol.model_validate(raw)

    # ── derived views (served from the bundle) ───────────────────────
    @classmethod
    def get_hierarchy(cls) -> dict[str, Any]:
        """L1 intent_class → {label, sub_intents} taxonomy."""
        return cls._load().hierarchy

    @classmethod
    def get_shortcut_intents(cls) -> dict[str, Any]:
        """Cross-intent tool shortcuts (trigger set → tool)."""
        return cls._load().shortcut_intents

    @classmethod
    def get_routing_map(cls) -> dict[str, Any]:
        """The compact per-protocol routing entries (intent_class, triggers…).

        Shape-compatible with the legacy ``_route_meta.json['protocols']`` so
        the router/semantic layers consume it unchanged.
        """
        return cls._load().protocols

    @classmethod
    def get_index(cls) -> dict[str, Any]:
        """Legacy ``_load_index()`` shape: {protocols, shortcut_intents, hierarchy}."""
        d = cls._load()
        return {
            "protocols": d.protocols,
            "shortcut_intents": d.shortcut_intents,
            "hierarchy": d.hierarchy,
        }

    @classmethod
    def get_gates(cls) -> list[dict]:
        """Every declared floor gate (was ``_gate_meta.json['gates']``)."""
        return cls._load().gates

    @classmethod
    def get_preconditions(cls) -> dict[str, list[dict]]:
        """protocol_id → checkable preconditions (was ``_precondition_meta.json``)."""
        return cls._load().preconditions

    @classmethod
    def list_protocols(cls) -> list[str]:
        """Sorted protocol ids known to the bundle (+ pack entries)."""
        return sorted(cls._load().protocols)

    @classmethod
    def source_hash(cls) -> str:
        """The bundle's compiled source hash (over all protocol YAMLs)."""
        return cls._load().source_hash


def _log_redirect(source: str, target: str, params: dict | None = None) -> None:
    """Append a redirect event to .os_state/deprecations.log (best-effort).

    Resolves project root via RESEARCH_OS_WORKSPACE env var; falls back to
    walking up CWD for `.os_state/`. Silently no-ops if no workspace.
    """
    import os
    root: Path | None = None
    env_root = os.environ.get("RESEARCH_OS_WORKSPACE", "").strip()
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if candidate.exists():
            root = candidate
    if root is None:
        cur = Path.cwd().resolve()
        for p in [cur, *cur.parents]:
            if (p / ".os_state").exists():
                root = p
                break
    if root is None:
        return
    log_dir = root / ".os_state"
    if not log_dir.exists():
        return
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": "protocol_redirect",
        "source": source,
        "target": target,
        "params": params or {},
    }
    try:
        with open(log_dir / DEPRECATIONS_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        # Best-effort telemetry — failing here must never break the load.
        logger.debug("deprecations.log append failed: %s", exc)


# ---------------------------------------------------------------------------
# Execution log
# ---------------------------------------------------------------------------


def log_protocol_execution(
    root: Path, protocol_name: str, status: str, details: str = "",
    *, override_completeness_gate: bool = False,
) -> dict:
    """Append a structured entry to the protocol execution log.

    C1 completeness gate: logging a protocol ``completed`` is now a GATE, not a
    sink. When ``status == "completed"`` and the protocol declares
    ``expected_outputs``, those outputs must exist (and be non-empty) on disk —
    otherwise the completion is REFUSED with ``status="blocked"`` and the
    missing-output checklist, so an AI under context pressure can't mark work
    done that produced nothing. Pass ``override_completeness_gate=True`` to log
    completion anyway (recorded as an override in the entry + override_log.md),
    for the rare legitimate case (e.g. a protocol whose output is intentionally
    external). A protocol with no declared outputs passes trivially. Fail-open:
    if the check itself errors, the completion is logged (never block on a bug).
    """
    log_path = root / ".os_state" / PROTOCOL_LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)

    overridden = False
    if status == "completed" and not override_completeness_gate:
        try:
            v = validate_protocol(protocol_name, root)
            # Only gate when the protocol actually declares outputs AND some are
            # missing (fail). Empty-but-present is advisory, handled elsewhere.
            if (
                isinstance(v, dict)
                and not v.get("error")
                and v.get("expected_count", 0) > 0
                and not v.get("all_passed", True)
            ):
                missing = [
                    c["item"] for c in v.get("checklist", [])
                    if c.get("status") == "fail"
                ]
                return {
                    "status": "blocked",
                    "reason": "completeness_gate",
                    "message": (
                        f"Cannot mark '{protocol_name}' completed: "
                        f"{len(missing)} declared output(s) missing — produce "
                        "them, then log completed. To override (rare, e.g. an "
                        "intentionally-external output), pass "
                        "override_completeness_gate=True (it will be recorded)."
                    ),
                    "missing_outputs": missing,
                    "checklist": v.get("checklist", []),
                }
        except Exception:  # noqa: BLE001 - never block on a gate bug (fail-open)
            # Fail-open is deliberate (a gate bug must not block real work), but
            # log it: a silently fail-open completeness gate means a real missing
            # output slips through invisibly.
            logger.warning(
                "completeness gate evaluation failed (fail-open) for %s",
                protocol_name, exc_info=True,
            )
    elif status == "completed" and override_completeness_gate:
        overridden = True

    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "protocol": protocol_name,
        "status": status,
        "details": details,
    }
    if overridden:
        entry["completeness_override"] = True
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Record the override durably so a reviewer can see a completion bypassed
    # the output gate (matches the doctrine: overrides are logged, not silent).
    if overridden:
        try:
            ov = root / ".os_state" / "override_log.md"
            ov.parent.mkdir(parents=True, exist_ok=True)
            with open(ov, "a") as f:
                f.write(
                    f"- {entry['timestamp']} — `{protocol_name}` logged "
                    "completed with completeness gate OVERRIDDEN "
                    f"(declared outputs not all present). {details}\n"
                )
        except OSError:
            pass

    return {"status": "success", "entry": entry, "completeness_overridden": overridden}


def get_protocol_history(root: Path, limit: int = 20) -> dict:
    """Return the last N protocol execution log entries."""
    log_path = root / ".os_state" / PROTOCOL_LOG_FILE
    entries: list[dict] = []
    if log_path.exists():
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return {"entries": entries[-limit:], "total": len(entries)}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


_LIGHT_DROP_KEYS = {
    "model_adaptations",
    "examples",
    "rationale",
    "rationale_examples",
    "templates",
    "code_templates",
    "long_description",
}

_LEAN_MAX_STEPS = 3
_LEAN_MAX_DESC_CHARS = 200
_LEAN_DROP_KEYS = _LIGHT_DROP_KEYS | {
    "pedagogical_prelude",
    "model_adaptations",
    "alternates",
    "anti_patterns",
}


def _lean_step(step: dict) -> dict:
    """Shrink one step to its load-bearing fields."""
    if not isinstance(step, dict):
        return step
    out: dict = {}
    for key, value in step.items():
        if key in _LEAN_DROP_KEYS:
            continue
        if key == "description" and isinstance(value, str):
            value = value.strip()
            if len(value) > _LEAN_MAX_DESC_CHARS:
                value = value[:_LEAN_MAX_DESC_CHARS].rsplit(" ", 1)[0] + " …"
        if key in {"sub_steps", "optional_sub_steps"}:
            # Drop optional sub-steps; keep mandatory ones if listed under sub_steps.
            if key == "optional_sub_steps":
                continue
        out[key] = value
    return out


def _auto_distill_lean(data: dict) -> dict:
    """Build a lean variant from `full` when no explicit lean_variant block exists."""
    steps = data.get("steps", []) or []
    capped: list[dict] = []
    for step in steps[:_LEAN_MAX_STEPS]:
        if isinstance(step, dict):
            capped.append(_lean_step(step))
        else:
            capped.append(step)
    out = {
        "id": data.get("id"),
        "name": data.get("name", ""),
        "description": (data.get("description") or "").split("\n\n")[0],
        "trigger": data.get("trigger", ""),
        "steps": capped,
        "expected_outputs": data.get("expected_outputs", []),
        "next_protocol": data.get("next_protocol"),
        "_lean_source": "auto-distilled",
        "_dropped_steps": max(0, len(steps) - _LEAN_MAX_STEPS),
        "_path": data.get("_path"),
    }
    return out


def _find_protocol_file(name: str) -> Path | None:
    """Locate ``<protocols>/<category>/<name>.yaml`` (or a pack equivalent).

    Resolution order:
      1. ``<pack>/...`` → if the first path segment matches a registered
         pack name, search the pack's ``protocols_dir`` first.
      2. ``<category>/<name>`` → search core ``PROTOCOLS_DIR``.
      3. Bare ``<name>`` → scan core, then every pack.

    Registry / index files (prefix ``_``) are NOT addressable as protocols.
    """
    pack_dirs = _pack_protocol_dirs_safe()

    if "/" in name:
        head, _, _ = name.partition("/")
        if head in pack_dirs:
            # `<pack>/<category>/<name>` → strip the pack prefix to look
            # under the pack's own tree.
            inner = name.split("/", 1)[1]
            candidate = pack_dirs[head] / f"{inner}.yaml"
            if candidate.exists():
                return candidate
            # Also try the full path verbatim in case the pack uses
            # the pack name as a top-level folder under its tree.
            candidate = pack_dirs[head] / f"{name}.yaml"
            if candidate.exists():
                return candidate
            return None
        candidate = PROTOCOLS_DIR / f"{name}.yaml"
        return candidate if candidate.exists() else None

    # Bare name — scan core first, then packs.
    for yaml_file in PROTOCOLS_DIR.rglob("*.yaml"):
        if "light" in yaml_file.parts:
            continue
        if yaml_file.name.startswith("_"):
            continue
        if yaml_file.stem == name:
            return yaml_file
    for pdir in pack_dirs.values():
        for yaml_file in pdir.rglob("*.yaml"):
            if yaml_file.name.startswith("_"):
                continue
            if yaml_file.stem == name:
                return yaml_file
    return None


def _pack_protocol_dirs_safe() -> dict:
    """Best-effort accessor for the plugin loader's pack-dir map."""
    try:
        from research_os.plugins.loader import pack_protocol_dirs
        return pack_protocol_dirs()
    except Exception:
        return {}


def _trim_for_light(data: dict) -> dict:
    """Drop verbose keys at the top level and within each step."""
    out: dict = {}
    for key, value in data.items():
        if key in _LIGHT_DROP_KEYS:
            continue
        if key == "steps" and isinstance(value, list):
            out["steps"] = []
            for step in value:
                if not isinstance(step, dict):
                    out["steps"].append(step)
                    continue
                out["steps"].append(
                    {k: v for k, v in step.items() if k not in _LIGHT_DROP_KEYS}
                )
        else:
            out[key] = value
    return out


_PROTOCOL_COMPLETION_BLOCK = {
    "id": "protocol_completion",
    "name": "Complete & Log Protocol",
    "description": (
        "Final mandatory step.\n"
        "1. Output check FIRST: call tool_verify(scope='outputs'). It confirms the files this\n"
        "   protocol declared in expected_outputs actually exist AND are non-empty. If any\n"
        "   come back missing or empty, do NOT proceed to log completed — go back and\n"
        "   (re)generate the gap (bump a version if a prior good copy exists), then re-verify.\n"
        "   A protocol with no expected_outputs passes this trivially.\n"
        "2. Once the output check passes, call sys_protocol_log with status='completed' and a\n"
        "   one-line details summary. If the protocol BLOCKED on a gate, log status='failed'\n"
        "   with the blocker count (the next session resumes cleanly from the same point).\n"
        "3. Call sys_checkpoint_create with description='<protocol> completed' — a rollback target\n"
        "   the researcher can return to if a downstream step regresses.\n"
        "4. Call sys_protocol_next to find the pipeline-recommended next protocol. If the\n"
        "   researcher's next message redirects, prefer tool_route on their message over\n"
        "   the pipeline pointer.\n"
        "4b. Path/plan finalize check: if you created or advanced an analysis PATH this\n"
        "   turn, run tool_path_finalize so its README + focal figure/captions reflect what\n"
        "   was produced (sys_boot.paths_summary flags missing_focal_figure/captions). If you\n"
        "   are in an autonomous roadmap loop, append this milestone's outcome to\n"
        "   inputs/research_plan.md's iteration log and score it with tool_judge_score\n"
        "   (ship/iterate/redo) — the verdict drives whether the loop continues or converges.\n"
        "5. Briefly summarise to the researcher in ONE sentence: what changed + what's next.\n"
        "   Skip the summary on shortcut-tool calls (sys_help, sys_protocol_list, etc.) — the\n"
        "   result is already the answer.\n"
        "\n"
        "Grounding check: if this protocol involved methodology or claims, confirm at\n"
        "least one tool_search call was made and logged to workspace/logs/searches.log.\n"
        "If grounding is missing AND the protocol commits a methodology decision, run\n"
        "tool_verify(scope='project') before declaring completion — ungrounded commitments\n"
        "surface in the master audit and slow the eventual synthesis.\n"
        "\n"
        "Override-log check: if the protocol bypassed any quality gate this turn\n"
        "(override_completeness_gate / override_gate), confirm workspace/logs/override_log.md\n"
        "captured the rationale. The pre-submission audit will re-surface every unresolved\n"
        "bypass — silent bypasses become RED at publish time."
    ),
}


def _inject_completion_step(data: dict) -> dict:
    """Append the standard completion step if not already present."""
    steps = data.get("steps", []) or []
    has_completion = any(
        isinstance(s, dict) and s.get("id") == "protocol_completion" for s in steps
    )
    if not has_completion:
        steps = list(steps) + [_PROTOCOL_COMPLETION_BLOCK]
        data["steps"] = steps
    return data


def load_protocol(
    name: str,
    model_profile: str = "medium",
    *,
    format: str = "full",
    step_id: str | None = None,
    _redirect_chain: tuple[str, ...] | None = None,
) -> dict:
    """Load a protocol YAML and post-process it.

    Args:
        name: ``"guidance/project_startup"`` or bare ``"project_startup"``.
        model_profile: ``small`` | ``medium`` | ``large``. ``small`` trims verbose
                       keys (model_adaptations, examples, etc.) to save tokens.
        format: ``ref`` | ``full`` (default) | ``summary`` | ``step`` |
                ``lean`` | ``dryrun``. The three canonical load tiers are
                ``ref`` (~50 tok: id + summary + step count), ``summary``
                (~200 tok), and ``full``; ``step`` / ``lean`` / ``dryrun``
                are specialised variants.
                * ``ref`` returns id + name + one-line summary + step
                  count — the cheapest peek before pulling more.
                * ``summary`` returns id + name + description + step
                  headings + expected_outputs + next_protocol + quality_bar
                  — roughly 300 tokens vs 2K for the full load.
                * ``step`` requires ``step_id`` and returns just that step
                  body plus its position in the protocol.
                * ``lean`` returns the protocol's explicit ``lean_variant:``
                  block if present, else auto-distills (cap at 3 steps,
                  drop optional sub-steps, trim step descriptions to 200
                  chars). For small / fast models.
                * ``dryrun`` returns the protocol's full tool-call
                  sequence with predicted arg shapes, without executing.
                  For supervised review before commit.
        step_id: which step to load when ``format='step'``.
    """
    file = _find_protocol_file(name)
    if not file:
        # Build a nearest-match suggestion list so the AI gets a "did you
        # mean" hint instead of just "not found".
        try:
            import difflib
            available = [
                p.relative_to(PROTOCOLS_DIR).with_suffix("").as_posix()
                for p in PROTOCOLS_DIR.rglob("*.yaml")
                if not p.name.startswith("_")
            ]
            for pdir in _pack_protocol_dirs_safe().values():
                available.extend(
                    p.relative_to(pdir).with_suffix("").as_posix()
                    for p in pdir.rglob("*.yaml") if not p.name.startswith("_")
                )
            suggestions = difflib.get_close_matches(name, available, n=3, cutoff=0.6)
        except Exception:
            suggestions = []
        suffix = (
            f" Did you mean: {', '.join(suggestions)}?"
            if suggestions else ""
        )
        from research_os.server.errors import RoError
        raise RoError(
            what=f"Protocol '{name}' not found",
            why=f"no YAML at {PROTOCOLS_DIR}/{name}.yaml or in installed packs",
            next_action=(
                f"call sys_protocol_list to see the live catalog.{suffix}"
            ),
        )
    with open(file) as f:
        data = yaml.safe_load(f) or {}

    # Redirect-stub support: a stub YAML carries `redirect_to: <target_name>`
    # (and optional
    # `redirect_params: {key: value}`). The stub is reduced to a thin
    # alias: the target is loaded, the source name is recorded on the
    # result for traceability, and any params are injected into the
    # `_redirect_params` field for the caller. Loops are detected via
    # a seen-set; cycles raise. Stubs must NOT carry `steps:`; the
    # preflight check enforces that.
    redirect_target = data.get("redirect_to")
    if isinstance(redirect_target, str) and redirect_target.strip():
        target = redirect_target.strip()
        params = data.get("redirect_params", {}) or {}
        try:
            _log_redirect(name, target, params)
        except Exception as exc:
            logger.debug("redirect-log failed for %s: %s", name, exc)
        # Cycle detection across the whole redirect chain (not just self).
        chain = (_redirect_chain or ()) + (name, target)
        target_norm = target.split("/")[-1]
        name_norm = name.split("/")[-1]
        chain_norms = {c.split("/")[-1] for c in (_redirect_chain or ())}
        if target_norm in chain_norms or target_norm == name_norm:
            raise ValueError(
                f"Redirect cycle detected: {' -> '.join(chain)}"
            )
        resolved = load_protocol(
            target,
            model_profile=model_profile,
            format=format,
            step_id=step_id,
            _redirect_chain=chain,
        )
        if isinstance(resolved, dict):
            resolved.setdefault("_redirected_from", name)
            if params:
                resolved.setdefault("_redirect_params", params)
        return resolved

    # Inject any per-profile step overrides explicitly attached as
    # ``model_adaptations: {small: {step_id: {key: value}}}``.
    adaptations = data.get("model_adaptations", {})
    if isinstance(adaptations, dict) and model_profile in adaptations:
        overrides = adaptations.get(model_profile) or {}
        if isinstance(overrides, dict):
            for sid, patch in overrides.items():
                if not isinstance(patch, dict):
                    continue
                for step in data.get("steps", []):
                    if isinstance(step, dict) and step.get("id") == sid:
                        step.update(patch)

    if model_profile == "small":
        data = _trim_for_light(data)

    data = _inject_completion_step(data)
    data.setdefault("name", name.split("/")[-1])
    try:
        rel = str(file.relative_to(PROTOCOLS_DIR))
    except ValueError:
        # Pack protocol — file lives outside the core PROTOCOLS_DIR.
        # Try each registered pack dir; fall back to the absolute path.
        rel = str(file)
        for pack_name, pdir in _pack_protocol_dirs_safe().items():
            try:
                inner = file.relative_to(pdir)
                rel = f"{pack_name}/{inner}"
                break
            except ValueError:
                continue
    data.setdefault("_path", rel)

    if format == "ref":
        # Cheapest load (~50 tokens): identity + one-line summary + step
        # count. For the router/AI to decide whether to pull summary/full.
        steps = data.get("steps", []) or []
        registry_summary = ""
        try:
            registry_summary = (
                ProtocolRegistry.get_routing_map().get(name, {}).get("summary", "")
            )
        except Exception:
            registry_summary = ""
        return {
            "id": data.get("id", name.split("/")[-1]),
            "name": data.get("name", ""),
            "summary": (
                data.get("summary")
                or registry_summary
                or (data.get("description") or "").split("\n")[0]
            ),
            "step_count": len([s for s in steps if isinstance(s, dict)]),
            "_path": data.get("_path"),
            "_load_hint": (
                f"Loaded as ref (~50 tok). For step headings call format='summary'; "
                f"for the full body call format='full'."
            ),
        }

    if format == "summary":
        steps = data.get("steps", []) or []
        return {
            "id": data.get("id", name.split("/")[-1]),
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "trigger": data.get("trigger", ""),
            "prerequisites": data.get("prerequisites", []),
            "step_summary": [
                {"id": s.get("id", ""), "name": s.get("name", "")}
                for s in steps
                if isinstance(s, dict)
            ],
            "expected_outputs": data.get("expected_outputs", []),
            "quality_bar": data.get("quality_bar", ""),
            "next_protocol": data.get("next_protocol"),
            "on_failure": data.get("on_failure"),
            "_path": data.get("_path"),
            "_load_hint": (
                f"Loaded as summary. For one specific step body call "
                f"sys_protocol_get name='{name}' format='step' step_id='<id>'. "
                f"For the full YAML use format='full'."
            ),
        }

    if format == "lean":
        explicit = data.get("lean_variant")
        if isinstance(explicit, dict) and explicit:
            out = dict(explicit)
            out.setdefault("id", data.get("id"))
            out.setdefault("name", data.get("name", ""))
            out.setdefault("_path", data.get("_path"))
            out["_lean_source"] = "explicit"
            return out
        return _auto_distill_lean(data)

    if format == "dryrun":
        import re
        steps = data.get("steps", []) or []
        tool_call_pat = re.compile(r"\b((?:sys|tool|mem)_[a-z0-9_]+)\b")
        sequence: list[dict] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            desc = step.get("description") or ""
            tool_calls = sorted(set(tool_call_pat.findall(desc)))
            sequence.append({
                "step_id": step.get("id"),
                "name": step.get("name", ""),
                "predicted_tool_calls": tool_calls,
            })
        return {
            "id": data.get("id"),
            "name": data.get("name", ""),
            "format": "dryrun",
            "sequence": sequence,
            "total_steps": len(sequence),
            "total_predicted_tool_calls": sum(len(s["predicted_tool_calls"]) for s in sequence),
            "_load_hint": (
                "dryrun preview — no tool calls were executed. "
                "Use format='full' to load the actual protocol body."
            ),
        }

    if format == "step":
        if not step_id:
            raise ValueError("format='step' requires step_id")
        steps = data.get("steps", []) or []
        match = next(
            (s for s in steps if isinstance(s, dict) and s.get("id") == step_id),
            None,
        )
        if not match:
            raise ValueError(
                f"Step '{step_id}' not in protocol '{name}'. "
                f"Available: {[s.get('id') for s in steps if isinstance(s, dict)]}"
            )
        step_ids = [s.get("id") for s in steps if isinstance(s, dict)]
        idx = step_ids.index(step_id)
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "step": match,
            "position": idx + 1,
            "of": len(step_ids),
            "previous_step_id": step_ids[idx - 1] if idx > 0 else None,
            "next_step_id": step_ids[idx + 1] if idx + 1 < len(step_ids) else None,
        }

    return data


def list_protocols(category: str | None = None) -> list[dict]:
    """Return every protocol with name, one-line summary, and source pack.

    Walks both the in-tree ``PROTOCOLS_DIR`` and every pack-registered
    ``protocols_dir`` returned by :func:`_pack_protocol_dirs_safe`, so the
    full multi-pack catalog is visible to ``sys_protocol_list``. Pack
    protocols (humanities, qualitative, theory_math, wet_lab, engineering,
    plus externally installed packs) are first-class catalog entries
    alongside core protocols and are tagged with their source via
    ``pack_or_core``.

    Args:
      category: Optional first-segment filter (e.g. ``"theory_math"``,
        ``"audit"``, ``"guidance"``). For core protocols the first segment
        of the relative path is matched; for pack protocols the pack name
        itself counts as a match so that ``category="theory_math"`` returns
        every protocol contributed by that pack.
    """
    out: list[dict] = []
    for name, yaml_file, source in _iter_protocol_files():
        if category is not None:
            first = name.split("/", 1)[0] if name else ""
            if source == "core":
                if first != category:
                    continue
            else:
                # Pack protocols match either by pack name or by the inner
                # category segment (e.g. ``theory_math/proof/...`` matches
                # both ``category="theory_math"`` and ``category="proof"``).
                inner = name.split("/")
                inner_cat = inner[1] if len(inner) > 1 else source
                if category != source and category != inner_cat:
                    continue
        summary = ""
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}
            summary = (data.get("description") or "").split("\n")[0]
        except Exception:
            pass
        out.append({"name": name, "summary": summary, "pack_or_core": source})
    return out


def _shorten(text: str, limit: int = 160) -> str:
    """Return the first line of ``text``, hard-capped at ``limit`` chars."""
    if not text:
        return ""
    first = str(text).strip().split("\n", 1)[0].strip()
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    return first


def _iter_protocol_files() -> list[tuple[str, Path, str]]:
    """Yield (name, yaml_file, pack_or_core) for every addressable protocol.

    Scans the core ``PROTOCOLS_DIR`` plus every pack-registered
    ``protocols_dir``. ``pack_or_core`` is the literal string ``"core"``
    for in-tree core protocols, else the pack name.
    """
    out: list[tuple[str, Path, str]] = []
    for yaml_file in sorted(PROTOCOLS_DIR.rglob("*.yaml")):
        if "light" in yaml_file.parts:
            continue
        if yaml_file.name.startswith("_"):
            continue
        rel = yaml_file.relative_to(PROTOCOLS_DIR).with_suffix("")
        name = str(rel).replace("\\", "/")
        out.append((name, yaml_file, "core"))
    for pack_name, pdir in _pack_protocol_dirs_safe().items():
        if not pdir.exists():
            continue
        for yaml_file in sorted(pdir.rglob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue
            rel = yaml_file.relative_to(pdir).with_suffix("")
            inner = str(rel).replace("\\", "/")
            # Pack protocols are addressed as ``<pack>/<inner>`` from
            # core; preserve the prefix even when the YAML already lives
            # inside a ``<pack>/`` sub-folder.
            if inner.startswith(f"{pack_name}/"):
                name = inner
            else:
                name = f"{pack_name}/{inner}"
            out.append((name, yaml_file, pack_name))
    return out


def list_protocols_flat(
    *,
    category: str | None = None,
    pack: str | None = None,
    include_pack_protocols: bool = True,
) -> list[dict]:
    """Flat protocol catalog with category + pack + routing metadata.

    Each entry::

        {
          "name": "guidance/session_boot",
          "category": "guidance",
          "pack_or_core": "core",
          "intent_class": "session",
          "tier": "intake",    # from the protocol YAML's `tier:` field
          "version": "1.11.0",
          "description_short": "First protocol of every session ..."
        }

    Args:
      category:  Filter to a single category (first path segment, e.g.
                 ``"guidance"``, ``"audit"``). ``None`` = no filter.
      pack:     Filter to a single source: ``"core"`` or a pack name.
                ``None`` = no filter.
      include_pack_protocols:  When ``False``, skip every pack-contributed
                 protocol regardless of ``pack``. Defaults to ``True``.

    Reads the router index once to map each protocol to its
    ``intent_class``. Protocols that exist on disk but are missing from
    the router index appear with ``intent_class=None``.
    """
    # One-shot routing-map pull from the bundle so each protocol's
    # intent_class lookup is O(1).
    try:
        router_protocols = ProtocolRegistry.get_routing_map()
    except Exception:
        router_protocols = {}

    out: list[dict] = []
    for name, yaml_file, source in _iter_protocol_files():
        if not include_pack_protocols and source != "core":
            continue
        if pack is not None and source != pack:
            continue
        # Category = first path segment (before any "/"). Pack protocols
        # also expose a category — the directory the file sits in inside
        # the pack tree. For ``humanities/close_reading`` that's
        # ``humanities`` itself; for ``humanities/research/foo`` it's
        # ``research``.
        parts = name.split("/")
        if source == "core":
            cat = parts[0] if parts else ""
        else:
            # Drop pack prefix; first remaining segment is the category.
            inner_parts = parts[1:] if len(parts) > 1 else parts
            cat = inner_parts[0] if len(inner_parts) > 1 else source
        if category is not None and cat != category:
            continue

        intent_class = None
        version = None
        description = ""
        tier_val: str | None = None
        router_entry = router_protocols.get(name) if isinstance(router_protocols, dict) else None
        if isinstance(router_entry, dict):
            intent_class = router_entry.get("intent_class")
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f) or {}
            description = data.get("description") or router_entry.get("summary", "") if router_entry else (data.get("description") or "")
            version = data.get("version")
            tier_val = data.get("tier")
            if intent_class is None:
                intent_class = data.get("intent_class")
        except Exception:
            pass

        out.append({
            "name": name,
            "category": cat,
            "pack_or_core": source,
            "intent_class": intent_class,
            "tier": tier_val,
            "version": str(version) if version is not None else None,
            "description_short": _shorten(description),
        })
    out.sort(key=lambda e: (e["pack_or_core"], e["category"], e["name"]))
    return out


# ---------------------------------------------------------------------------
# Pipeline ordering
# ---------------------------------------------------------------------------

# Each entry: (protocol_name, predicate(root) -> bool) — "done" means the AI
# can move on. Predicates check both the execution log AND key output files,
# so the pipeline survives a workspace migrated from outside Research OS.


def _has(root: Path, *paths: str) -> bool:
    return all((root / p).exists() for p in paths)


def _has_any(root: Path, glob_pattern: str) -> bool:
    return bool(list(root.glob(glob_pattern)))


def _has_experiment(root: Path, marker: str = "conclusions.md") -> bool:
    workspace = root / "workspace"
    if not workspace.exists():
        return False
    for child in workspace.iterdir():
        if child.is_dir() and child.name[:2].isdigit() and "__DEAD_END" not in child.name:
            mfile = child / marker
            if mfile.exists() and len(mfile.read_text()) > 200:
                return True
    return False


def _protocol_completed(root: Path, name: str) -> bool:
    """True if the protocol has logged a 'completed' status."""
    log = root / ".os_state" / PROTOCOL_LOG_FILE
    if not log.exists():
        return False
    try:
        for line in log.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("protocol") == name and entry.get("status") == "completed":
                return True
    except Exception:
        return False
    return False


def _any_protocol_logged(root: Path) -> bool:
    log = root / ".os_state" / PROTOCOL_LOG_FILE
    if not log.exists():
        return False
    try:
        return any(line.strip() for line in log.read_text().splitlines())
    except Exception:
        return False


def _has_real_research_question(root: Path) -> bool:
    """True if docs/research_overview.md has been filled in (placeholder gone)."""
    p = root / "docs" / "research_overview.md"
    if not p.exists():
        return False
    text = p.read_text().lower()
    # Any of these substrings signals an unfilled placeholder.
    placeholder_markers = (
        "(to be",
        "(blank",
        "(to be confirmed",
        "fill out the intake",
        "*(to be determined)*",
    )
    if any(marker in text for marker in placeholder_markers):
        return False
    # Beyond a placeholder, require at least some real prose.
    return len(text.strip()) > 200


# Each step is considered done when EITHER the protocol logged completion OR
# its hallmark on-disk artifact exists with real content.
#
# The analysis prefix (session boot → project startup → domain → methodology
# → literature → analysis_plan → reproducibility → audit_and_validation) is
# UNIVERSAL — every research project needs it regardless of declared
# output_types. Synthesis tail is dynamic: chosen from
# researcher_config.yaml#research_goal.output_types so the loader stops
# pushing every project toward a paper. Empty output_types falls back to
# synthesis/synthesis_paper as the terminal (legacy fallback, so
# existing projects don't regress).

_ANALYSIS_PIPELINE: list[tuple[str, Any]] = [
    (
        "guidance/session_boot",
        lambda r: _any_protocol_logged(r) or _protocol_completed(r, "guidance/session_boot"),
    ),
    (
        "guidance/project_startup",
        lambda r: _protocol_completed(r, "guidance/project_startup")
        or _has_real_research_question(r),
    ),
    (
        "domain/domain_analysis",
        lambda r: _protocol_completed(r, "domain/domain_analysis")
        or _has(r, "docs/domain_summary.md"),
    ),
    (
        "domain/research_design",
        lambda r: _protocol_completed(r, "domain/research_design")
        or _has(r, "docs/research_design.md"),
    ),
    (
        "methodology/methodology_selection",
        lambda r: _protocol_completed(r, "methodology/methodology_selection")
        or (
            _has(r, "workspace/methods.md")
            and (r / "workspace" / "methods.md").stat().st_size > 400
        ),
    ),
    (
        "literature/literature_search",
        lambda r: _protocol_completed(r, "literature/literature_search")
        or (_has(r, "inputs/literature_index.yaml") and _has(r, "workspace/citations.md") and (r / "workspace" / "citations.md").stat().st_size > 200),
    ),
    (
        "guidance/analysis_plan",
        lambda r: _has_experiment(r, "conclusions.md"),
    ),
    (
        "reproducibility/reproducibility",
        lambda r: _protocol_completed(r, "reproducibility/reproducibility")
        or _has_any(r, "workspace/*/environment/requirements.txt"),
    ),
    (
        "audit/audit_and_validation",
        lambda r: _protocol_completed(r, "audit/audit_and_validation")
        or _has(r, "workspace/logs/audit_report.md"),
    ),
]


# Maps each output_types keyword the wizard accepts (researcher_config.yaml
# template line 113) to its synthesis protocol + the predicate that marks
# that protocol "done" on disk. Keys are lowercased, hyphens stripped, so
# `lay_summary` / `lay-summary` / `Lay Summary` all match.
SYNTHESIS_OUTPUT_TYPE_MAP: dict[str, tuple[str, Any]] = {
    "paper": (
        "synthesis/synthesis_paper",
        lambda r: (
            (_has(r, "synthesis/paper.md") and (r / "synthesis" / "paper.md").stat().st_size > 1000)
            or _has(r, "synthesis/paper.pdf")
        ),
    ),
    "dashboard": (
        "synthesis/synthesis_dashboard",
        lambda r: _has(r, "synthesis/dashboard.html")
        and (r / "synthesis" / "dashboard.html").stat().st_size > 1000,
    ),
    "poster": (
        "synthesis/synthesis_poster",
        lambda r: _has(r, "synthesis/poster.pdf") or _has(r, "synthesis/poster.typ"),
    ),
    "slides": (
        "synthesis/synthesis_slides",
        lambda r: _has(r, "synthesis/slides.pdf") or _has(r, "synthesis/slides.typ"),
    ),
    "report": (
        "synthesis/synthesis_report",
        lambda r: _has(r, "synthesis/report.pdf") or _has(r, "synthesis/report.typ") or _has(r, "synthesis/report.md"),
    ),
    "lay_summary": (
        "synthesis/synthesis_lay_summary",
        lambda r: _has(r, "synthesis/lay_summary.md"),
    ),
    "grant": (
        "synthesis/synthesis_grant",
        lambda r: _has(r, "synthesis/grant.pdf") or _has(r, "synthesis/grant.typ"),
    ),
    "abstract": (
        "synthesis/synthesis_abstract",
        lambda r: _has(r, "synthesis/abstract.md") or _has(r, "synthesis/abstract.typ"),
    ),
    "essay": (
        "synthesis/humanities_essay_structure",
        lambda r: _has(r, "synthesis/essay.pdf") or _has(r, "synthesis/essay.typ"),
    ),
    "handout": (
        "synthesis/printable",
        lambda r: _has(r, "synthesis/handout.pdf") or _has(r, "synthesis/handout.typ"),
    ),
}


def _normalise_output_kind(kind: str) -> str:
    """Map any AI-input spelling to the canonical SYNTHESIS_OUTPUT_TYPE_MAP key."""
    if not isinstance(kind, str):
        return ""
    return kind.strip().lower().replace("-", "_").replace(" ", "_")


def _declared_output_types(root: Path) -> list[str]:
    """Return the lowercased, deduplicated list of declared output_types.

    Empty list ⇒ caller treats as "open" (no preference declared). A
    missing config file is treated identically to an empty list; the
    wizard hasn't seeded the project yet, so we don't gate.
    """
    cfg_path = root / "inputs" / "researcher_config.yaml"
    if not cfg_path.exists():
        return []
    try:
        from research_os.tools.actions.state.config import get_config
    except Exception:
        return []
    res = get_config(root)
    if res.get("status") != "success":
        return []
    raw = (
        ((res.get("config") or {}).get("research_goal") or {}).get("output_types") or []
    )
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        norm = _normalise_output_kind(item)
        if not norm or norm == "exploratory":
            # 'exploratory' is the explicit "no deliverable yet" marker;
            # it doesn't promote any synthesis protocol.
            continue
        if norm not in seen:
            seen.append(norm)
    return seen


def _synthesis_tail(root: Path) -> list[tuple[str, Any]]:
    """Return the synthesis tail of the pipeline filtered by output_types.

    Empty output_types ⇒ ``synthesis/synthesis_paper`` only (legacy
    fallback), so projects that haven't filled out the wizard's
    output_types field don't regress.
    """
    declared = _declared_output_types(root)
    if not declared:
        return [SYNTHESIS_OUTPUT_TYPE_MAP["paper"]]
    tail: list[tuple[str, Any]] = []
    for kind in declared:
        entry = SYNTHESIS_OUTPUT_TYPE_MAP.get(kind)
        if entry and entry not in tail:
            tail.append(entry)
    if not tail:
        # Researcher's output_types listed only unknown strings — fall
        # back to paper so the loader still has a terminal step.
        return [SYNTHESIS_OUTPUT_TYPE_MAP["paper"]]
    return tail


def _full_pipeline(root: Path) -> list[tuple[str, Any]]:
    """Analysis prefix + synthesis tail filtered by declared outputs."""
    return list(_ANALYSIS_PIPELINE) + _synthesis_tail(root)


# Backwards-compat alias for callers that import the legacy name. New
# code should use _full_pipeline(root) so the synthesis tail respects
# researcher_config.yaml#research_goal.output_types.
PIPELINE: list[tuple[str, Any]] = list(_ANALYSIS_PIPELINE) + [
    SYNTHESIS_OUTPUT_TYPE_MAP["paper"]
]


def get_next_protocol(root: Path) -> dict:
    """Return the recommended next protocol based on workspace state.

    The pipeline is the universal analysis prefix
    (session_boot → project_startup → ... → audit_and_validation)
    followed by a synthesis tail filtered by
    ``researcher_config.yaml#research_goal.output_types``. A project
    that declared ``output_types: [dashboard]`` will see
    ``synthesis/synthesis_dashboard`` as its terminal step, NOT
    ``synthesis_paper``. Projects with empty ``output_types`` fall
    back to ``synthesis_paper`` so the legacy behaviour is preserved.
    """
    pipeline = _full_pipeline(root)
    for protocol_name, predicate in pipeline:
        try:
            done = predicate(root)
        except Exception:
            done = False
        if not done:
            return {
                "next_protocol": protocol_name,
                "reason": f"Outputs of '{protocol_name}' not yet present.",
                "pipeline_position": [name for name, _ in pipeline].index(protocol_name) + 1,
                "pipeline_total": len(pipeline),
                "declared_output_types": _declared_output_types(root),
            }
    declared = _declared_output_types(root)
    deliverables = ", ".join(declared) if declared else "paper"
    return {
        "next_protocol": None,
        "reason": (
            f"Pipeline complete — analysis + {deliverables} outputs all present."
        ),
        "pipeline_position": len(pipeline),
        "pipeline_total": len(pipeline),
        "declared_output_types": declared,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_protocol(name: str, root: Path | None = None) -> dict:
    """Check each declared expected_output against the filesystem."""
    try:
        data = load_protocol(name)
        expected_outputs = data.get("expected_outputs", []) or []

        checklist: list[dict] = []
        all_passed = True
        empty_count = 0

        if root:
            for item in expected_outputs:
                if isinstance(item, dict):
                    path_str = item.get("path", "")
                elif ":" in item:
                    path_str = item.split(":")[0].strip()
                else:
                    path_str = item.strip()

                if not path_str:
                    continue

                non_empty = False
                if "*" in path_str or "{" in path_str:
                    # Use glob — drop curly placeholders ({step_name}) since we
                    # only know step folders by pattern.
                    expanded = path_str.replace("{step_number}", "??").replace(
                        "{step_name}", "*"
                    )
                    matches = list(root.glob(expanded.lstrip("/")))
                    status = "pass" if matches else "fail"
                    # A glob match can be a file OR a populated directory.
                    non_empty = any(
                        (m.is_file() and m.stat().st_size > 0)
                        or (m.is_dir() and any(f.is_file() for f in m.rglob("*")))
                        for m in matches
                    )
                else:
                    p = root / path_str
                    status = "pass" if p.exists() else "fail"
                    if p.exists():
                        non_empty = (
                            p.stat().st_size > 0 if p.is_file()
                            else any(f.is_file() for f in p.rglob("*"))
                        )

                entry = {"item": path_str, "status": status, "non_empty": non_empty}
                # Existing files that are empty are an advisory gap — the
                # output-existence gate (tool_verify scope='outputs') treats
                # them as a hard blocker, but validate_protocol stays
                # existence-authoritative for back-compat.
                if status == "pass" and not non_empty:
                    empty_count += 1
                    entry["next_action"] = (
                        f"`{path_str}` exists but is empty — regenerate it."
                    )
                elif status == "fail":
                    entry["next_action"] = (
                        f"`{path_str}` is missing — re-run the step that produces it."
                    )
                checklist.append(entry)
                if status == "fail":
                    all_passed = False

        return {
            "protocol": name,
            "checklist": checklist,
            "all_passed": all_passed,
            "all_present_nonempty": all_passed and empty_count == 0,
            "empty_count": empty_count,
            "expected_count": len(expected_outputs),
            "next_protocol": data.get("next_protocol"),
        }
    except FileNotFoundError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"validate_protocol failed: {e}")
        return {"error": str(e)}
