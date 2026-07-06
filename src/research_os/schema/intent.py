"""Intent-class enum — coarse research intent categories for routing."""

from __future__ import annotations

from enum import Enum


class IntentClass(str, Enum):
    """Coarse categories of research intent used for protocol routing."""

    LITERATURE = "literature"
    EXPLORATION = "exploration"
    ANALYSIS = "analysis"
    SYNTHESIS = "synthesis"
    BUILD = "build"
    AUDIT = "audit"
    GUIDANCE = "guidance"
