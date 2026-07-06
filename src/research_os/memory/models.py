"""Pydantic v2 data models for the Research-OS memory subsystem.

This module is pure data — no I/O, no disk access, no imports from other
research_os sub-packages.  Every model uses ``extra="allow"`` so that
callers can attach arbitrary metadata without triggering validation errors.

Public classes
--------------
EvidenceLink  – a typed pointer from a hypothesis to a piece of evidence.
Hypothesis    – a falsifiable scientific claim with status tracking.
MemoryRecord  – a durable memory entry (analysis, decision, lesson, …).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def _new_id() -> str:
    """Return a fresh random hex UUID (no hyphens)."""
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class EvidenceLink(BaseModel):
    """A typed pointer from a :class:`Hypothesis` to a piece of evidence.

    Attributes
    ----------
    kind:
        Broad category of the evidence source.
    ref:
        Opaque pointer — file path, run ID, DOI, tool output key, etc.
    summary:
        Human-readable one-liner describing what this evidence shows.
    strength:
        Qualitative confidence in how strongly this item supports or
        refutes the hypothesis.
    """

    model_config = ConfigDict(extra="allow")

    kind: Literal["analysis", "figure", "run", "citation"]
    ref: str  # Pointer — file path, run ID, DOI, …
    summary: str = ""
    strength: Literal["weak", "moderate", "strong"] = "moderate"


class Hypothesis(BaseModel):
    """A falsifiable scientific claim with provenance and status tracking.

    Hypotheses live in the per-project hypothesis ledger.  Each one
    carries forward-links to the evidence that supports or refutes it so
    that the ledger remains self-contained even without the full memory
    store.

    Attributes
    ----------
    id:
        Stable random hex identifier, assigned at construction.
    statement:
        Plain-English statement of the hypothesis (the claim itself).
    status:
        Lifecycle state — updated as experiments accumulate evidence.
    evidence_for:
        Evidence items that support the hypothesis.
    evidence_against:
        Evidence items that refute or weaken the hypothesis.
    created_at / updated_at:
        UTC timestamps; callers should refresh ``updated_at`` whenever
        ``status`` or evidence lists change.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=_new_id)
    statement: str
    status: Literal[
        "proposed", "tested", "supported", "refuted", "inconclusive"
    ] = "proposed"
    evidence_for: list[EvidenceLink] = Field(default_factory=list)
    evidence_against: list[EvidenceLink] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class MemoryRecord(BaseModel):
    """A durable memory entry stored in the project's semantic memory store.

    Each record captures a single atomic piece of project knowledge —
    an analysis result, a decision, a lesson learned, etc.  The
    ``embedding`` field is intentionally optional so that records can be
    created before a vector index is available (the retriever fills it in
    lazily).

    Attributes
    ----------
    id:
        Stable random hex identifier.
    kind:
        Semantic category, used for filtering and routing.
    content:
        Full text of the memory entry.
    summary:
        Short pointer-architecture digest; used in search ranking and
        as the primary display string.
    tags:
        Free-form labels for grouping / filtering.
    project:
        Owning project slug — must match the project directory name.
    protocol:
        Protocol that produced this record, if any.
    run_id:
        Daemon run ID for provenance (links back to ``RunRecord``).
    artifact_keys:
        Keys of output artifacts associated with this record (e.g.
        file paths relative to the project outputs directory).
    timestamp:
        UTC creation time.
    embedding:
        Dense vector representation; populated by the retriever.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=_new_id)
    kind: Literal["analysis", "decision", "hypothesis", "lesson", "result", "error"]
    content: str
    summary: str = ""  # pointer-architecture placeholder fidelity
    tags: list[str] = Field(default_factory=list)
    project: str
    protocol: str | None = None
    run_id: str | None = None  # links to daemon run (provenance)
    artifact_keys: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_now)
    embedding: list[float] | None = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def searchable_text(self) -> str:
        """Return a single string used by keyword search.

        Concatenates ``summary`` and ``content`` so that both the
        condensed pointer and the full entry are indexed together.
        """
        return f"{self.summary}\n{self.content}"
