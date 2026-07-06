"""Protocol schema — the central doctrine model for a research workflow protocol."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .tiers import Tier


class ScopeTags(BaseModel):
    """Flexible tagging model scoping a protocol to domains, phases, and tools."""

    model_config = ConfigDict(extra="allow")

    domain: list[str] = Field(default_factory=list)
    phase: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class PreconditionCheck(BaseModel):
    """A single precondition that must hold before a protocol may run."""

    id: str
    description: str
    check: str | None = None
    required: bool = True


class Gate(BaseModel):
    """An enforcement gate guarding progression through a protocol."""

    id: str
    name: str
    description: str
    blocking: bool = True


class Step(BaseModel):
    """A single executable step within a protocol."""

    id: str
    name: str
    description: str
    substeps: list[str] = Field(default_factory=list)


class Protocol(BaseModel):
    """The central protocol model — free-prose doctrine preserved verbatim."""

    id: str
    name: str
    version: str
    schema_version: Literal["3.0", "2.0"] = "3.0"
    tier: str
    intent_class: str | None = None
    sub_intent: str | None = None
    triggers: list[str] = Field(default_factory=list)
    summary: str = ""
    shortcut_tool: str | None = None
    token_estimate: int | None = None
    decomposition: str = ""
    modes: list[str] = Field(default_factory=list)
    scope_tags: ScopeTags = Field(default_factory=ScopeTags)
    see_also: list[str] = Field(default_factory=list)
    description: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    requires: list[PreconditionCheck] = Field(default_factory=list)
    enforcement: list[Gate] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    on_failure: str = ""
    next_protocol: str | None = None

    @field_validator("tier")
    @classmethod
    def _validate_tier(cls, v: str) -> str:
        """Accept any Tier value or name case-insensitively; store lowercase value."""
        candidate = str(v).strip()
        for member in Tier:
            if candidate.lower() == member.value.lower() or candidate.lower() == member.name.lower():
                return member.value
        valid = ", ".join(m.value for m in Tier)
        raise ValueError(f"invalid tier {v!r}; must be one of: {valid}")
