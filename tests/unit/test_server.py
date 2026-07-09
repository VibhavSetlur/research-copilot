"""MCP server unit tests — envelopes, rate limiter, tool definitions."""

import json

from research_os.server import (
    TOOL_DEFINITIONS,
    RateLimiter,
    _error,
    _log_search,
    _resolve_tool_name,
    _short_for_list,
    _success,
    _text,
)


def test_tool_definitions_nonempty():
    assert isinstance(TOOL_DEFINITIONS, dict)
    assert len(TOOL_DEFINITIONS) >= 40


def test_tool_definitions_have_description_and_schema():
    for name, schema in TOOL_DEFINITIONS.items():
        assert "description" in schema, name
        assert "inputSchema" in schema, name
        inp = schema["inputSchema"]
        assert inp.get("type") == "object", name
        if "required" in inp:
            for r in inp["required"]:
                assert r in inp.get("properties", {}), f"{name} required {r}"


def test_rate_limiter():
    limiter = RateLimiter(max_calls=2, window_seconds=60)
    assert limiter.is_allowed("alice")
    assert limiter.is_allowed("alice")
    assert not limiter.is_allowed("alice")
    assert limiter.is_allowed("bob")


def test_envelope_helpers():
    # v2.1.0 envelope: backwards-compatible — `data` still present and
    # equal to `payload`. New fields added with sane defaults.
    s = _success({"x": 1})
    assert s["status"] == "success"
    assert s["payload"] == {"x": 1}
    assert s["data"] == {"x": 1}
    assert s["data"] is s["payload"]
    assert s["audit_findings"] == []
    assert s["next_recommended_call"] is None
    assert s["tier_transition"] is None
    # tokens_estimate is now a heuristic (`len(json.dumps(payload))//4`)
    # rather than a hardcoded 0. For a tiny payload like {"x": 1} it's
    # > 0 but bounded.
    assert isinstance(s["tokens_estimate"], int)
    assert s["tokens_estimate"] >= 0
    assert "ro_version" in s
    assert s["ro_version"].count(".") >= 2

    s_empty = _success()
    assert s_empty["status"] == "success"
    assert s_empty["payload"] == {}
    assert s_empty["data"] == {}

    err = _error("oops")
    assert err["status"] == "error"
    assert err["error"] == "oops"
    assert err["payload"]["what"] == "oops"
    assert err["audit_findings"] == []

    err2 = _error(
        what="path missing",
        why="protocol was renamed",
        next_action="run sys_protocol_list",
    )
    assert err2["status"] == "error"
    assert "path missing" in err2["error"]
    assert "renamed" in err2["error"]
    assert err2["payload"]["next_action"] == "run sys_protocol_list"
    assert err2["next_recommended_call"] == "run sys_protocol_list"


def test_text_helper():
    out = _text("hello")
    assert len(out) == 1
    assert out[0].text == "hello"

    payload = {"k": "v"}
    out = _text(payload)
    assert json.loads(out[0].text) == payload


def test_log_search_creates_jsonl(tmp_path):
    # tool_search is the consolidated entry point; tool_search_web was the
    # v1.6.1 alias and was hard-removed in phase-14a.
    _log_search(tmp_path, "tool_search", "q1", 3)
    _log_search(tmp_path, "tool_search", "q2", 5)
    log = tmp_path / "workspace" / "logs" / "searches.log"
    assert log.exists()
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["tool"] == "tool_search"
    assert first["results_count"] == 3


def test_dispatcher_resolves_dots_to_underscores():
    assert _resolve_tool_name("sys.state.get") == "sys_state_get"
    # tool.search → underscore → tool_search (the unified search dispatcher).
    # tool.search.web no longer exists — its alias was removed in phase-14a.
    assert _resolve_tool_name("tool.search") == "tool_search"


def test_dispatcher_resolves_legacy_aliases():
    # v2.0.0: tool_audit_statistical_power resolves to the consolidated
    # tool_audit entry point (was tool_audit_power before the audit-family
    # collapse). Param injection sets scope=step / dimension=power so the
    # legacy behaviour is preserved end-to-end.
    assert _resolve_tool_name("tool_audit_statistical_power") == "tool_audit"
    assert _resolve_tool_name("sys_state_summary") == "sys_state_get"
    # tool_log_decision used to chain through mem_decision_log → mem_log;
    # mem_decision_log was hard-removed in phase-14a so tool_log_decision now
    # resolves directly to mem_log (with kind='decision' injected).
    assert _resolve_tool_name("tool_log_decision") == "mem_log"
    assert _resolve_tool_name("view_workspace_tree") == "sys_workspace_tree"


def test_dispatcher_passes_underscore_names_through():
    assert _resolve_tool_name("sys_state_get") == "sys_state_get"


def test_workspace_mode_is_live_registry_tool():
    import research_os.server as s

    assert "sys_workspace_mode" in s.TOOL_DEFINITIONS
    assert "sys_workspace_mode" in s._HANDLERS


def test_routing_tools_registered():
    """Core routing/planning/discovery tools must be wired.

    Discovery folded into sys_active_tools; plan sub-ops flow through
    tool_plan(operation=...).
    """
    for name in (
        "sys_boot",
        "tool_route",
        "tool_plan",
        "sys_active_tools",
    ):
        assert name in TOOL_DEFINITIONS, f"{name} missing from TOOL_DEFINITIONS"


def test_short_for_list_uses_short_field_when_present():
    schema = {
        "short": "Tight one-liner.",
        "description": "Long description that goes on and on and on...",
    }
    assert _short_for_list(schema) == "Tight one-liner."


def test_short_for_list_falls_back_to_first_sentence():
    schema = {
        "description": "First sentence here. Second sentence with more detail.",
    }
    short = _short_for_list(schema)
    assert short.startswith("First sentence here")
    assert len(short) <= 160


def test_short_for_list_caps_at_160_chars():
    schema = {"description": "x" * 500}
    assert len(_short_for_list(schema)) <= 160
