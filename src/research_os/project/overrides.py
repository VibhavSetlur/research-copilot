"""Override-gate validation, logging, and enforcement helpers.

These are the canonical implementations used across all gate handlers.
``project_ops`` re-exports them for backward compat.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_os.utils.common import now_iso


#: Common low-effort placeholder strings that small models emit when
#: asked for an override rationale. Rejected case-insensitively after
#: stripping whitespace. ai-qwen audit (W11) explicitly flagged 'TODO'
#: and 'preview' as the most common small-model placeholders.
_OVERRIDE_RATIONALE_PLACEHOLDERS = frozenset({
    "",
    "todo",
    "test",
    "preview",
    "tmp",
    "temporary",
    "idk",
    "na",
    "n/a",
    "placeholder",
    "tbd",
    "fix later",
    "check later",
})


def validate_override_rationale(rationale: str | None) -> dict | None:
    """Return an error envelope dict if *rationale* is too thin, else None.

    Rules (all must pass for an override to be accepted):
      1. ``rationale.strip()`` must be at least 20 characters.
      2. ``rationale.strip().lower()`` must NOT be in the placeholder set.
      3. ``rationale.strip()`` must contain at least one whitespace
         character (rejects single-word rationales).

    Callers should:

        from research_os.project_ops import validate_override_rationale
        err = validate_override_rationale(rationale)
        if err is not None:
            return _text(err)

    Returning a pre-built error envelope (rather than raising) keeps the
    call-site shape identical to existing override checks.
    """
    from research_os.server.envelopes import _error

    text = (rationale or "").strip()
    lowered = text.lower()
    n = len(text)
    is_placeholder = lowered in _OVERRIDE_RATIONALE_PLACEHOLDERS
    is_single_word = bool(text) and (" " not in text and "\t" not in text)
    if n < 20 or is_placeholder or is_single_word:
        return _error(
            what="override_rationale_too_thin",
            why=f"rationale {n} chars, single-word/placeholder",
            next_action=(
                'Provide a substantive rationale (>=20 chars, multiple '
                'words). Example: "3pm preview for PI; methods.md is '
                'still a stub but figures are final."'
            ),
        )
    return None


def log_override(
    root: Path,
    *,
    tool: str,
    gate: str,
    rationale: str | None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Append a researcher-authorised gate bypass to the override log.

    Every time the AI calls a tool with ``override_completeness_gate=true``
    (or ``override_gate=true`` on ``tool_plan(operation='advance')``), we record:

    * which tool was bypassed
    * which gate it was
    * the rationale the researcher supplied (or ``<none provided>`` —
      this surfaces in audits as a soft warning)
    * a UTC timestamp

    The log lives at ``workspace/logs/override_log.md`` so the
    pre-submission audit can list every bypass and ask the researcher
    to confirm before publication.
    """
    logs = root / "workspace" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / "override_log.md"
    if not log.exists():
        log.write_text(
            "# Quality-gate bypass log\n\n"
            "Every entry here represents a moment the researcher "
            "explicitly authorised the AI to bypass a quality gate. "
            "The pre-submission audit surfaces this list — confirm "
            "each bypass was intentional before submission.\n\n"
        )
    note = (rationale or "").strip() or "<no rationale provided — flag in audit>"
    extras = ""
    if extra:
        try:
            extras = " · " + json.dumps(extra, sort_keys=True, default=str)
        except Exception:
            extras = ""
    with log.open("a") as fh:
        fh.write(f"- {now_iso()} · `{tool}` · gate={gate} · {note}{extras}\n")
    return log


def enforce_override(
    root: Path,
    *,
    requested: bool,
    rationale: str | None,
    tool: str,
    gate: str,
    blocked: bool,
    extra: dict[str, Any] | None = None,
    empty_msg: str | None = None,
) -> dict | None:
    """One-stop override enforcement for quality gates (the canonical sequence).

    Replaces the require-rationale → reject-thin → log_override block that was
    hand-rolled across many gate handlers (and had drifted: some sites skipped
    the empty-rationale guard, and one never journaled the bypass at all).

    Returns either:
      * an ``_error`` envelope dict — caller must ``return _text(that)``
        (rationale missing-when-required, or too thin); OR
      * ``None`` — proceed. When ``requested and blocked`` is True the bypass has
        already been journaled to override_log.md as a side effect.

    The ``blocked`` trigger varies per auditor (``blockers`` vs
    ``bypassed_blockers`` vs ``override_no_pdfs``), so the caller passes a
    pre-computed bool rather than the helper inspecting the result shape. Typical
    use::

        err = enforce_override(root, requested=req, rationale=r, tool="tool_x",
                               gate="g", blocked=bool(res.get("blockers")))
        if err is not None:
            return _text(err)
        if req and res.get("blockers"):
            res["override_applied"] = True; res["status"] = "success"
    """
    from research_os.server.envelopes import _error

    if requested and not (rationale and str(rationale).strip()):
        return _error(
            what=f"{tool}: override requires override_rationale",
            why=(
                "an un-rationaled bypass would log rationale=None and slip past "
                "the pre-submission audit"
            ),
            next_action=(
                empty_msg
                or 'pass override_rationale="..." (>=20 chars, multi-word, substantive)'
            ),
        )
    if requested and rationale:
        thin = validate_override_rationale(rationale)
        if thin is not None:
            return thin
    if requested and blocked:
        log_override(root, tool=tool, gate=gate, rationale=rationale, extra=extra)
    return None
