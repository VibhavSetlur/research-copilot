"""Server-side enforcement of autopilot / adaptive floor gates.

The ``guidance/autopilot.yaml`` protocol lists the mandatory
confirmation gates that must stop and ask the researcher before they
execute, even when the AI is otherwise hands-off. Before this module,
those gates were prose only — an AI could legally skip them. Now the
dispatcher refuses the call unless ``arguments['confirmed'] == True``.

The gates intercepted here:

  1. ``tool_typst_compile`` (final-deliverable PDF compile)
  2. ``tool_audit(scope='step', dimension='reproducibility')``
  3. ``tool_research_tool`` (paid candidates)
  4. ``sys_path(operation='abandon')`` — irreversible-ish path closure
  5. ``sys_file_write`` targeting ``synthesis/`` with ``force=true``
  6. ``tool_package_install``
  7. ``sys_checkpoint_rollback``
  8. ``tool_task(operation='run')`` — long-running background jobs

Two autonomy levels engage these gates:

  * ``autopilot`` — STATIC. All 8 gates always fire. The opt-in "be
    hands-off but stop on the big stuff" posture.
  * ``adaptive`` — DEFAULT, and the point of v3.3: the researcher never
    picks a mode. The gate SET flexes with the project's resolved
    ``gate_strictness`` (which is itself trust-score driven via
    ``rigor_signals.resolve_gate_strictness``):

        strict  → all 8 gates fire (same as autopilot). Low-trust /
                  young / messy projects get full protection.
        normal  → the irreversible + real-cost gates fire; reversible
                  ones (synthesis force-overwrite — auto-archived; long
                  background tasks — killable) flow.
        light   → only the genuinely irreversible / real-money gates
                  fire (path abandon, package install, paid tools,
                  rollback). A rigorous project earns flow.

``supervised`` / ``manual`` / ``coaching`` are untouched (their flows
already include an explicit ask elsewhere).
"""
from __future__ import annotations

import logging
from pathlib import Path

from .errors import RoError

logger = logging.getLogger("research-os.server.autopilot_gate")


def _read_autonomy_level(root: Path) -> str:
    """Return the normalized autonomy level for this project.

    Fail-SAFE, not fail-open:
      * No config file at all  → 'supervised' (a project without a config has
        opted into nothing; the gate stays out of the way).
      * Config file EXISTS but is unreadable/corrupt → 'adaptive' (the protective
        default). Returning 'supervised' here was a fail-OPEN bug: a corrupt
        researcher_config.yaml silently stripped every floor gate
        (package_install / rollback / paid / abandon). 'adaptive' pairs with
        _resolved_strictness, which already fails to 'strict' on error, so a
        corrupt config now means all gates fire, not none.
    """
    from research_os.tools.actions.state.config import (
        _config_path,
        normalize_autonomy_level,
    )
    import yaml as _yaml

    try:
        cfg_path = _config_path(Path(root))
    except Exception:
        return "supervised"
    if not cfg_path.exists():
        return "supervised"
    try:
        cfg = _yaml.safe_load(cfg_path.read_text()) or {}
        raw = (cfg.get("interaction") or {}).get("autonomy_level")
        # No explicit level set → the v3.3 default is adaptive.
        return normalize_autonomy_level(raw, default="adaptive")
    except Exception:
        # The file is present but broken — do NOT drop to 'supervised' (that
        # disables the floor gates). Fail to the protective default.
        logger.warning(
            "researcher_config.yaml present but unreadable at %s — "
            "failing autonomy_level to 'adaptive' so floor gates still apply",
            root,
        )
        return "adaptive"


def _resolved_strictness(root: Path) -> str:
    """Resolve the project's gate_strictness (light|normal|strict).

    Defaults to 'strict' on any error so adaptive mode fails SAFE — an
    unreadable project keeps every floor gate active.
    """
    try:
        from research_os.tools.actions.state.rigor_signals import (
            resolve_gate_strictness,
        )

        res = resolve_gate_strictness(Path(root))
        val = res.get("resolved")
        return val if val in {"light", "normal", "strict"} else "strict"
    except Exception:
        return "strict"


# Tools that ALWAYS require confirmation in autopilot mode, regardless
# of arguments. LEGACY fail-safe table — used only when the compiled
# _gate_meta.json sidecar is missing/garbage (see gate_spec). The live
# source of truth is guidance/autopilot.yaml's `enforcement.gates`, which
# compiles into the sidecar and is what _requires_confirmation /
# _gate_key / _GATE_FLOOR consult first.
_ALWAYS_GATED: set[str] = {
    "tool_package_install",
    "sys_checkpoint_rollback",
}

