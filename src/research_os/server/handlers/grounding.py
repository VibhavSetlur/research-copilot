"""Handlers for the grounding domain.

Extracted from server/_core.py as part of the Phase-10 modular split.
The HANDLERS dict at the bottom is consumed by handlers/__init__.py
where it is merged into the canonical _HANDLERS map.
"""
from __future__ import annotations

from .._handlers_runtime import *  # noqa: F401,F403
# mem_log dispatcher delegates to _handle_mem_hypothesis_update which lives
# in methodology.py — pull it into this module's namespace.
from .methodology import _handle_mem_hypothesis_update  # noqa: F401

__all__ = [
    "_handle_mem_analysis_log",
    "_handle_mem_methods_append",
    "_handle_mem_decision_log",
    "_handle_tool_thought_log",
    "_handle_tool_thought_trace",
    "_handle_tool_thought",
    "_handle_tool_grounding_register",
    "_handle_tool_ground_from_context",
    "_handle_tool_claim_verify",
    "_handle_tool_grounding_verify",
    "_handle_tool_lessons_record",
    "_handle_tool_lessons_consult",
    "_handle_tool_dead_end_lessons",
    "_handle_tool_reliability_log_event",
    "_handle_tool_reliability_report",
    "_handle_tool_failure_record",
    "_handle_tool_failure_check",
    "_handle_tool_failure_list",
    "_handle_tool_mistake_replay",
    "_handle_tool_ground",
    "_handle_tool_verify",
    "_handle_tool_lessons",
    "_handle_tool_skills",
    "_handle_tool_reliability",
    "_handle_mem_log",
]

def _handle_mem_analysis_log(name, arguments, root):
    entry = arguments.get("entry")
    if not entry:
        return _text(_error(
            "mem_log kind='analysis' requires entry= (the analysis note to log)."
        ))
    log_path = root / "workspace" / "analysis.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"[{now_iso()}] {entry}\n")
    _update_workflow_mermaid(root)
    return _text(_success({"logged": True, "path": "workspace/analysis.md"}))


def _handle_mem_methods_append(name, arguments, root):
    method = arguments.get("method")
    if not method:
        return _text(_error(
            "mem_log kind='methods' requires method= (the method or step description)."
        ))
    m_path = root / "workspace" / "methods.md"
    m_path.parent.mkdir(parents=True, exist_ok=True)
    ts = now_iso()
    if len(arguments) == 1:
        line = f"- {method}\n"
    else:
        step_name = arguments.get("step_name", "Step")
        step_number = arguments.get("step_number", "")
        heading = f"{step_number} — {step_name}" if step_number else step_name
        lines = [f"\n## {ts} — {heading}"]
        lines.append(f"  - **Method**: {method}")
        if arguments.get("dataset_name"):
            h = arguments.get("dataset_hash", "N/A")
            lines.append(f"  - **Dataset**: {arguments['dataset_name']} (sha256: {h})")
        if arguments.get("implementation"):
            lines.append(f"  - **Implementation**: {arguments['implementation']}")
        if arguments.get("parameters"):
            lines.append(f"  - **Parameters**: {arguments['parameters']}")
        if arguments.get("justification"):
            lines.append(f"  - **Justification**: {arguments['justification']}")
        if arguments.get("assumptions"):
            for a in arguments["assumptions"]:
                lines.append(f"  - **Assumption checked**: {a}")
        line = "\n".join(lines) + "\n"
    with open(m_path, "a") as f:
        f.write(line)
    return _text(_success({"logged": True, "path": "workspace/methods.md"}))


def _handle_mem_decision_log(name, arguments, root):
    context = arguments.get("context")
    selected = arguments.get("selected")
    rationale = arguments.get("rationale")
    missing = [k for k, v in (
        ("context", context), ("selected", selected), ("rationale", rationale),
    ) if not v]
    if missing:
        return _text(_error(
            "mem_log kind='decision' requires "
            + ", ".join(f"{k}=" for k in missing)
            + " (context = the choice point, selected = what you chose, "
            "rationale = why)."
        ))
    res = log_decision(context, selected, rationale, root=root)
    return _text(_success(res))


def _handle_tool_thought_log(name, arguments, root):
    from research_os.tools.actions.research.grounding import thought_log

    res = thought_log(
        root,
        kind=arguments["kind"],
        content=arguments["content"],
        step_id=arguments.get("step_id"),
        decision_id=arguments.get("decision_id"),
        metadata=arguments.get("metadata"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "thought_log failed")))


