"""Declared-gate spec: protocols author hard gates, the engine enforces.

This is the HYBRID layer (docs/HYBRID_ARCHITECTURE.md). Floor gates —
the actions that MUST stop and ask even in hands-off mode — used to live
twice: as prose in ``guidance/autopilot.yaml`` and as hand-maintained
Python in ``autopilot_gate.py``. Two sources of truth drift. Now a
protocol DECLARES its gates in a machine-readable ``enforcement.gates``
block, a build step compiles every protocol's block into one sidecar
(``protocols/_gate_meta.json``), and this module reads that sidecar and
evaluates a gate's arg-match predicate.

Seam (ARCHITECTURE #1, preflight-enforced): this module lives on the
reasoning side (``server/``) and MUST NOT import ``research_os.daemon``.
It only reads the compiled sidecar shipped in the package. The daemon's
role (UNSKIPPABLE_GATES.md) is orthogonal: it makes a fired gate
un-skippable by minting consent; THIS module decides which gates fire.

Fail-safe: every loader path falls back to ``[]`` (and the caller keeps
its built-in legacy tables) so a missing/garbage sidecar never drops a
floor — the engine keeps enforcing, it just can't be EXTENDED by a
protocol until the sidecar is rebuilt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _load_gate_meta(path: Path | None = None) -> list[dict[str, Any]]:
    """Read the declared gate list from ``_protocols.bundle``. Fail SAFE to [].

    P1: gates are compiled into the single bundle and served by
    ProtocolRegistry.get_gates(). An unreadable/empty bundle yields an
    empty list; the caller then relies on its built-in legacy tables so
    the floor never silently drops. The ``path`` arg is accepted for
    back-compat but ignored (the bundle is the sole source).
    """
    try:
        from research_os.tools.actions.protocol import ProtocolRegistry

        gates = ProtocolRegistry.get_gates()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(gates, list):
        return []
    out: list[dict[str, Any]] = []
    for g in gates:
        if not isinstance(g, dict):
            continue
        key = g.get("key")
        tool = g.get("tool")
        floor = g.get("floor")
        when = g.get("when")
        if not isinstance(key, str) or not key:
            continue
        if not isinstance(tool, str) or not tool:
            continue
        if floor not in {"light", "normal", "strict"}:
            continue
        if not isinstance(when, dict):
            continue
        out.append(
            {
                "key": key,
                "tool": tool,
                "floor": floor,
                "when": when,
                "reason": g.get("reason") or "",
                "source_protocol": g.get("source_protocol") or "",
            }
        )
    return out


def _match_predicate(
    when: dict[str, Any], args: dict[str, Any], root: Path | None
) -> bool:
    """Evaluate a gate's ``when`` predicate against a tool call's args.

    The predicate vocabulary is deliberately tiny — it is a DECLARATION
    of which arg combos are dangerous, not a general expression language.
    ALL clauses must hold (logical AND). An empty ``when`` ({}) always
    matches (the tool is a gate regardless of arguments).

    Supported clause forms (value side):
      * scalar           → str(args.get(k)) == str(value)
      * list             → str(args.get(k)) in {str(v) for v in value}
      * {"truthy": true} → bool(args.get(k)) is True
      * {"path_prefix": P, "exists": E, "when_arg": A}
            → the synthesis-force-write special case. Fires when:
              args[A] is truthy AND the target path (args['filepath'])
              resolves under prefix P AND (if E is true and root given)
              the target already exists. Mirrors the legacy
              _is_synthesis_force_write logic exactly.
      * {"any_of": [<sub-predicate>, ...]} → OR: the clause holds if any
            sub-predicate matches. Used for one dangerous action that has
            two distinct argument signatures (e.g. paid tool via
            source='paid' OR paid=true).
      * {"world_state": "<kind>"} → fires based on DETECTED world state
            (not the call's args). ``no_stale_inputs`` fires when a daemon
            has currently determined the project has stale inputs (read via
            server.staleness_state, no daemon import). Lets a gate ask "is
            the world safe for this action?", not only "is this action
            dangerous?".

    Any unrecognised clause shape fails CLOSED for THIS clause (returns
    False → the gate does not fire on a predicate the engine can't read),
    which is the safe default: we never invent a gate from a malformed
    rule, and the legacy tables remain the backstop for known gates.
    """
    args = args or {}
    if not when:
        return True
    for k, expected in when.items():
        if k == "world_state":
            # World-state predicate: the gate fires based on DETECTED state
            # (not the call's args). Two forms:
            #   world_state: no_stale_inputs            (scalar kind)
            #   world_state: {kind: preconditions_met,  (parameterised)
            #                 protocol: guidance/analysis_plan}
            # Needs root to read the verdict/checks; with no root, no claim.
            if isinstance(expected, dict):
                kind = str(expected.get("kind") or "")
                if not _match_world_state(kind, root, params=expected):
                    return False
            elif not _match_world_state(str(expected), root):
                return False
            continue
        if k == "any_of":
            # ``any_of`` is a list of sub-predicates; the clause holds if
            # ANY sub-predicate matches (logical OR). Lets a single gate
            # express "source in {paid,...} OR paid==true" without needing
            # two gate keys for one dangerous action.
            if not isinstance(expected, list):
                return False
            if not any(
                isinstance(sub, dict) and _match_predicate(sub, args, root)
                for sub in expected
            ):
                return False
            continue
        if isinstance(expected, dict):
            if "path_prefix" in expected:
                if not _match_path_clause(expected, args, root):
                    return False
                continue
            if expected.get("truthy") is True:
                if args.get(k) is not True and not bool(args.get(k)):
                    return False
                continue
            # Unknown dict clause → fail closed for this clause.
            return False
        if isinstance(expected, list):
            # Case-insensitive membership: the legacy gate path lowercased before
            # comparing, so source="PAID" must fire the paid-tool gate exactly
            # like "paid" (a case-variant must NOT bypass a money/safety gate).
            allowed = {str(v).strip().lower() for v in expected}
            actual = str(args.get(k) if args.get(k) is not None else "").strip().lower()
            if actual not in allowed:
                return False
            continue
        # Scalar equality — case-insensitive, matching the legacy checks which
        # lowercased before comparing.
        actual = str(args.get(k) if args.get(k) is not None else "").strip().lower()
        if actual != str(expected).strip().lower():
            return False
    return True


def _match_path_clause(
    clause: dict[str, Any], args: dict[str, Any], root: Path | None
) -> bool:
    """The synthesis-force-write predicate (needs args + optional root).

    Fires when the gating arg is truthy AND the target path is under the
    declared prefix AND (when ``exists`` is set and a root is available)
    the file actually exists — a force-write to a non-existent path
    destroys nothing, so it is not a floor gate. With no root, fall back
    to path-shape only (fail toward gating on any resolution error).
    """
    when_arg = clause.get("when_arg")
    prefix = str(clause.get("path_prefix") or "")
    needs_exists = bool(clause.get("exists"))

    if when_arg is not None and not bool(args.get(when_arg)):
        return False

    filepath = str(args.get("filepath") or "")
    if root is not None:
        try:
            root_r = Path(root).resolve()
            target = Path(filepath)
            cand = target if target.is_absolute() else (root_r / target)
            cand_r = cand.resolve()
            rel = cand_r.relative_to(root_r).as_posix()
        except (ValueError, OSError):
            return True  # fail-safe: any resolution error → gate
        if not rel.startswith(prefix):
            return False
        if needs_exists:
            return cand_r.exists()
        return True
    # No root: path-shape only (cannot check existence).
    norm = filepath
    for p in ("./", "/"):
        while norm.startswith(p):
            norm = norm[len(p):]
    return norm.startswith(prefix)


def _match_world_state(
    kind: str, root: Path | None, params: dict[str, Any] | None = None
) -> bool:
    """Evaluate a world-state predicate. True = the gate should fire.

    Kinds:
      * ``no_stale_inputs`` — fires when a daemon has CURRENTLY determined
        the project has stale inputs (verdict sidecar, via
        server.staleness_state).
      * ``preconditions_met`` — fires when a named protocol's declared
        mechanical preconditions are NOT all satisfied (via
        server.preconditions). The protocol is named in ``params['protocol']``.
        "fires" = the gate blocks because a foundation is missing.

    All read by shape (no daemon import). With no root, or no positive
    claim, returns False (gate does not fire) — fail toward NOT blocking,
    per the design's deliberate direction. An unknown kind fails CLOSED
    (returns False): we never invent a gate from a predicate we can't read.
    """
    if root is None:
        return False
    if kind == "no_stale_inputs":
        from .staleness_state import is_currently_stale

        return is_currently_stale(Path(root))
    if kind == "preconditions_met":
        protocol = str((params or {}).get("protocol") or "")
        if not protocol:
            return False
        from .preconditions import unmet_preconditions

        # The gate FIRES when preconditions are NOT met (foundation missing).
        return bool(unmet_preconditions(protocol, Path(root)))
    return False


def resolve_declared_gate(
    tool_name: str,
    args: dict[str, Any],
    root: Path | None = None,
    *,
    gates: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Return the declared gate matching this call, or None.

    A tool may have MORE than one declared gate (e.g. tool_typst_compile has
    an unconditional "is this shareable?" gate AND a conditional "are inputs
    stale?" gate). When several match, the MOST SPECIFIC wins: a gate with a
    non-empty ``when`` predicate is preferred over an unconditional
    (``when: {}``) gate, so the firing reason the AI/human sees reflects the
    real, specific risk (stale inputs) rather than the generic one. Among
    gates of equal specificity, declaration order (sorted by key in the
    compiled sidecar) is the tiebreak.

    Returns the gate dict (carrying ``key`` and ``floor``) so the caller can
    apply adaptive-floor logic. None when no declared gate matches (the
    caller then consults its legacy tables for fail-safe coverage).
    """
    pool = gates if gates is not None else _load_gate_meta()
    specific_match: dict[str, Any] | None = None
    unconditional_match: dict[str, Any] | None = None
    for g in pool:
        if g["tool"] != tool_name:
            continue
        if not _match_predicate(g["when"], args, root):
            continue
        if g["when"]:
            # First specific (conditional) match wins outright.
            specific_match = g
            break
        if unconditional_match is None:
            unconditional_match = g
    return specific_match or unconditional_match


def declared_floor_map(
    gates: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """key → floor for every declared gate (mirrors legacy _GATE_FLOOR)."""
    pool = gates if gates is not None else _load_gate_meta()
    return {g["key"]: g["floor"] for g in pool}
