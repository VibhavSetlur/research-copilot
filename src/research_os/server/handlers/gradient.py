"""Handlers for the beginner↔PI gradient domain.

Backs tool_explain (grounded layered tutor) + tool_deliverable_chooser
(output_types-gated 'what now?' recommender). The HANDLERS dict at the
bottom is merged into the canonical _HANDLERS map by handlers/__init__.py.
"""
from __future__ import annotations

# ruff: noqa: F403, F405  # legacy handler runtime star-import compatibility
from .._handlers_runtime import *  # noqa: F401,F403

__all__ = [
    "_handle_tool_explain",
    "_handle_tool_deliverable_chooser",
]


def _handle_tool_explain(name, arguments, root):
    from research_os.tools.actions.research.gradient import explain_scaffold

    topic = (arguments or {}).get("topic")
    if not topic or not str(topic).strip():
        return _text(_error(
            "tool_explain requires topic=<concept/method to explain>."
        ))
    res = explain_scaffold(
        str(topic),
        depth=arguments.get("depth", "all"),
        audience=arguments.get("audience"),
    )
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_explain failed")))


def _handle_tool_deliverable_chooser(name, arguments, root):
    from research_os.tools.actions.research.gradient import deliverable_chooser

    res = deliverable_chooser(root)
    if res.get("status") == "success":
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_deliverable_chooser failed")))


HANDLERS: dict[str, object] = {}
