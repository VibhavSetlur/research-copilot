"""Workspace mode enum — the six operating modes of a research workspace."""

from __future__ import annotations

from enum import Enum


class Mode(str, Enum):
    """Research workspace operating modes."""

    EXPLORE = "explore"
    BUILD = "build"
    ANALYZE = "analyze"
    WRITE = "write"
    REVIEW = "review"
    PRESENT = "present"
