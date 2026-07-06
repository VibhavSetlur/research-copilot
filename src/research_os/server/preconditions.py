"""Precondition verifier — protocols declare what must be true, this checks it.

docs/PRECONDITION_GATE.md. A protocol's `prerequisites:` block is prose
the AI is trusted to honour. The optional `requires.checks` block holds the
MECHANICALLY checkable subset, compiled into
`protocols/_precondition_meta.json`; this module evaluates those checks
against a workspace so "you must have done X first" becomes a checked fact.

Seam: reasoning side (`server/`), reads workspace files BY SHAPE, never
imports `research_os.daemon` (nor the daemon-coupled protocol loader). Pure
stdlib, fail-safe: an unreadable sidecar/workspace → "no claim" (empty
list), so a project without compiled preconditions behaves exactly as
today.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_PROTOCOL_LOG = "protocol_execution_log.jsonl"


def _load_meta(path: Path | None = None) -> dict[str, list[dict]]:
    """Load protocol_id -> [checks] from ``_protocols.bundle``. Fail-safe to {}.

    P1: preconditions are compiled into the single bundle and served by
    ProtocolRegistry.get_preconditions(). The ``path`` arg is accepted for
    back-compat but ignored.
    """
    try:
        from research_os.tools.actions.protocol import ProtocolRegistry

        protos = ProtocolRegistry.get_preconditions()
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(protos, dict):
        return {}
    out: dict[str, list[dict]] = {}
    for pid, checks in protos.items():
        if isinstance(checks, list):
            out[str(pid)] = [c for c in checks if isinstance(c, dict)]
    return out


# ── individual check evaluators (each returns True when SATISFIED) ─────────

def _check_file_exists(root: Path, check: dict) -> bool:
    rel = str(check.get("path") or "")
    if not rel:
        return False
    target = root / rel
    if not target.exists() or not target.is_file():
        return False
    if check.get("non_empty"):
        try:
            return target.stat().st_size > 0
        except OSError:
            return False
    return True


def _check_glob_min(root: Path, check: dict) -> bool:
    pattern = str(check.get("pattern") or "")
    if not pattern:
        return False
    try:
        minimum = int(check.get("min", 1))
    except (TypeError, ValueError):
        minimum = 1
    try:
        matches = [p for p in root.glob(pattern) if p.is_file()]
    except (OSError, ValueError):
        return False
    return len(matches) >= minimum


def _check_protocol_completed(root: Path, check: dict) -> bool:
    name = str(check.get("protocol") or "")
    if not name:
        return False
    log = root / ".os_state" / _PROTOCOL_LOG
    try:
        if not log.exists():
            return False
        for line in log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if (entry.get("protocol") == name
                    and entry.get("status") == "completed"):
                return True
    except OSError:
        return False
    return False


def _check_state_field(root: Path, check: dict) -> bool:
    field = str(check.get("field") or "")
    if not field:
        return False
    ledger = root / ".os_state" / "state_ledger.json"
    try:
        if not ledger.exists():
            return False
        data = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    value = data.get(field)
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


_CHECKERS = {
    "file_exists": _check_file_exists,
    "glob_min": _check_glob_min,
    "protocol_completed": _check_protocol_completed,
    "state_field": _check_state_field,
}


def unmet_preconditions(
    protocol_id: str,
    root: Path,
    *,
    meta: dict[str, list[dict]] | None = None,
) -> list[dict[str, Any]]:
    """Return the list of UNMET precondition checks for a protocol.

    Each item: ``{kind, because, detail}`` describing what is missing and
    why it matters, so the AI's next action is obvious. Empty list = all
    declared mechanical preconditions are satisfied (or none are declared).

    Fail-safe: an UNKNOWN check kind is treated as SATISFIED (not blocked) —
    we never invent a block from a check the verifier can't evaluate, same
    posture as the gate predicate evaluator. A genuinely missing foundation
    is only ever reported for a kind we positively evaluated to False.
    """
    pool = meta if meta is not None else _load_meta()
    checks = pool.get(protocol_id)
    if checks is None:
        # Resolve a bare leaf ("analysis_plan") against path-keyed meta
        # ("guidance/analysis_plan"), so either form the caller passes works.
        for key, val in pool.items():
            if key.rsplit("/", 1)[-1] == protocol_id:
                checks = val
                break
    checks = checks or []
    root = Path(root)
    unmet: list[dict[str, Any]] = []
    for check in checks:
        kind = str(check.get("kind") or "")
        checker = _CHECKERS.get(kind)
        if checker is None:
            continue  # unknown kind → don't block (fail-safe)
        try:
            satisfied = checker(root, check)
        except Exception:  # noqa: BLE001 - a check must never raise into the gate
            satisfied = True  # ambiguous → don't block
        if not satisfied:
            unmet.append({
                "kind": kind,
                "because": str(check.get("because") or ""),
                "detail": _describe(check),
            })
    return unmet


def preconditions_met(protocol_id: str, root: Path) -> bool:
    """True iff every declared mechanical precondition is satisfied."""
    return not unmet_preconditions(protocol_id, root)


def _describe(check: dict) -> str:
    """One-line, human-readable description of what a check wanted."""
    kind = check.get("kind")
    if kind == "file_exists":
        ne = " (non-empty)" if check.get("non_empty") else ""
        return f"file {check.get('path')!r} must exist{ne}"
    if kind == "glob_min":
        return f"at least {check.get('min', 1)} file(s) matching {check.get('pattern')!r}"
    if kind == "protocol_completed":
        return f"protocol {check.get('protocol')!r} must be completed first"
    if kind == "state_field":
        return f"state field {check.get('field')!r} must be set"
    return str(kind)
