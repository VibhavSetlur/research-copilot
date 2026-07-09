"""Handlers for the methodology domain.

Extracted from server/_core.py as part of the Phase-10 modular split.
The HANDLERS dict at the bottom is consumed by handlers/__init__.py
where it is merged into the canonical _HANDLERS map.
"""
from __future__ import annotations

# ruff: noqa: F403, F405  # legacy handler runtime star-import compatibility
from .._handlers_runtime import *  # noqa: F401,F403
from .._handlers_runtime import (
    _error,
    _success,
    _text,
    _STEP_DISPATCH,
    _STEP_PIPELINE_DISPATCH,
)
# env_lock's handler lives in meta_routing, but the tool_step dispatcher
# resolves operations via this module's globals() — so it must be importable
# here or operation='env_lock' silently fails "handler not callable" (F1).
from .meta_routing import _handle_tool_step_env_lock  # noqa: F401

__all__ = [
    "_handle_tool_plan_advance",
    "_handle_tool_plan_turn",
    "_handle_tool_plan_clear",
    "_handle_tool_step",
    "_handle_tool_step_pipeline",
    "_handle_tool_step_revision_options",
    "_handle_tool_step_iterate",
    "_handle_tool_step_iterations_list",
    "_handle_tool_step_pipeline_define",
    "_handle_tool_step_pipeline_run",
    "_handle_tool_step_pipeline_status",
    "_handle_tool_step_pipeline_diagram",
    "_handle_tool_plan_step_grounded",
    "_handle_tool_preregister_freeze",
    "_handle_tool_preregister_diff",
    "_handle_tool_preregister",
    "_handle_tool_sensitivity_define",
    "_handle_tool_sensitivity_run",
    "_handle_tool_sensitivity",
    "_handle_tool_redteam_review",
    "_handle_tool_null_findings_report",
    "_handle_tool_plan_step",
    "_handle_mem_hypothesis_add",
    "_handle_mem_hypothesis_update",
    "_handle_mem_hypothesis_list",
    "_handle_tool_plan_next_step",
    "_handle_tool_branch_recommendation",
    "_handle_tool_session_resume",
    "_handle_tool_progress_digest",
    "_handle_tool_quick_review",
    "_handle_tool_plan",
]

def _handle_tool_plan_advance(name, arguments, root):
    from research_os.project_ops import log_override, validate_override_rationale
    from research_os.tools.actions.router import advance_plan

    override = bool(arguments.get("override_gate", False))
    raw_rationale = arguments.get("override_rationale")
    # A bypass is applied + logged whenever override_gate=true, so the
    # rationale is required whenever it's honoured (not just under
    # policy=enforce) — else the override slips through logging rationale=None.
    if override and not (raw_rationale and str(raw_rationale).strip()):
        return _text(_error(
            what="override_gate=true requires override_rationale",
            why="an un-rationaled bypass would log rationale=None and slip past the pre-submission audit",
            next_action='pass override_rationale="..." (>=20 chars, multi-word, substantive)',
        ))
    # The rationale must be substantive (>=20 chars, multi-word, not a placeholder).
    if override and raw_rationale:
        thin = validate_override_rationale(raw_rationale)
        if thin is not None:
            return _text(thin)
    res = advance_plan(root, override_gate=override)
    # Log the override ONLY when the gate would have blocked — a bypass
    # passed on a deliverable that already met the gate is a phantom
    # entry the pre-submission audit shouldn't have to defend.
    if override and res.get("bypassed_blockers"):
        log_override(
            root,
            tool="tool_plan_advance",
            gate="deliverable_completeness",
            rationale=arguments.get("override_rationale"),
            extra={"blocker_count": len(res["bypassed_blockers"])},
        )
    # status='blocked' is informational, not a transport-level error.
    if res.get("status") in {"success", "blocked"}:
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_plan_advance failed")))


