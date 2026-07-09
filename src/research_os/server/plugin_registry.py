"""Composite tool loader foundation — built-in 45 + (future) external plugins.

In this release the plugin list is always empty; the dispatch layer calls
resolve_tool() as a fallback before the unknown-tool error path so external
MCP tools declared in ~/.research-os/plugins.yaml can be wired in a later
release without touching dispatch again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PluginManifest:
    name: str
    tools: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class HandlerSpec:
    name: str
    handler: Any


class PluginRegistry:
    """Discover + resolve external plugin tools. Empty by default in this release."""

    def discover(self) -> list[PluginManifest]:
        """Read ~/.research-os/plugins.yaml for external tool declarations.

        Returns [] in this release (no external plugins wired yet)."""
        return []

    def resolve_tool(self, name: str) -> Optional[HandlerSpec]:
        """Return a HandlerSpec for a plugin tool by name, or None if unknown."""
        return None


_PLUGIN_REGISTRY = PluginRegistry()


def plugin_registry() -> PluginRegistry:
    return _PLUGIN_REGISTRY
