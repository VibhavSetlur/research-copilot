"""Handlers — synthesis_reviewer sub-domain.

Carved out of handlers/synthesis.py to stay under the 600-line ceiling.
"""
from __future__ import annotations

from .._handlers_runtime import _error, _success, _text


__all__ = [
    "_handle_tool_rebuttal_draft",
    "_handle_tool_reviewer_response_compile",
    "_handle_tool_reviewer",
    "_handle_tool_response_to_reviewers",
]


def _handle_tool_rebuttal_draft(name, arguments, root):
    from research_os.tools.actions.synthesis.reviewer import rebuttal_draft
    res = rebuttal_draft(
        root,
        comment=arguments["comment"],
        persona=arguments["persona"],
        evidence_paths=arguments.get("evidence_paths"),
    )
    if res.get("status") == "error":
        return _text(_error(res.get("message", "rebuttal_draft failed")))
    return _text(_success(res))


def _handle_tool_reviewer_response_compile(name, arguments, root):
    from research_os.tools.actions.synthesis.reviewer import (
        reviewer_response_compile,
    )
    res = reviewer_response_compile(root)
    if res.get("status") == "error":
        return _text(_error(res.get("message", "compile failed")))
    return _text(_success(res))


def _handle_tool_reviewer(name, arguments, root):
    """Reviewer-response dispatcher.

    Operations:
      response → write synthesis/response_to_reviewers.md template
      rebuttal → scaffold one rebuttal .md w/ evidence inventory
      compile  → assemble rebuttals into response_to_reviewers.md + PDF

    Per-operation alias names (``tool_response_to_reviewers``,
    ``tool_rebuttal_draft``, ``tool_reviewer_response_compile``) are
    aliased here with operation injected via
    ``_ALIAS_PARAM_INJECTION``.
    """
    op = arguments.get("operation")
    if not op:
        return _text(_error(
            "tool_reviewer requires operation='response'|'rebuttal'|'compile'."
        ))
    if op == "response":
        return _handle_tool_response_to_reviewers(name, arguments, root)
    if op == "rebuttal":
        return _handle_tool_rebuttal_draft(name, arguments, root)
    if op == "compile":
        return _handle_tool_reviewer_response_compile(name, arguments, root)
    return _text(_error(
        f"tool_reviewer: unknown operation '{op}'. "
        "Valid operations: response, rebuttal, compile."
    ))


def _handle_tool_response_to_reviewers(name, arguments, root):
    from research_os.tools.actions.audit.redteam import write_response_template

    res = write_response_template(root, review_path=arguments.get("review_path"))
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "response_to_reviewers failed")))


HANDLERS = {
    "tool_reviewer": _handle_tool_reviewer,
}