def _handle_tool_thought_trace(name, arguments, root):
    from research_os.tools.actions.research.grounding import thought_trace

    return _text(_success(thought_trace(
        root,
        step_id=arguments.get("step_id"),
        decision_id=arguments.get("decision_id"),
        tail=int(arguments.get("tail", 50)),
    )))


def _handle_tool_thought(name, arguments, root):
    """Unified thought dispatcher.

    Operations:
      log   → tool_thought_log   (append one ReAct trace entry)
      trace → tool_thought_trace (read the recent thought trace tail)

    Every legacy ``tool_thought_log`` / ``tool_thought_trace`` name is
    aliased to this entry point and has its operation injected via
    ``_ALIAS_PARAM_INJECTION`` so callers (researchers, scripts,
    protocols) using the older per-operation names keep working
    unchanged.
    """
    op = arguments.get("operation")
    if not op:
        return _text(_error(
            "tool_thought requires operation='log'|'trace'."
        ))
    if op == "log":
        return _handle_tool_thought_log(name, arguments, root)
    if op == "trace":
        return _handle_tool_thought_trace(name, arguments, root)
    return _text(_error(
        f"tool_thought: unknown operation '{op}'. "
        "Valid: log | trace."
    ))


def _handle_tool_grounding_register(name, arguments, root):
    from research_os.tools.actions.research.grounding import grounding_register

    claim = arguments.get("claim")
    sources = arguments.get("sources")
    if not claim:
        return _text(_error("tool_ground requires claim= (the statement to ground)."))
    if not sources:
        return _text(_error(
            "tool_ground mode='explicit' requires sources= "
            "(the list of supporting sources)."
        ))
    res = grounding_register(
        root,
        decision_id=arguments.get("decision_id"),
        claim=claim,
        sources=sources,
        step_id=arguments.get("step_id"),
        confidence=arguments.get("confidence", "medium"),
        notes=arguments.get("notes", ""),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "grounding_register failed")))


def _handle_tool_ground_from_context(name, arguments, root):
    from research_os.tools.actions.research.grounding import ground_from_context

    claim = arguments.get("claim")
    context_paths = arguments.get("context_paths")
    if not claim:
        return _text(_error("tool_ground requires claim= (the statement to ground)."))
    if not context_paths:
        return _text(_error(
            "tool_ground mode='from_context' requires context_paths= "
            "(the workspace paths the claim is grounded in)."
        ))
    res = ground_from_context(
        root,
        decision_id=arguments.get("decision_id"),
        claim=claim,
        context_paths=context_paths,
        cited_excerpts=arguments.get("cited_excerpts"),
        confidence=arguments.get("confidence", "medium"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "ground_from_context failed")))


def _handle_tool_claim_verify(name, arguments, root):
    from research_os.tools.actions.research.grounding import claim_verify

    claim = arguments.get("claim")
    verifications = arguments.get("verifications")
    if not claim:
        return _text(_error(
            "tool_verify scope='claim' requires claim= (the claim to verify)."
        ))
    if not verifications:
        return _text(_error(
            "tool_verify scope='claim' requires verifications= "
            "(the list of {question, answer, supports, evidence} checks)."
        ))
    res = claim_verify(
        root,
        claim=claim,
        verifications=verifications,
        decision_id=arguments.get("decision_id"),
        step_id=arguments.get("step_id"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "claim_verify failed")))


def _handle_tool_grounding_verify(name, arguments, root):
    from research_os.tools.actions.research.grounding import grounding_verify

    return _text(_success(grounding_verify(root)))


def _handle_tool_lessons_record(name, arguments, root):
    from research_os.tools.actions.research.lessons import lessons_record

    res = lessons_record(
        root,
        outcome=arguments["outcome"],
        reflection=arguments["reflection"],
        what_worked=arguments.get("what_worked", ""),
        what_didnt=arguments.get("what_didnt", ""),
        recommendation=arguments.get("recommendation", ""),
        tags=arguments.get("tags"),
        step_id=arguments.get("step_id"),
        scope=arguments.get("scope", "step"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "lessons_record failed")))


def _handle_tool_lessons_consult(name, arguments, root):
    from research_os.tools.actions.research.lessons import lessons_consult

    return _text(_success(lessons_consult(
        root,
        task=arguments["task"],
        tags=arguments.get("tags"),
        top_k=int(arguments.get("top_k", 5)),
        scope_filter=arguments.get("scope_filter"),
    )))


def _handle_tool_dead_end_lessons(name, arguments, root):
    from research_os.tools.actions.research.planning import dead_end_lessons

    res = dead_end_lessons(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "dead_end_lessons failed")))


