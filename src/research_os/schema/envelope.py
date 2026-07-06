"""Transport envelope schema — tool calls, results, routing, and message wrapper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """A request to invoke a tool with arguments."""

    tool: str
    args: dict = Field(default_factory=dict)
    call_id: str | None = None


class ToolResult(BaseModel):
    """The result of a tool invocation."""

    call_id: str | None = None
    ok: bool = True
    output: Any = None
    error: str | None = None


class RoutingDecision(BaseModel):
    """A routing decision selecting protocol, tier, and mode."""

    protocol_id: str | None = None
    tier: str | None = None
    mode: str | None = None
    rationale: str = ""
    confidence: float | None = None


class Envelope(BaseModel):
    """A message/transport wrapper carrying tool calls, results, and routing."""

    id: str
    kind: str
    payload: dict = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    results: list[ToolResult] = Field(default_factory=list)
    routing: RoutingDecision | None = None
    metadata: dict = Field(default_factory=dict)
