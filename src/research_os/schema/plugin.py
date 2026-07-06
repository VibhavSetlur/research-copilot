"""Plugin manifest schema — declarative metadata for a Research-OS plugin."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PluginManifest(BaseModel):
    """Declarative manifest describing a plugin's identity and capabilities."""

    id: str
    name: str
    version: str
    entrypoint: str | None = None
    provides: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    config_schema: dict = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict = Field(default_factory=dict)
