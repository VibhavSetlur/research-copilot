"""Tests for mode-scoped tool listing (context-bloat fix).

list_tools_flat(..., mode=) restricts the surface to CORE categories +
the active workspace mode's working categories. tool_tools_list exposes
this via a `mode` param ('auto' resolves from workspace config).
"""
from __future__ import annotations

import json
import re

from research_os.server import _ALIASES, _DEPRECATED_ALIASES, TOOL_DEFINITIONS
from research_os.tools.actions.listers import (
    VALID_LISTING_MODES,
    _categories_for_mode,
    list_tools_flat,
)


def _names(entries):
    return {e["name"] for e in entries}


def test_mode_none_is_backcompat_full_surface():
    """mode=None must return exactly the unscoped surface."""
    full = list_tools_flat(TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES)
    explicit_none = list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES, mode=None,
    )
    assert [e["name"] for e in full] == [e["name"] for e in explicit_none]


def test_mode_reduces_surface():
    full = list_tools_flat(TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES)
    for mode in VALID_LISTING_MODES:
        scoped = list_tools_flat(
            TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES, mode=mode,
        )
        # Scoped surface never exceeds the full surface (with a lean 45-tool
        # catalog a mode may retain every tool, so this is <=, not <).
        assert len(scoped) <= len(full), f"mode={mode} grew the surface"
        # Scoped surface is a subset of the full surface.
        assert _names(scoped) <= _names(full)


def test_core_tools_present_in_every_mode():
    """Routing / file / state plumbing + gradient on-ramps in all modes."""
    core_expected = {
        "tool_route", "sys_boot", "sys_protocol_get", "sys_file_read",
        "sys_state_get",
    }
    for mode in VALID_LISTING_MODES:
        scoped = _names(list_tools_flat(
            TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES, mode=mode,
        ))
        missing = core_expected - scoped
        assert not missing, f"mode={mode} missing core tools {missing}"


def test_tool_build_mode_surfaces_build_tools():
    scoped = _names(list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES, mode="tool_build",
    ))
    assert "tool_git" in scoped
    assert "tool_build" in scoped
    # scope='tool' audit gates ride in the audit category.
    assert "tool_audit" in scoped


def test_analysis_mode_surfaces_analysis_tools():
    scoped = _names(list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES, mode="analysis",
    ))
    assert "tool_data" in scoped
    assert "tool_synthesis_scaffold" in scoped


def test_unknown_mode_defaults_to_analysis_categories():
    """An unknown mode must not crash — it behaves like analysis."""
    bogus = _categories_for_mode("nonsense")
    analysis = _categories_for_mode("analysis")
    assert bogus == analysis


# ---------------------------------------------------------------------------
# tool_tools_list handler — mode param
# ---------------------------------------------------------------------------


def test_handler_mode_explicit(tmp_path):
    from research_os.server import _handle_tool_tools_list

    res = _handle_tool_tools_list(
        "tool_tools_list", {"mode": "tool_build"}, tmp_path,
    )
    payload = json.loads(res[0].text)
    assert payload["status"] == "success"
    assert payload["data"]["filters"]["mode"] == "tool_build"
    names = {e["name"] for e in payload["data"]["tools"]}
    assert "tool_git" in names


def test_handler_mode_auto_resolves_from_config(tmp_path):
    from research_os.project_ops import scaffold_minimal_workspace
    from research_os.server import _handle_tool_tools_list

    scaffold_minimal_workspace(tmp_path, "Demo")
    # Force tool_build mode in the config workspace block.
    cfg = tmp_path / "inputs" / "researcher_config.yaml"
    txt = cfg.read_text()
    if re.search(r"^\s*mode:\s*", txt, flags=re.MULTILINE):
        txt = re.sub(r"(\bmode:\s*)\S+", r"\1tool_build", txt, count=1)
    else:
        txt += "\nworkspace:\n  mode: tool_build\n"
    cfg.write_text(txt)

    res = _handle_tool_tools_list("tool_tools_list", {"mode": "auto"}, tmp_path)
    payload = json.loads(res[0].text)
    assert payload["status"] == "success"
    assert payload["data"]["filters"]["mode"] == "tool_build"


def test_handler_mode_omitted_is_full(tmp_path):
    from research_os.server import _handle_tool_tools_list

    res = _handle_tool_tools_list("tool_tools_list", {}, tmp_path)
    payload = json.loads(res[0].text)
    assert payload["status"] == "success"
    assert payload["data"]["filters"]["mode"] is None


def test_handler_bad_mode_errors(tmp_path):
    from research_os.server import _handle_tool_tools_list

    res = _handle_tool_tools_list(
        "tool_tools_list", {"mode": "nonsense"}, tmp_path,
    )
    payload = json.loads(res[0].text)
    assert payload["status"] == "error"