def _handle_tool_plan_turn(name, arguments, root):
    from research_os.tools.actions.router import plan_turn

    res = plan_turn(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_plan_turn failed")))


def _handle_tool_plan_clear(name, arguments, root):
    from research_os.tools.actions.router import clear_active_plan

    res = clear_active_plan(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_plan_clear failed")))


def _handle_tool_step(name, arguments, root):
    """Unified step-lifecycle dispatcher.

    Routes operation → the matching per-operation handler. Every legacy
    ``tool_step_*`` name (except ``tool_step_complete`` and the pipeline
    family) is aliased to this entry point and has its operation
    injected via ``_ALIAS_PARAM_INJECTION`` so callers (researchers,
    scripts, protocols) using the older per-operation names keep working
    unchanged.
    """
    op = arguments.get("operation")
    if not op:
        valid = ", ".join(sorted(_STEP_DISPATCH))
        return _text(_error(
            f"tool_step requires operation=. Valid operations: {valid}."
        ))
    handler_name = _STEP_DISPATCH.get(op)
    if not handler_name:
        valid = ", ".join(sorted(_STEP_DISPATCH))
        return _text(_error(
            f"tool_step: unknown operation '{op}'. "
            f"Valid operations: {valid}."
        ))
    handler = globals().get(handler_name)
    if not callable(handler):
        return _text(_error(
            f"tool_step: handler '{handler_name}' is not callable."
        ))
    return handler(name, arguments, root)


def _handle_tool_step_pipeline(name, arguments, root):
    """Unified step-pipeline dispatcher.

    Routes operation → the matching per-operation handler. Every legacy
    ``tool_step_pipeline_*`` name is aliased to this entry point and has
    its operation injected via ``_ALIAS_PARAM_INJECTION`` so callers
    using the older per-operation names keep working unchanged.
    """
    op = arguments.get("operation")
    if not op:
        valid = ", ".join(sorted(_STEP_PIPELINE_DISPATCH))
        return _text(_error(
            f"tool_step_pipeline requires operation=. "
            f"Valid operations: {valid}."
        ))
    handler_name = _STEP_PIPELINE_DISPATCH.get(op)
    if not handler_name:
        valid = ", ".join(sorted(_STEP_PIPELINE_DISPATCH))
        return _text(_error(
            f"tool_step_pipeline: unknown operation '{op}'. "
            f"Valid operations: {valid}."
        ))
    handler = globals().get(handler_name)
    if not callable(handler):
        return _text(_error(
            f"tool_step_pipeline: handler '{handler_name}' is not callable."
        ))
    return handler(name, arguments, root)


def _handle_tool_step_revision_options(name, arguments, root):
    from research_os.tools.actions.state.revision import step_revision_options

    try:
        res = step_revision_options(arguments["step_id"], root)
        if res.get("status") == "success":
            return _text(_success(res))
        return _text(_error(res.get("message", "step_revision_options failed")))
    except Exception as e:
        return _text(_error(str(e)))


def _handle_tool_step_iterate(name, arguments, root):
    from research_os.tools.actions.state.iteration import iterate_step

    try:
        res = iterate_step(
            root,
            step_id=arguments["step_id"],
            rationale=arguments["rationale"],
            scripts=arguments.get("scripts"),
            figures=arguments.get("figures"),
            tables=arguments.get("tables"),
            bump_conclusion=bool(arguments.get("bump_conclusion", True)),
        )
        return _text(_success(res))
    except (ValueError, FileNotFoundError) as e:
        return _text(_error(str(e)))


def _handle_tool_step_iterations_list(name, arguments, root):
    from research_os.tools.actions.state.iteration import list_iterations

    try:
        return _text(_success(list_iterations(root, arguments["step_id"])))
    except (KeyError, FileNotFoundError) as e:
        return _text(_error(str(e)))


def _handle_tool_step_pipeline_define(name, arguments, root):
    from research_os.tools.actions.exec.step_pipeline import define_pipeline

    res = define_pipeline(
        arguments["step_id"], root,
        name=arguments.get("name"),
        description=arguments.get("description", ""),
        nodes=arguments.get("nodes"),
        template=arguments.get("template", "default"),
    )
    if res.get("status") in {"success", "exists"}:
        return _text(_success(res))
    return _text(_error(res.get("message", "step_pipeline_define failed")))


def _handle_tool_step_pipeline_run(name, arguments, root):
    from research_os.tools.actions.exec.step_pipeline import run_pipeline

    res = run_pipeline(
        arguments["step_id"], root,
        only=arguments.get("only"),
        force=bool(arguments.get("force", False)),
        dry_run=bool(arguments.get("dry_run", False)),
    )
    return _text(_success(res) if res.get("status") == "success"
                 else _error(res.get("advice") or res.get("message", "pipeline run failed")))


def _handle_tool_step_pipeline_status(name, arguments, root):
    from research_os.tools.actions.exec.step_pipeline import pipeline_status

    return _text(_success(pipeline_status(arguments["step_id"], root)))


def _handle_tool_step_pipeline_diagram(name, arguments, root):
    from research_os.tools.actions.exec.step_pipeline import render_pipeline_diagram

    res = render_pipeline_diagram(arguments["step_id"], root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "pipeline diagram failed")))


