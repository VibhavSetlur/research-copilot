"""Tests for the progressive-disclosure MCP tool surface (context-bloat fix).

The MCP ``list_tools()`` handshake must advertise only a lean CORE surface
by default, NOT all ~160 tools — that flood is the single biggest per-session
context cost. Hidden tools stay fully callable via ``call_tool`` (the
dispatcher resolves against the full ``_HANDLERS`` registry, not the
advertised list), so progressive disclosure is safe.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.server import (
    TOOL_DEFINITIONS,
    _CORE_SURFACE,
    _handle_tool_call,
    resolve_surface_mode,
    select_visible_tools,
)


@pytest.fixture(autouse=True)
def _clean_surface_env(monkeypatch):
    """Each test controls RESEARCH_OS_TOOL_SURFACE explicitly."""
    monkeypatch.delenv("RESEARCH_OS_TOOL_SURFACE", raising=False)
    yield


# ── surface resolution ────────────────────────────────────────────────


def test_default_surface_is_core(monkeypatch):
    monkeypatch.delenv("RESEARCH_OS_TOOL_SURFACE", raising=False)
    assert resolve_surface_mode() == "core"


def test_unknown_surface_falls_back_to_core(monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_TOOL_SURFACE", "nonsense")
    assert resolve_surface_mode() == "core"


def test_surface_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_TOOL_SURFACE", "FULL")
    assert resolve_surface_mode() == "full"


# ── visible-tool selection ────────────────────────────────────────────


def test_core_surface_is_lean(monkeypatch):
    """Default surface must be a small fraction of the full catalog."""
    monkeypatch.delenv("RESEARCH_OS_TOOL_SURFACE", raising=False)
    visible = select_visible_tools(TOOL_DEFINITIONS, Path("/tmp"))
    # Lean: well under half the catalog (the bug was advertising ALL of it).
    assert len(visible) < len(TOOL_DEFINITIONS) / 2
    assert len(visible) <= len(_CORE_SURFACE)


def test_full_surface_returns_everything(monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_TOOL_SURFACE", "full")
    visible = select_visible_tools(TOOL_DEFINITIONS, Path("/tmp"))
    assert set(visible) == set(TOOL_DEFINITIONS.keys())


def test_core_surface_includes_boot_ritual_and_discovery(monkeypatch):
    """The AI MUST be able to orient, route, and DISCOVER from the core set."""
    monkeypatch.delenv("RESEARCH_OS_TOOL_SURFACE", raising=False)
    visible = set(select_visible_tools(TOOL_DEFINITIONS, Path("/tmp")))
    required = {
        "sys_boot", "tool_route", "sys_protocol_get", "sys_active_tools",
        "sys_file_read", "sys_file_write", "sys_state_get",
    }
    missing = required - visible
    assert not missing, f"core surface missing discovery/boot tools: {missing}"


def test_every_core_tool_exists_in_catalog():
    """A typo in _CORE_SURFACE would silently shrink the handshake."""
    missing = _CORE_SURFACE - set(TOOL_DEFINITIONS.keys())
    assert not missing, f"_CORE_SURFACE names not in TOOL_DEFINITIONS: {missing}"


def test_mode_surface_is_between_core_and_full(monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_TOOL_SURFACE", "mode")
    visible = select_visible_tools(TOOL_DEFINITIONS, Path("/tmp"))
    # Mode scoping is broader than core, no broader than full.
    assert len(visible) >= len(_CORE_SURFACE)
    assert len(visible) <= len(TOOL_DEFINITIONS)
    # Core bootstrap tools survive mode scoping.
    assert _CORE_SURFACE <= set(visible)


def test_visible_order_follows_catalog(monkeypatch):
    """Returned names preserve TOOL_DEFINITIONS order for a stable handshake."""
    monkeypatch.delenv("RESEARCH_OS_TOOL_SURFACE", raising=False)
    visible = select_visible_tools(TOOL_DEFINITIONS, Path("/tmp"))
    catalog_order = [n for n in TOOL_DEFINITIONS if n in set(visible)]
    assert visible == catalog_order


# ── the safety invariant: hidden tools stay callable ──────────────────


def test_hidden_tool_still_dispatches(monkeypatch, tmp_path):
    """A tool absent from the core surface must still be callable by name.

    This is what makes progressive disclosure safe — call_tool resolves
    against _HANDLERS, not against the advertised list_tools() set.
    """
    monkeypatch.delenv("RESEARCH_OS_TOOL_SURFACE", raising=False)
    visible = set(select_visible_tools(TOOL_DEFINITIONS, tmp_path))
    # tool_protocols_list is a real, side-effect-free tool that is NOT core.
    assert "tool_protocols_list" not in visible
    res = _handle_tool_call("tool_protocols_list", {}, tmp_path)
    payload = json.loads(res[0].text)
    assert payload.get("status") == "success"
