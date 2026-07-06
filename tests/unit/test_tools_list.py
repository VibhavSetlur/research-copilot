"""Tests for the v2 flat tool lister + tool_tools_list MCP tool."""

from __future__ import annotations

from research_os.server import _ALIASES, _DEPRECATED_ALIASES, TOOL_DEFINITIONS
from research_os.tools.actions.listers import list_tools_flat


def test_list_tools_flat_default_shape():
    out = list_tools_flat(TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES)
    assert isinstance(out, list)
    assert len(out) >= 45
    required = {
        "name", "scope", "summary_first_line",
        "input_schema_required_fields", "deprecated", "alias_of",
    }
    for entry in out:
        missing = required - set(entry.keys())
        assert not missing, f"tool {entry.get('name')} missing keys {missing}"
        assert isinstance(entry["input_schema_required_fields"], list)
        assert isinstance(entry["deprecated"], bool)


def test_list_tools_flat_core_tool_present():
    out = list_tools_flat(TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES)
    routes = [e for e in out if e["name"] == "tool_route"]
    assert len(routes) == 1
    entry = routes[0]
    assert entry["scope"] == "core"
    assert "prompt" in entry["input_schema_required_fields"]
    assert entry["deprecated"] is False
    assert entry["alias_of"] is None


def test_list_tools_flat_scope_filter_core():
    out = list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES, scope="core",
    )
    assert out
    for e in out:
        assert e["scope"] == "core"


def test_list_tools_flat_include_deprecated_surfaces_aliases():
    """tool_web_scrape is a deprecated alias of tool_search (consolidation)."""
    plain = list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES,
        include_deprecated=False,
    )
    plain_names = {e["name"] for e in plain}
    assert "tool_web_scrape" not in plain_names

    with_deps = list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES,
        include_deprecated=True,
    )
    dep_entry = next(
        (e for e in with_deps if e["name"] == "tool_web_scrape"), None,
    )
    assert dep_entry is not None
    assert dep_entry["deprecated"] is True
    assert dep_entry["alias_of"] == "tool_search"


def test_list_tools_flat_match_substring():
    out = list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES,
        match_substring="route",
    )
    assert out
    # Filter applies to name OR summary; needle must appear in at least one.
    for e in out:
        hay = (e["name"] + " " + e["summary_first_line"]).lower()
        assert "route" in hay


def test_list_tools_flat_match_substring_case_insensitive():
    upper = list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES,
        match_substring="ROUTE",
    )
    lower = list_tools_flat(
        TOOL_DEFINITIONS, _ALIASES, _DEPRECATED_ALIASES,
        match_substring="route",
    )
    assert [e["name"] for e in upper] == [e["name"] for e in lower]


def test_tool_tools_list_handler(tmp_path):
    from research_os.server import _handle_tool_tools_list

    res = _handle_tool_tools_list(
        "tool_tools_list",
        {"scope": "core", "match_substring": "route"},
        tmp_path,
    )
    import json
    payload = json.loads(res[0].text)
    assert payload["status"] == "success"
    data = payload["data"]
    assert data["count"] == len(data["tools"])
    assert data["filters"]["scope"] == "core"
    assert all(e["scope"] == "core" for e in data["tools"])
    # tool_route must be in the substring-filtered output.
    names = {e["name"] for e in data["tools"]}
    assert "tool_route" in names


def test_tool_tools_list_default_all_scope(tmp_path):
    from research_os.server import _handle_tool_tools_list

    res = _handle_tool_tools_list("tool_tools_list", {}, tmp_path)
    import json
    payload = json.loads(res[0].text)
    assert payload["status"] == "success"
    assert payload["data"]["filters"]["scope"] == "all"
    assert payload["data"]["filters"]["include_deprecated"] is False
