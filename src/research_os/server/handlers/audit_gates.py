"""Handlers — audit_gates sub-domain.

Carved out of handlers/audit.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

# ruff: noqa: F403, F405  # legacy handler runtime star-import compatibility
from .._handlers_runtime import *  # noqa: F401,F403

__all__ = [
    "_handle_tool_state_freshness_check",
    "_handle_tool_intake_freshness",
    "_handle_tool_rigor_signals_scan",
    "_handle_tool_resolve_gate_strictness",
    "_handle_tool_self_certify",
    "_handle_tool_list_certifications",
    "_handle_tool_quick_route",
    "_handle_tool_promote_to_step",
    "_handle_tool_project_tier_strictness",
    "_handle_tool_dry_run",
    "_handle_tool_step_complete",
    "_handle_tool_finalize_project",
]

def _handle_tool_state_freshness_check(name, arguments, root):
    from research_os.tools.actions.state.freshness import state_freshness_check
    days = arguments.get("stale_after_days")
    kwargs = {}
    if isinstance(days, (int, float)) and days > 0:
        kwargs["stale_after_days"] = int(days)
    return _text(state_freshness_check(root, **kwargs))


def _handle_tool_intake_freshness(name, arguments, root):
    from research_os.tools.actions.data.intake_freshness import intake_freshness
    days = arguments.get("fresh_window_days")
    kwargs = {}
    if isinstance(days, (int, float)) and days > 0:
        kwargs["fresh_window_days"] = int(days)
    return _text(intake_freshness(root, **kwargs))


def _handle_tool_rigor_signals_scan(name, arguments, root):
    from research_os.tools.actions.state.rigor_signals import rigor_signals_scan
    return _text(rigor_signals_scan(root))


def _handle_tool_resolve_gate_strictness(name, arguments, root):
    from research_os.tools.actions.state.rigor_signals import resolve_gate_strictness
    # Action returns a bare {resolved, source, trust_score} dict (no status) —
    # wrap so the envelope is conformant.
    return _text(_success(resolve_gate_strictness(root)))


def _handle_tool_self_certify(name, arguments, root):
    from research_os.tools.actions.state.certifications import self_certify
    return _text(self_certify(
        root,
        domain=str(arguments.get("domain", "")),
        scope=str(arguments.get("scope", "")),
        rationale=str(arguments.get("rationale", "")),
    ))


def _handle_tool_list_certifications(name, arguments, root):
    from research_os.tools.actions.state.certifications import list_certifications
    return _text(list_certifications(root))


def _handle_tool_quick_route(name, arguments, root):
    from research_os.tools.actions.state.quick_mode import quick_route
    # Action returns a bare {is_quick, ...} dict (no status) — wrap it.
    return _text(_success(quick_route(root, str(arguments.get("prompt", "")))))


def _handle_tool_promote_to_step(name, arguments, root):
    from research_os.tools.actions.state.quick_mode import promote_to_step
    return _text(promote_to_step(
        root,
        scratch_path=str(arguments.get("scratch_path", "")),
        step_slug=str(arguments.get("step_slug", "")),
        rationale=str(arguments.get("rationale", "")),
    ))


def _handle_tool_project_tier_strictness(name, arguments, root):
    from research_os.tools.actions.state.quick_mode import project_tier_strictness
    return _text(project_tier_strictness(root))


# Lean variants / dry-run / bundling / coaching handlers (Themes 2/13/15/7).


def _handle_tool_dry_run(name, arguments, root):
    from research_os.tools.actions.protocol import load_protocol
    pname = arguments.get("protocol_name") or ""
    if not pname:
        return _text(_error("protocol_name is required"))
    try:
        out = load_protocol(pname, format="dryrun")
        out["simulated_args"] = arguments.get("simulated_args") or {}
        return _text(_success(out))
    except (FileNotFoundError, ValueError) as e:
        return _text(_error(str(e)))


def _handle_tool_step_complete(name, arguments, root):
    step_id = arguments.get("step_id") or ""
    if not step_id:
        return _text({"status": "error", "message": "step_id is required"})
    override_lit = bool(arguments.get("override_literature_gate"))
    rationale = arguments.get("override_rationale") or ""

    from research_os.tools.actions.audit.audit import audit_step_completeness
    from research_os.tools.actions.audit.step_literature import audit_step_literature
    from research_os.tools.actions.state.path import finalize_path
    from research_os.tools.actions.state.revision import step_revision_options
    from research_os.project_ops import validate_override_rationale

    # reject thin override_rationale ('TODO', 'preview',
    # single-word, <20 chars) BEFORE any audit work runs.
    # Also reject empty rationale paired with override flag (silently
    # skipping the override would surprise the caller).
    if override_lit:
        if not rationale:
            return _text(_error(
                what="override_literature_gate=true requires override_rationale",
                why="empty rationale would silently no-op the override",
                next_action="pass override_rationale=\"...\" with substantive text (>=20 chars, multi-word)",
            ))
        thin = validate_override_rationale(rationale)
        if thin is not None:
            return _text(thin)

    merged = {"step_id": step_id, "stages": {}}
    statuses: list[str] = []
    try:
        merged["stages"]["finalize"] = finalize_path(step_id, root)
        statuses.append(merged["stages"]["finalize"].get("status", "success"))
    except Exception as e:
        merged["stages"]["finalize"] = {"status": "error", "message": str(e)}
        statuses.append("error")
    try:
        merged["stages"]["completeness"] = audit_step_completeness(root, step_id=step_id)
        statuses.append(merged["stages"]["completeness"].get("status", "success"))
    except Exception as e:
        merged["stages"]["completeness"] = {"status": "error", "message": str(e)}
        statuses.append("error")
    try:
        lit = audit_step_literature(root, step_id=step_id)
        if override_lit and rationale:
            lit["overridden"] = True
            lit["override_rationale"] = rationale
            if lit.get("status") == "error":
                lit["status"] = "warning"
            # Journal the bypass so the pre-submission audit sees it (this was
            # previously applied to the stage dict but never logged).
            from research_os.project_ops import log_override
            log_override(
                root, tool="tool_step_complete", gate="step_literature",
                rationale=rationale, extra={"step_id": step_id},
            )
        merged["stages"]["literature"] = lit
        statuses.append(lit.get("status", "success"))
    except Exception as e:
        merged["stages"]["literature"] = {"status": "error", "message": str(e)}
        statuses.append("error")
    try:
        merged["stages"]["revision"] = step_revision_options(step_id, root)
        statuses.append(merged["stages"]["revision"].get("status", "success"))
    except Exception as e:
        merged["stages"]["revision"] = {"status": "error", "message": str(e)}
        statuses.append("error")

    # A1 fix (stress): grounding stage — every numeric claim in the step's
    # conclusions.md must trace to a number in its outputs, so a step can't be
    # finalized citing p=0.001 / d=0.85 that no script ever produced. Only runs
    # when the step has a conclusions.md with claims; ungrounded claims downgrade
    # to a warning the AI must resolve (override via override_grounding_gate +
    # rationale for the rare intentionally-external number).
    override_grounding = bool(arguments.get("override_grounding_gate"))
    if override_grounding and not rationale:
        return _text(_error(
            what="override_grounding_gate=true requires override_rationale",
            why="empty rationale would silently no-op the override",
            next_action="pass override_rationale=\"...\" (>=20 chars, multi-word)",
        ))
    if override_grounding and rationale:
        thin = validate_override_rationale(rationale)
        if thin is not None:
            return _text(thin)
    try:
        from research_os.tools.actions.audit.claim_grounding import audit_claims
        concl = f"workspace/{step_id}/conclusions.md"
        if (root / concl).exists():
            g = audit_claims(root, target_path=concl)
            if override_grounding and rationale and g.get("status") in ("error", "warning"):
                g["overridden"] = True
                g["override_rationale"] = rationale
                g["status"] = "warning"
                from research_os.project_ops import log_override
                log_override(
                    root, tool="tool_step_complete", gate="claim_grounding",
                    rationale=rationale, extra={"step_id": step_id},
                )
            merged["stages"]["grounding"] = g
            statuses.append(g.get("status", "success"))
        else:
            merged["stages"]["grounding"] = {
                "status": "success",
                "message": "no conclusions.md with claims to ground (trivially passes)",
            }
    except Exception as e:
        merged["stages"]["grounding"] = {"status": "error", "message": str(e)}
        statuses.append("error")

    if "error" in statuses:
        merged["overall_status"] = "error"
    elif "warning" in statuses:
        merged["overall_status"] = "warning"
    else:
        merged["overall_status"] = "success"

    # Phase 8 — advance current_tier when the just-finished step's
    # protocol moves the project across a tier boundary. Best-effort;
    # never fails the bundle. tier_transition is null when no protocol
    # is associated with the step, or when the new tier matches the
    # current one.
    try:
        from research_os.tools.actions.router import _resolve_tier
        from research_os.tools.actions.state.tier_state import set_current_tier
        next_proto = _latest_protocol_for_step(root, step_id)
        if next_proto:
            new_tier = _resolve_tier(next_proto)
            if new_tier:
                trans = set_current_tier(
                    root,
                    new_tier,
                    source_protocol=next_proto,
                    via="tool_step_complete",
                )
                merged["tier_transition"] = trans
                merged["tier"] = new_tier
    except Exception as exc:
        logger.debug("tier advance on step_complete failed: %s", exc)

    merged["_note"] = (
        "Bundle result. Surface revision_options verbatim per the "
        "anti-one-shot doctrine; do not auto-scaffold the next step "
        "unless autonomy_level='autopilot'."
    )
    # Emit a conformant v2.1.0 envelope (was a raw dict missing all 9 keys).
    # overall_status -> envelope status; merged is preserved as the payload so
    # stages / tier_transition / revision_options stay visible on every path.
    env = _success(merged)
    if merged["overall_status"] == "error":
        failed = [
            s for s, v in (merged.get("stages") or {}).items()
            if isinstance(v, dict) and v.get("status") == "error"
        ]
        env["status"] = "error"
        env["error"] = (
            "tool_step_complete — failing stage(s): " + (", ".join(failed) or "unknown")
        )
    return _text(env)


def _handle_tool_finalize_project(name, arguments, root):
    """Server-enforced ship gate — the one gate that can REFUSE 'done'.

    operation='check' (default) reports blockers without refusing.
    operation='finalize' enforces: a non-empty blocker set returns a hard
    error unless a verifiable researcher override clears it.
    """
    from research_os.tools.actions.audit.ship_gate import finalize_project

    res = finalize_project(
        root,
        operation=str(arguments.get("operation") or "check"),
        override=bool(arguments.get("override", False)),
        override_rationale=str(arguments.get("override_rationale", "")),
    )
    status = res.get("status")
    # 'clear' / 'overridden' → success envelope (deliverable may ship).
    # 'check'+'blocked' → success envelope (advisory report; not a refusal).
    # 'finalize'+'blocked' → hard error: this is the refusal of 'done'.
    # 'error' → bad override / bad operation → error envelope.
    if status == "blocked" and res.get("operation") == "finalize":
        return _text(_error(
            what="ship_gate_blocked",
            why=res.get("message", "unresolved ship blockers"),
            next_action=(
                "resolve the blockers in the report, or call "
                "tool_finalize_project(operation='finalize', override=true, "
                "override_rationale='...') if the researcher authorizes "
                "shipping anyway"
            ),
            audit_findings=res.get("blockers") or None,
        ))
    if status == "error":
        return _text(_error(res.get("message", "finalize_project error")))
    return _text(_success(res))


HANDLERS = {
    "tool_dry_run": _handle_tool_dry_run,
    "tool_finalize_project": _handle_tool_finalize_project,
}