def _handle_tool_skills(name, arguments, root):
    """Self-improving skill registry: distill | promote | list."""
    from research_os.tools.actions.research.skills import (
        distill_skills,
        list_skills,
        promote_skills,
    )

    op = str(arguments.get("operation", "")).strip()
    min_occ = int(arguments.get("min_occurrences", 2) or 2)
    if op == "distill":
        return _text(_success(distill_skills(root, min_occurrences=min_occ)))
    if op == "promote":
        return _text(_success(promote_skills(root, min_occurrences=min_occ)))
    if op == "list":
        return _text(_success(list_skills(root)))
    return _text(_error(
        f"Unknown tool_skills operation '{op}' — use distill | promote | list"
    ))


def _handle_tool_reliability_log_event(name, arguments, root):
    from research_os.tools.actions.state.reliability import log_event
    return _text(log_event(
        root,
        str(arguments.get("event_type", "")),
        protocol_name=arguments.get("protocol_name"),
        model_profile=arguments.get("model_profile"),
        payload=arguments.get("payload") or {},
    ))


def _handle_tool_reliability_report(name, arguments, root):
    from research_os.tools.actions.state.reliability import reliability_report
    return _text(reliability_report(root))


def _handle_tool_failure_record(name, arguments, root):
    from research_os.tools.actions.state.paywall_memory import record_failure
    return _text(record_failure(
        root,
        tool=str(arguments.get("tool", "")),
        target=str(arguments.get("target", "")),
        reason=str(arguments.get("reason", "")),
        error_text=str(arguments.get("error_text", "")),
        permanent=bool(arguments.get("permanent", False)),
    ))


def _handle_tool_failure_check(name, arguments, root):
    from research_os.tools.actions.state.paywall_memory import is_known_bad
    return _text(is_known_bad(root, str(arguments.get("target", ""))))


def _handle_tool_failure_list(name, arguments, root):
    from research_os.tools.actions.state.paywall_memory import list_failures
    limit = arguments.get("limit")
    if isinstance(limit, (int, float)) and limit > 0:
        return _text(list_failures(root, limit=int(limit)))
    return _text(list_failures(root))


def _handle_tool_mistake_replay(name, arguments, root):
    from research_os.tools.actions.state.mistake_replay import mistake_replay
    limit = arguments.get("limit") or 5
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    return _text(mistake_replay(root, limit=limit))


def _handle_tool_ground(name, arguments, root):
    """Unified grounding-register dispatcher.

    mode='explicit'  → tool_grounding_register (sources list)
    mode='from_context' → tool_ground_from_context (context_paths list)
    """
    mode = arguments.get("mode")
    if not mode:
        if name == "tool_ground_from_context" or "context_paths" in arguments:
            mode = "from_context"
        else:
            mode = "explicit"
    if mode == "explicit":
        return _handle_tool_grounding_register(name, arguments, root)
    if mode == "from_context":
        return _handle_tool_ground_from_context(name, arguments, root)
    return _text(_error(
        f"Unknown ground mode '{mode}'. Use 'explicit' or 'from_context'."
    ))


def _handle_tool_verify(name, arguments, root):
    """Unified verify dispatcher.

    scope='claim'   → tool_claim_verify (claim + verifications list)
    scope='project' → tool_grounding_verify (whole-project grounding sweep)
    scope='outputs' → verify_outputs (declared files exist + are non-empty)
    """
    scope = arguments.get("scope")
    if not scope:
        if name == "tool_grounding_verify" or not arguments.get("claim"):
            scope = "project"
        else:
            scope = "claim"
    if scope == "claim":
        return _handle_tool_claim_verify(name, arguments, root)
    if scope == "project":
        return _handle_tool_grounding_verify(name, arguments, root)
    if scope in ("outputs", "step"):
        from research_os.tools.actions.research.grounding import verify_outputs

        try:
            min_bytes = int(arguments.get("min_bytes", 1))
        except (TypeError, ValueError):
            min_bytes = 1
        res = verify_outputs(
            root,
            scope="project" if scope == "outputs" and arguments.get("all_protocols")
            else ("step" if scope == "step" else "protocol"),
            protocol_name=arguments.get("protocol_name"),
            min_bytes=min_bytes,
        )
        if res.get("status") == "error":
            return _text(_error(res.get("message", "verify_outputs failed")))
        return _text(_success(res))
    return _text(_error(
        f"Unknown verify scope '{scope}'. Use 'claim', 'project', or 'outputs'."
    ))