# Adaptive-mode gate tiers. A gate fires in adaptive mode when the
# project's resolved strictness is at or above the gate's floor. Lower
# index = looser. ``light`` keeps only the truly irreversible / real-money
# gates; ``normal`` adds the reversible-but-weighty ones; ``strict`` is the
# full autopilot set. The key → floor map is served by
# gate_spec.declared_floor_map() from the compiled _protocols.bundle (P1) —
# the bundle always ships in the package, so no hand-maintained fallback
# table is needed.
_STRICTNESS_RANK = {"light": 0, "normal": 1, "strict": 2}


def _declared_gates() -> list:
    """Load the compiled declared gates (cached in gate_spec). May be []."""
    from .gate_spec import _load_gate_meta

    return _load_gate_meta()


def _GATE_FLOOR_resolved() -> dict[str, str]:
    """key → floor from the compiled _protocols.bundle (P1).

    The bundle always ships in the package; a garbage bundle yields an
    empty map (gate_spec fails safe to []), which just means adaptive-mode
    floor filtering has nothing to relax — every resolved gate still fires.
    """
    from .gate_spec import declared_floor_map

    return declared_floor_map(_declared_gates())


# Back-compat module attribute: some callers/tests read _GATE_FLOOR
# directly. Resolve it once at import from the compiled bundle. This is a
# snapshot; the live decision path uses _GATE_FLOOR_resolved() so a rebuilt
# bundle is picked up on reload.
_GATE_FLOOR: dict[str, str] = _GATE_FLOOR_resolved()


def _gate_key(tool_name: str, arguments: dict) -> str | None:
    """Return the canonical gate key for this (tool, args) combo, or None.

    The key is what the adaptive-floor logic is indexed by. Resolves from
    the compiled declared gates (the live source of truth); if the sidecar
    is empty, falls back to the legacy hand-coded matcher so the floor is
    never lost.
    """
    from .gate_spec import resolve_declared_gate

    gates = _declared_gates()
    if gates:
        g = resolve_declared_gate(tool_name, arguments or {}, None, gates=gates)
        return g["key"] if g else None
    return _legacy_gate_key(tool_name, arguments)


def _legacy_gate_key(tool_name: str, arguments: dict) -> str | None:
    """Fail-safe hand-coded gate-key matcher (sidecar-absent fallback)."""
    args = arguments or {}
    if tool_name == "tool_package_install":
        return "tool_package_install"
    if tool_name == "sys_checkpoint_rollback":
        return "sys_checkpoint_rollback"
    if tool_name == "sys_path":
        return "sys_path:abandon" if (args.get("operation") or "") == "abandon" else None
    if tool_name == "tool_research_tool":
        source = str(args.get("source") or "").lower()
        if source in {"paid", "paid_or_licensed"} or args.get("paid") is True:
            return "tool_research_tool:paid"
        return None
    if tool_name == "tool_typst_compile":
        return "tool_typst_compile"
    if tool_name == "tool_audit":
        scope = str(args.get("scope") or "")
        dimension = str(args.get("dimension") or "")
        if scope == "step" and dimension == "reproducibility":
            return "tool_audit:reproducibility"
        return None
    if tool_name == "tool_task":
        return "tool_task:run" if (args.get("operation") or "") == "run" else None
    if tool_name == "sys_file_write":
        return "sys_file_write:synthesis_force" if _is_synthesis_force_write(
            args, None
        ) else None
    return None


def _is_synthesis_force_write(args: dict, root: Path | None) -> bool:
    """True when this sys_file_write force-OVERWRITES an existing synthesis/ file.

    A force-write to a path that does not exist yet destroys nothing, so
    it is not a floor gate — only an actual overwrite of existing
    synthesis content is irreversible-ish (and even then auto-archived).
    """
    filepath = str(args.get("filepath") or "")
    force = bool(args.get("force"))
    if not force:
        return False
    if root is not None:
        try:
            root_r = Path(root).resolve()
            target = Path(filepath)
            cand = target if target.is_absolute() else (root_r / target)
            cand_r = cand.resolve()
            rel = cand_r.relative_to(root_r).as_posix()
        except (ValueError, OSError):
            return True  # fail-safe: any resolution error → gate
        if not rel.startswith("synthesis/"):
            return False
        # Only gate when we are actually clobbering existing content.
        return cand_r.exists()
    # No root to check existence against → fall back to path-shape only.
    norm = filepath
    for prefix in ("./", "/"):
        while norm.startswith(prefix):
            norm = norm[len(prefix):]
    return norm.startswith("synthesis/")


