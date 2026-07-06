"""Aggregated TOOL_DEFINITIONS — the consolidated core tool surface."""
from __future__ import annotations

from typing import Any

from .consolidated import CONSOLIDATED_TOOL_DEFINITIONS

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {**CONSOLIDATED_TOOL_DEFINITIONS}