def _handle_tool_lessons(name, arguments, root):
    """Unified lessons + failure-memory dispatcher.

    Operations:
      record         → tool_lessons_record (Reflexion-style lesson append)
      consult        → tool_lessons_consult (retrieve top-K prior lessons)
      failure_record → tool_failure_record (paywall / 404 / permanent-error memory)
      failure_check  → tool_failure_check (is this URL/DOI known-bad?)
      failure_list   → tool_failure_list (recent tool failures)
      dead_end       → tool_dead_end_lessons (pull lessons from __DEAD_END folders)
      mistake_replay → tool_mistake_replay (recurring patterns from reliability + override log)
    """
    legacy = {
        "tool_lessons_record":   "record",
        "tool_lessons_consult":  "consult",
        "tool_failure_record":   "failure_record",
        "tool_failure_check":    "failure_check",
        "tool_failure_list":     "failure_list",
        "tool_dead_end_lessons": "dead_end",
        "tool_mistake_replay":   "mistake_replay",
    }
    op = arguments.get("operation") or legacy.get(name)
    if not op:
        # Heuristic fallback for the original tool_lessons surface.
        op = "consult" if "task" in arguments else "record"
    if op == "record":
        return _handle_tool_lessons_record(name, arguments, root)
    if op == "consult":
        return _handle_tool_lessons_consult(name, arguments, root)
    if op == "failure_record":
        return _handle_tool_failure_record(name, arguments, root)
    if op == "failure_check":
        return _handle_tool_failure_check(name, arguments, root)
    if op == "failure_list":
        return _handle_tool_failure_list(name, arguments, root)
    if op == "dead_end":
        return _handle_tool_dead_end_lessons(name, arguments, root)
    if op == "mistake_replay":
        return _handle_tool_mistake_replay(name, arguments, root)
    return _text(_error(f"Unknown lessons operation '{op}'"))


def _handle_tool_reliability(name, arguments, root):
    """Unified reliability-log dispatcher.

    Operations:
      log_event → tool_reliability_log_event (append structural event)
      report    → tool_reliability_report   (redacted markdown summary)
    """
    legacy = {
        "tool_reliability_log_event": "log_event",
        "tool_reliability_report":    "report",
    }
    op = arguments.get("operation") or legacy.get(name)
    if not op:
        # Heuristic: presence of event_type implies log_event; otherwise report.
        op = "log_event" if "event_type" in arguments else "report"
    if op == "log_event":
        return _handle_tool_reliability_log_event(name, arguments, root)
    if op == "report":
        return _handle_tool_reliability_report(name, arguments, root)
    return _text(_error(f"Unknown reliability operation '{op}'"))


def _handle_mem_log(name, arguments, root):
    """Unified memory-log dispatcher.

    kind='methods'    → mem_methods_append
    kind='decision'   → mem_decision_log
    kind='hypothesis' → mem_hypothesis_add (new entry) or mem_hypothesis_update
                        (when hypothesis_id= is present)
    kind='analysis'   → mem_analysis_log
    kind='lesson'     → tool_lessons (passthrough; `operation` selects sub-op:
                        record | consult | failure_record | failure_check |
                        failure_list | dead_end | mistake_replay)
    """
    arguments = arguments or {}
    legacy = {
        "mem_methods_append": "methods",
        "mem_decision_log": "decision",
        "mem_hypothesis_update": "hypothesis",
        "mem_analysis_log": "analysis",
    }
    kind = arguments.get("kind") or legacy.get(name)
    if not kind:
        return _text(_error(
            "mem_log requires kind='methods'|'decision'|'hypothesis'|'analysis'|'lesson'"
        ))
    if kind == "methods":
        return _handle_mem_methods_append(name, arguments, root)
    if kind == "decision":
        return _handle_mem_decision_log(name, arguments, root)
    if kind == "hypothesis":
        # Updating an existing hypothesis requires its id. Adding a new
        # hypothesis goes through the mem_hypothesis(operation='add') tool.
        if not arguments.get("hypothesis_id"):
            return _text(_error(
                "mem_log(kind='hypothesis') updates an existing hypothesis and "
                "requires hypothesis_id=; use mem_hypothesis(operation='add') to "
                "record a new hypothesis"
            ))
        return _handle_mem_hypothesis_update(name, arguments, root)
    if kind == "analysis":
        return _handle_mem_analysis_log(name, arguments, root)
    if kind == "lesson":
        # Delegate to tool_lessons; map `operation` through as-is.
        return _handle_tool_lessons(name, arguments, root)
    return _text(_error(f"Unknown mem_log kind '{kind}'"))


HANDLERS = {
    "tool_thought": _handle_tool_thought,
    "tool_ground": _handle_tool_ground,
    "tool_verify": _handle_tool_verify,
    "tool_lessons": _handle_tool_lessons,
    "tool_reliability": _handle_tool_reliability,
    "mem_log": _handle_mem_log,
}
