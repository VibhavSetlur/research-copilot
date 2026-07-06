"""Workflow tier enum — the seven canonical stages of a research protocol."""

from __future__ import annotations

from enum import Enum


class Tier(str, Enum):
    """Canonical research workflow tiers, ordered from intake to finalize."""

    INTAKE = "intake"
    PLAN = "plan"
    EXECUTE = "execute"
    GROUND = "ground"
    SYNTHESIZE = "synthesize"
    REVIEW = "review"
    FINALIZE = "finalize"
