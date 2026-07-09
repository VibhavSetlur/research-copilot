"""Handlers for the tool_build domain (git + build/test/lint).

Provides first-class, provenance-aware entry points for the build/* protocols
that run in workspace.mode='tool_build'. The heavy lifting lives in
``research_os.tools.actions.exec.build_tools``; these handlers just unpack
arguments, dispatch by operation, and wrap the result in the standard
envelope.
"""
from __future__ import annotations

# ruff: noqa: F403, F405  # legacy handler runtime star-import compatibility
from .._handlers_runtime import *  # noqa: F401,F403

__all__ = [
    "_handle_tool_git",
    "_handle_tool_build",
]


def _handle_tool_git(name, arguments, root):
    """Path-contained git dispatcher for the tool_build inner repo."""
    from research_os.tools.actions.exec.build_tools import git_op

    operation = arguments.get("operation")
    if not operation:
        return _text(_error(
            "tool_git requires operation= "
            "(init | status | commit | branch | tag | log | diff)."
        ))
    res = git_op(
        root,
        operation,
        message=arguments.get("message"),
        step_id=arguments.get("step_id"),
        name=arguments.get("name"),
        paths=arguments.get("paths"),
        all_changes=bool(arguments.get("all_changes", True)),
        max_count=int(arguments.get("max_count", 20)),
        annotated=bool(arguments.get("annotated", True)),
        scope=arguments.get("scope"),
    )
    # status='noop' (nothing to commit) is informational, not a hard error.
    if res.get("status") in {"success", "noop"}:
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_git failed")))


def _handle_tool_build(name, arguments, root):
    """Run the researcher-declared build/test/lint command in the inner repo."""
    from research_os.tools.actions.exec.build_tools import build_op

    operation = arguments.get("operation")
    if not operation:
        return _text(_error(
            "tool_build requires operation= (build | test | lint)."
        ))
    res = build_op(
        root,
        operation,
        timeout=int(arguments.get("timeout", 1800)),
    )
    # A failing build/test/lint is a real result the caller must see, but it
    # is NOT a transport error — surface it as a success envelope carrying
    # passed=false so audits + protocols can branch on it. Only genuine
    # tool failures (unknown op, unconfigured command, path violation) come
    # back without 'passed' and route to the error envelope.
    if "passed" in res:
        return _text(_success(res))
    return _text(_error(res.get("message", "tool_build failed")))


HANDLERS = {
    "tool_git": _handle_tool_git,
    "tool_build": _handle_tool_build,
}
