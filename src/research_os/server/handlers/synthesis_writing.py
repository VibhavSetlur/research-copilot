"""Handlers — synthesis_writing sub-domain.

Synthesis tools support AI-direct authoring: plan, validate, scaffold,
compile. They never generate prose / layout themselves.
"""
from __future__ import annotations

from .._handlers_runtime import _error, _success, _text, Path


__all__ = [
    "_handle_tool_synthesize_plan",
    "_handle_tool_synthesis_preview",
    "_handle_tool_synthesis_scaffold",
    "_handle_tool_synthesis_check",
    "_handle_tool_typst_compile",
    "_handle_tool_latex_compile",
    "_handle_tool_writing_discussion_from_verdicts",
    "_handle_tool_discussion_coverage_audit",
    "_handle_tool_figure_palette",
]


def _handle_tool_synthesize_plan(name, arguments, root):
    from research_os.tools.actions.synthesis.plan import synthesize_plan

    return _text(_success(synthesize_plan(root)))


def _handle_tool_synthesis_preview(name, arguments, root):
    from research_os.tools.actions.synthesis.preview import synthesis_preview

    return _text(_success(synthesis_preview(
        root,
        target=arguments.get("target", "paper"),
        venue=arguments.get("venue"),
        mode=arguments.get("mode", "fresh"),
    )))


def _handle_tool_synthesis_scaffold(name, arguments, root):
    from research_os.tools.actions.synthesis.scaffold import synthesis_scaffold

    res = synthesis_scaffold(
        Path(root),
        kind=arguments.get("kind", "paper"),
        overwrite=bool(arguments.get("overwrite", False)),
        confirmed=bool(arguments.get("confirmed", False)),
        archetype=arguments.get("archetype"),
        palette=arguments.get("palette"),
        step=arguments.get("step"),
        label=arguments.get("label"),
        audience=arguments.get("audience"),
        scratch=bool(arguments.get("scratch", False)),
        meeting=arguments.get("meeting"),
    )
    if res.get("status") == "error":
        return _text(_error(res.get("message", "scaffold failed")))
    return _text(_success(res))


def _handle_tool_synthesis_check(name, arguments, root):
    from research_os.tools.actions.synthesis.check import synthesis_check

    res = synthesis_check(
        Path(root),
        file=arguments.get("file"),
        mode=arguments.get("mode", "all"),
    )
    if res.get("status") == "error":
        return _text(_error(res.get("message", "synthesis_check failed")))
    return _text(_success(res))


def _handle_tool_typst_compile(name, arguments, root):
    from research_os.tools.actions.synthesis.typst_compile import typst_compile

    res = typst_compile(
        Path(root),
        source=arguments.get("source"),
        output=arguments.get("output"),
        biblio=arguments.get("biblio"),
    )
    if res.get("status") == "error":
        return _text(_error(res.get("message", "typst_compile failed")))
    return _text(_success(res))


def _handle_tool_latex_compile(name, arguments, root):
    from research_os.tools.actions.synthesis.latex import latex_compile

    res = latex_compile(root)
    # Don't wrap a failed compile (no pdflatex / no PDF) in _success — mirror
    # the typst handler so the client doesn't think a PDF exists (SYN-4).
    if res.get("status") == "error":
        return _text(_error(res.get("message") or res.get("error") or "latex_compile failed"))
    return _text(_success(res))


def _handle_tool_writing_discussion_from_verdicts(name, arguments, root):
    from research_os.tools.actions.synthesis.discussion_from_verdicts import (
        emit_discussion_paragraphs,
    )
    return _text(emit_discussion_paragraphs(root))


def _handle_tool_discussion_coverage_audit(name, arguments, root):
    from research_os.tools.actions.synthesis.discussion_from_verdicts import (
        discussion_coverage_audit,
    )
    from research_os.project_ops import log_override, validate_override_rationale

    override_requested = bool(arguments.get("override_discussion_coverage", False))
    rationale = arguments.get("override_rationale")
    # Required whenever an override is requested — the bypass is logged +
    # applied regardless of quality_gate_policy (AG-11).
    if override_requested and (not rationale or not str(rationale).strip()):
        return _text(_error(
            "override_discussion_coverage=true requires override_rationale "
            "(a bypass is logged + applied regardless of quality_gate_policy)."
        ))
    if override_requested and rationale:
        thin = validate_override_rationale(rationale)
        if thin is not None:
            return _text(thin)
    res = discussion_coverage_audit(root)
    if res.get("blockers") and override_requested:
        log_override(
            root,
            tool="tool_discussion_coverage_audit",
            gate="discussion_coverage",
            rationale=rationale or "",
            extra={"uncovered_count": res.get("uncovered_count", 0)},
        )
        res["override_applied"] = True
        res["status"] = "success"
    return _text(res)


def _handle_tool_figure_palette(name, arguments, root):
    from research_os.tools.actions.viz.figures import palette_for

    kind = arguments.get("kind", "qualitative")
    n = int(arguments.get("n", 8))
    return _text(_success({
        "kind": kind,
        "n": n,
        "colors": palette_for(kind, n),
    }))


HANDLERS = {
    "tool_synthesis_scaffold": _handle_tool_synthesis_scaffold,
    "tool_typst_compile": _handle_tool_typst_compile,
}
