"""Gate request schema — serializable human-in-the-loop approval request."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GateRequest(BaseModel):
    """A serializable human-in-the-loop gate request and its resolution."""

    id: str
    gate_id: str
    prompt: str
    options: list[str] = Field(default_factory=list)
    context: dict = Field(default_factory=dict)
    blocking: bool = True
    response: str | None = None
    resolved: bool = False
    created_at: str | None = None
