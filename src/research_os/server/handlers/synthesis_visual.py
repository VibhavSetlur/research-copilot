"""Handlers — synthesis_visual sub-domain.

Empty post-v2.3.0. The dashboard/slides/poster generators were removed
in favour of AI-direct authoring (the AI writes synthesis/dashboard.html,
synthesis/slides.typ, synthesis/poster.typ directly following the matching
synthesis protocol, then validates with tool_synthesis_check and renders
PDFs via tool_typst_compile).

tool_figure_palette moved to synthesis_writing.HANDLERS. Kept here for
import compatibility — any future visual-domain handlers can land in
this module.
"""
from __future__ import annotations

# ruff: noqa: F403, F405  # legacy handler runtime star-import compatibility
from .._handlers_runtime import *  # noqa: F401,F403

__all__: list[str] = []


HANDLERS: dict[str, object] = {}
