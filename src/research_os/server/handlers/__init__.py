"""Aggregated handlers — merges every sub-module."""
from __future__ import annotations


from .meta_routing import HANDLERS as _META_ROUTING_HANDLERS  # noqa: E501
from .meta_workspace import HANDLERS as _META_WORKSPACE_HANDLERS  # noqa: E501
from .meta_sys import HANDLERS as _META_SYS_HANDLERS  # noqa: E501
from .meta_help import HANDLERS as _META_HELP_HANDLERS  # noqa: E501
from .research_search import HANDLERS as _RESEARCH_SEARCH_HANDLERS  # noqa: E501
from .research_exec import HANDLERS as _RESEARCH_EXEC_HANDLERS  # noqa: E501
from .audit_core import HANDLERS as _AUDIT_CORE_HANDLERS  # noqa: E501
from .audit_gates import HANDLERS as _AUDIT_GATES_HANDLERS  # noqa: E501
from .synthesis_writing import HANDLERS as _SYNTHESIS_WRITING_HANDLERS  # noqa: E501
from .synthesis_visual import HANDLERS as _SYNTHESIS_VISUAL_HANDLERS  # noqa: E501
from .synthesis_reviewer import HANDLERS as _SYNTHESIS_REVIEWER_HANDLERS  # noqa: E501
from .methodology import HANDLERS as _METHODOLOGY_HANDLERS  # noqa: E501
from .grounding import HANDLERS as _GROUNDING_HANDLERS  # noqa: E501
from .build import HANDLERS as _BUILD_HANDLERS  # noqa: E501
from .gradient import HANDLERS as _GRADIENT_HANDLERS  # noqa: E501
from .memory import HANDLERS as _MEMORY_HANDLERS  # noqa: E501

_HANDLERS: dict = {
    **_META_ROUTING_HANDLERS,
    **_META_WORKSPACE_HANDLERS,
    **_META_SYS_HANDLERS,
    **_META_HELP_HANDLERS,
    **_RESEARCH_SEARCH_HANDLERS,
    **_RESEARCH_EXEC_HANDLERS,
    **_AUDIT_CORE_HANDLERS,
    **_AUDIT_GATES_HANDLERS,
    **_SYNTHESIS_WRITING_HANDLERS,
    **_SYNTHESIS_VISUAL_HANDLERS,
    **_SYNTHESIS_REVIEWER_HANDLERS,
    **_METHODOLOGY_HANDLERS,
    **_GROUNDING_HANDLERS,
    **_BUILD_HANDLERS,
    **_GRADIENT_HANDLERS,
    **_MEMORY_HANDLERS,
}