def _handle_tool_plan_step_grounded(name, arguments, root):
    from research_os.tools.actions.research.research import plan_step_grounded

    res = plan_step_grounded(
        arguments["goal"], root,
        inputs_to_consult=arguments.get("inputs_to_consult"),
        context_to_consult=arguments.get("context_to_consult"),
        literature_queries=arguments.get("literature_queries"),
        max_substeps=int(arguments.get("max_substeps", 6)),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "plan_step_grounded failed")))


def _handle_tool_preregister_freeze(name, arguments, root):
    from research_os.tools.actions.audit.preregistration import (
        freeze_preregistration,
    )

    res = freeze_preregistration(
        root,
        primary_outcomes=arguments.get("primary_outcomes"),
        secondary_outcomes=arguments.get("secondary_outcomes"),
        target_n=arguments.get("target_n"),
        power_assumption=arguments.get("power_assumption"),
        stopping_rule=arguments.get("stopping_rule"),
        subgroups=arguments.get("subgroups"),
        sensitivity=arguments.get("sensitivity"),
        multiplicity=arguments.get("multiplicity"),
        inclusion=arguments.get("inclusion"),
        exclusion=arguments.get("exclusion"),
        missing_data=arguments.get("missing_data"),
        additional_analyses=arguments.get("additional_analyses"),
        contingencies=arguments.get("contingencies"),
        anticipated_deviations=arguments.get("anticipated_deviations"),
        data_status=arguments.get("data_status", "not yet collected"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "preregister_freeze failed")))


def _handle_tool_preregister_diff(name, arguments, root):
    from research_os.tools.actions.audit.preregistration import (
        diff_preregistration,
    )

    return _text(_success(diff_preregistration(root)))


def _handle_tool_preregister(name, arguments, root):
    """Unified preregistration dispatcher.

    Operations:
      freeze → tool_preregister_freeze (snapshot SAP + hypotheses, content-hashed)
      diff   → tool_preregister_diff   (compare frozen SAP against current state)
    """
    op = arguments.get("operation")
    if not op:
        return _text(_error(
            "tool_preregister requires operation='freeze' or operation='diff'."
        ))
    if op == "freeze":
        return _handle_tool_preregister_freeze(name, arguments, root)
    if op == "diff":
        return _handle_tool_preregister_diff(name, arguments, root)
    return _text(_error(
        f"tool_preregister: unknown operation '{op}'. "
        "Valid operations: freeze, diff."
    ))


def _handle_tool_sensitivity_define(name, arguments, root):
    from research_os.tools.actions.exec.sensitivity import define_sensitivity

    res = define_sensitivity(
        arguments["step_id"], root,
        base_script=arguments["base_script"],
        estimate_column=arguments.get("estimate_column", "estimate"),
        ci_columns=tuple(arguments.get("ci_columns", ["ci_lo", "ci_hi"])),
        grid=arguments.get("grid"),
        output_csv=arguments.get("output_csv", "data/next_step_output/grid_results.csv"),
    )
    if res.get("status") in {"success", "exists"}:
        return _text(_success(res))
    return _text(_error(res.get("message", "sensitivity_define failed")))


def _handle_tool_sensitivity_run(name, arguments, root):
    from research_os.tools.actions.exec.sensitivity import run_sensitivity

    res = run_sensitivity(
        arguments["step_id"], root,
        max_specs=arguments.get("max_specs"),
        render_figure=bool(arguments.get("render_figure", True)),
    )
    return _text(_success(res))


def _handle_tool_sensitivity(name, arguments, root):
    """Unified sensitivity dispatcher.

    Operations:
      define → tool_sensitivity_define (author the multiverse grid)
      run    → tool_sensitivity_run    (execute the grid + render the spec curve)
    """
    op = arguments.get("operation")
    if not op:
        return _text(_error(
            "tool_sensitivity requires operation='define' or operation='run'."
        ))
    if op == "define":
        return _handle_tool_sensitivity_define(name, arguments, root)
    if op == "run":
        return _handle_tool_sensitivity_run(name, arguments, root)
    return _text(_error(
        f"tool_sensitivity: unknown operation '{op}'. "
        "Valid operations: define, run."
    ))


def _handle_tool_redteam_review(name, arguments, root):
    from research_os.tools.actions.audit.redteam import redteam_scaffold

    res = redteam_scaffold(
        root, persona=arguments.get("persona", "methodological_skeptic"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "redteam_review failed")))


def _handle_tool_null_findings_report(name, arguments, root):
    from research_os.tools.actions.audit.null_findings import write_null_findings

    return _text(_success(write_null_findings(root)))


def _handle_tool_plan_step(name, arguments, root):
    from research_os.tools.actions.research.research import plan_step

    res = plan_step(
        arguments["goal"], root, max_substeps=int(arguments.get("max_substeps", 6))
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "plan_step failed")))


