"""Memory schema — evidence links, hypotheses, and generic memory records."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceLink(BaseModel):
    """A typed link between a source and a target with a relation and weight."""

    id: str
    source: str
    target: str
    relation: str = "supports"
    weight: float | None = None


class Hypothesis(BaseModel):
    """A research hypothesis with status, confidence, and supporting evidence."""

    id: str
    statement: str
    status: str = "open"
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)


class MemoryRecord(BaseModel):
    """A generic tagged memory record."""

    id: str
    kind: str
    content: str
    tags: list[str] = Field(default_factory=list)
    created_at: str | None = None
    metadata: dict = Field(default_factory=dict)