def _requires_confirmation(tool_name: str, arguments: dict,
                           root: Path | None = None) -> bool:
    """Decide whether this (tool_name, arguments) combo is a floor gate.

    Resolves from the compiled declared gates (the live source of truth in
    guidance/autopilot.yaml's enforcement block, evaluated with ``root`` so
    the synthesis-force existence check works). Falls back to the legacy
    hand-coded matcher only when the compiled sidecar is absent, so the
    floor is never lost.
    """
    from .gate_spec import resolve_declared_gate

    gates = _declared_gates()
    if gates:
        return resolve_declared_gate(tool_name, arguments or {}, root, gates=gates) is not None
    return _legacy_requires_confirmation(tool_name, arguments, root)


def _legacy_requires_confirmation(tool_name: str, arguments: dict,
                                  root: Path | None = None) -> bool:
    """Fail-safe hand-coded gate matcher (sidecar-absent fallback).

    Returns ``True`` only for the combinations enumerated in
    ``guidance/autopilot.yaml`` step ``mandatory_gates``. (autopilot-static
    set — adaptive mode further filters this by strictness.)
    """
    if tool_name in _ALWAYS_GATED:
        return True
    args = arguments or {}
    if tool_name == "sys_file_write":
        return _is_synthesis_force_write(args, root)
    if tool_name == "sys_path":
        return (args.get("operation") or "") == "abandon"
    if tool_name == "tool_task":
        # Expensive jobs: heuristic on the run operation. The protocol
        # spec says "> 1 GPU-hour OR > 10 GB memory OR > 50 GB disk I/O".
        # Without a cost estimator, treat every operation='run' as a
        # floor gate in autopilot — the researcher said "wake me on
        # background tasks", and they can confirm with one flag.
        return (args.get("operation") or "") == "run"
    if tool_name == "tool_research_tool":
        # Paid-source picks need explicit confirmation. The autopilot
        # protocol scopes this to candidates tagged paid_or_licensed —
        # callers signal that via source='paid' or paid=True.
        source = str(args.get("source") or "").lower()
        if source in {"paid", "paid_or_licensed"}:
            return True
        if args.get("paid") is True:
            return True
        return False
    if tool_name == "tool_typst_compile":
        # Final-deliverable PDF compile — gate every call.
        return True
    if tool_name == "tool_audit":
        # Reproducibility audits are slow + expensive.
        scope = str(args.get("scope") or "")
        dimension = str(args.get("dimension") or "")
        return scope == "step" and dimension == "reproducibility"
    return False


def _gate_block_reason(
    tool_name: str, args: dict, gate_key: str | None, root: Path
) -> str:
    """Human-readable reason a floor gate fired, for the away-user page.

    Prefers the SPECIFIC world-state risk (stale inputs / missing
    preconditions) over a generic 'floor gate' note, so the researcher's
    notification names the real hazard. Best-effort + fail-safe: any error
    yields an empty string (the page still fires with its generic body).
    """
    try:
        key = gate_key or ""
        if key.endswith(":stale_inputs"):
            return (
                "the final deliverable would be built from inputs that have "
                "since changed (stale results)"
            )
        if "precondition" in key:
            return "a required foundation for this step is not yet in place"
        from .gate_spec import resolve_declared_gate

        gates = _declared_gates()
        if gates:
            g = resolve_declared_gate(tool_name, args or {}, root, gates=gates)
            if g and g.get("reason"):
                return str(g["reason"])
    except Exception:  # noqa: BLE001 - reason is cosmetic; never break paging
        return ""
    return ""