def _handle_mem_hypothesis_add(name, arguments, root):
    from research_os.tools.actions.memory.memory import hypothesis_add

    res = hypothesis_add(
        arguments["statement"],
        root,
        hypothesis_id=arguments.get("hypothesis_id"),
        direction=arguments.get("direction"),
        status=arguments.get("status", "testing"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "hypothesis_add failed")))


def _handle_mem_hypothesis_update(name, arguments, root):
    from research_os.tools.actions.memory.memory import hypothesis_update

    hypothesis_id = arguments.get("hypothesis_id")
    if not hypothesis_id:
        return _text(_error(
            "mem_log kind='hypothesis' requires hypothesis_id= "
            "(e.g. 'H1') to update an existing hypothesis."
        ))
    res = hypothesis_update(
        hypothesis_id,
        root,
        status=arguments.get("status"),
        evidence=arguments.get("evidence"),
        step=arguments.get("step"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "hypothesis_update failed")))


def _handle_mem_hypothesis_list(name, arguments, root):
    from research_os.tools.actions.memory.memory import hypothesis_list

    res = hypothesis_list(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "hypothesis_list failed")))


def _handle_tool_plan_next_step(name, arguments, root):
    from research_os.tools.actions.research.planning import plan_next_step

    res = plan_next_step(
        root,
        goal=arguments.get("goal"),
        search_literature=bool(arguments.get("search_literature", True)),
        search_tools=bool(arguments.get("search_tools", True)),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "plan_next_step failed")))


def _handle_tool_branch_recommendation(name, arguments, root):
    from research_os.tools.actions.research.planning import branch_recommendation

    res = branch_recommendation(root, reason=arguments["reason"])
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "branch_recommendation failed")))


def _handle_tool_session_resume(name, arguments, root):
    from research_os.tools.actions.research.planning import session_resume

    res = session_resume(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "session_resume failed")))


def _handle_tool_progress_digest(name, arguments, root):
    from research_os.tools.actions.research.planning import progress_digest

    res = progress_digest(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "progress_digest failed")))


def _handle_tool_quick_review(name, arguments, root):
    from research_os.tools.actions.research.planning import quick_review

    res = quick_review(
        root,
        arguments["paper_path"],
        lens=arguments.get("lens", "claims_vs_evidence"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "quick_review failed")))


def _handle_tool_plan(name, arguments, root):
    """Unified plan dispatcher.

    Core operations (tool_plan's own):
      turn    → tool_plan_turn
      advance → tool_plan_advance
      clear   → tool_plan_clear

    Step-lifecycle operations (delegated to tool_step):
      iterate | iterations_list | revision_options | env_lock

    Step-pipeline operations (delegated to tool_step_pipeline):
      define | run | status | diagram

    Grounded step planning (delegated to tool_plan_step_grounded):
      grounded_step
    """
    arguments = arguments or {}
    legacy = {
        "tool_plan_turn": "turn",
        "tool_plan_advance": "advance",
        "tool_plan_clear": "clear",
    }
    operation = arguments.get("operation") or legacy.get(name)
    if not operation:
        return _text(_error(
            "tool_plan requires operation= "
            "(turn | advance | clear | iterate | iterations_list | "
            "revision_options | env_lock | define | run | status | "
            "diagram | grounded_step)"
        ))

    # tool_plan core operations
    if operation == "turn":
        return _handle_tool_plan_turn(name, arguments, root)
    if operation == "advance":
        return _handle_tool_plan_advance(name, arguments, root)
    if operation == "clear":
        return _handle_tool_plan_clear(name, arguments, root)

    # tool_step operations (iterate / iterations_list / revision_options / env_lock)
    _STEP_OPS = set(_STEP_DISPATCH.keys())
    if operation in _STEP_OPS:
        mapped = dict(arguments)
        mapped["operation"] = operation
        return _handle_tool_step(name, mapped, root)

    # tool_step_pipeline operations (define / run / status / diagram)
    _PIPELINE_OPS = set(_STEP_PIPELINE_DISPATCH.keys())
    if operation in _PIPELINE_OPS:
        mapped = dict(arguments)
        mapped["operation"] = operation
        return _handle_tool_step_pipeline(name, mapped, root)

    # grounded step planning
    if operation == "grounded_step":
        return _handle_tool_plan_step_grounded(name, arguments, root)

    return _text(_error(f"Unknown plan operation '{operation}'"))


HANDLERS = {
    "tool_preregister": _handle_tool_preregister,
    "tool_sensitivity": _handle_tool_sensitivity,
    "tool_plan": _handle_tool_plan,
}
