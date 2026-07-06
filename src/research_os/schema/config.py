"""Researcher configuration schema — simplified per-researcher settings."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResearcherConfig(BaseModel):
    """Simplified configuration for an individual researcher's workspace."""

    name: str = ""
    domain: str = ""
    default_mode: str | None = None
    default_tier: str | None = None
    output_dir: str = "output"
    enable_gates: bool = True
    plugins: list[str] = Field(default_factory=list)
    token_budget: int | None = None
    verbose: bool = False
    metadata: dict = Field(default_factory=dict)