def enforce_autopilot_gate(
    tool_name: str, arguments: dict, root: Path
) -> None:
    """Raise ``RoError`` if this call hits a floor gate without consent.

    No-op when:
      * autonomy is not gate-active (not 'autopilot' / 'adaptive')
      * tool is not in the gated set for these arguments
      * autonomy is 'adaptive' AND the project's strictness is below the
        gate's floor (a rigorous project flows through reversible gates)
      * consent is satisfied (see below)

    Consent has TWO modes:

      * NO daemon running (stdio-only, the default for most users) →
        DEGRADE to the historical behaviour: the agent's own
        ``confirmed=true`` clears the gate. Nothing is hardened, nothing
        is broken.
      * A daemon IS running for this project → it is the consent
        AUTHORITY. The agent's ``confirmed=true`` no longer suffices; the
        call must carry a ``consent_token`` the daemon minted for THIS
        exact (gate_key, argument-fingerprint). This is the un-skippable
        layer: the agent cannot grade its own homework when a daemon is
        watching.

    The error includes the exact next-action the AI must take — either
    self-confirm (no daemon) or request consent from the daemon.
    """
    if not _requires_confirmation(tool_name, arguments, root):
        return
    level = _read_autonomy_level(root)
    if level not in {"autopilot", "adaptive"}:
        return

    args = arguments or {}

    # Adaptive mode: only fire when the project's resolved strictness
    # clears this gate's floor. autopilot is always full-strictness.
    gate_key = _gate_key(tool_name, args)
    if level == "adaptive" and gate_key is not None:
        floor = _GATE_FLOOR.get(gate_key, "strict")
        strictness = _resolved_strictness(root)
        if _STRICTNESS_RANK[strictness] < _STRICTNESS_RANK[floor]:
            logger.debug(
                "adaptive gate %s skipped: strictness=%s < floor=%s",
                gate_key, strictness, floor,
            )
            return

    # The gate is active for this call. Decide whether consent is satisfied.
    from .consent import (
        arg_fingerprint,
        consume_grant,
        daemon_present,
        find_valid_grant,
    )

    if daemon_present(Path(root)):
        # HARD mode: the daemon is the consent authority. A token the
        # daemon minted for this exact action is required; the agent's
        # self-asserted confirmed=true is intentionally NOT honored.
        token = args.get("consent_token")
        fp = arg_fingerprint(tool_name, args)
        key = gate_key or tool_name

        grant = find_valid_grant(Path(root), key, fp, token)
        if grant is not None:
            # Burn the token before returning so a single authorization
            # clears exactly ONE action — the agent cannot replay one
            # human approval across many gated calls. Pass the grant's
            # expires_at so the spent log can prune the token once it is
            # long dead (otherwise the log grows unbounded on a long-lived
            # project).
            consume_grant(Path(root), token, expires_at=grant.get("expires_at"))
            return
        # BLOCKED while unattended: a daemon is the authority and the human
        # is away. Page them on the daemon's notification spine so they learn
        # action is needed — a wedged/looping/crashed agent would otherwise
        # leave the floor gate silently stuck. Best-effort + de-duplicated;
        # never alters the gate decision below.
        try:
            from .notify_sink import notify_gate_blocked

            notify_gate_blocked(
                Path(root),
                tool=tool_name,
                gate_key=key,
                arg_fingerprint=fp,
                reason=_gate_block_reason(tool_name, args, key, Path(root)),
            )
        except Exception:  # noqa: BLE001 - paging must never break the gate
            logger.debug("gate-block notification failed", exc_info=True)
        raise RoError(
            what="consent_required",
            why=(
                f"a daemon is enforcing floor gates for this project, so "
                f"{tool_name} needs a daemon-minted consent token bound to "
                "this exact action — the agent's own confirmed=true is not "
                "sufficient while a daemon is present"
            ),
            next_action=(
                f"call sys_consent(action='request', gate_key='{key}', "
                f"arg_fingerprint='{fp}', tool='{tool_name}', reason='<why>') "
                "to queue a consent request for the researcher; once they "
                f"approve (CLI: research-os daemon consent approve, or any "
                "authorized client), call sys_consent(action='token', "
                f"gate_key='{key}', arg_fingerprint='{fp}') to fetch the "
                f"minted token, then retry {tool_name}(consent_token='<minted>', "
                "...). Only request if the researcher authorized this action"
            ),
        )

    # DEGRADE mode: no daemon → historical behaviour, agent self-confirm
    # clears the gate so stdio-only users are unaffected.
    if args.get("confirmed") is True:
        return

    posture = (
        "adaptive autonomy paused here: this action is irreversible / "
        "expensive / external-cost at the project's current rigor level"
        if level == "adaptive"
        else "autopilot autonomy requires explicit confirmation"
    )
    raise RoError(
        what="autopilot_gate_blocked",
        why=(
            f"{posture} for {tool_name} — this is one of the mandatory "
            "floor gates declared in guidance/autopilot.yaml and enforced "
            "server-side"
        ),
        next_action=(
            f"researcher must confirm — call {tool_name}(confirmed=true, ...) "
            "only if researcher authorized"
        ),
    )
