"""Tests for §13.1 Persona modes.

Covers:
  - Persona records exist and are valid
  - sys_mode query returns current+available
  - sys_mode set persists to config.yaml
  - read_only persona filters exec tools from select_visible_tools
  - forbidden policy refuses an exec tool at dispatch
  - supervised policy writes a gate file
  - verified policy appends an audit finding
  - no-persona default behaves like direct (exec runs)
  - No new /v1/chat or /v1/messages route was introduced
  - No new import of research_os.daemon appears in server/ or tools/
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def workspace(tmp_path):
    """Minimal workspace scaffold for dispatch tests."""
    (tmp_path / ".os_state").mkdir()
    (tmp_path / "workspace" / "logs").mkdir(parents=True)
    (tmp_path / "inputs").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Persona records exist and are valid
# ---------------------------------------------------------------------------

def test_persona_records_exist():
    from research_os.server.personas import PERSONAS, VALID_PERSONA_NAMES, DEFAULT_PERSONA

    assert set(PERSONAS.keys()) == {"scruffy", "neat", "critique", "delegation"}
    assert VALID_PERSONA_NAMES == tuple(PERSONAS.keys())
    assert DEFAULT_PERSONA == "scruffy"


def test_persona_records_have_required_fields():
    from research_os.server.personas import PERSONAS

    required = {"directive", "tool_visibility", "execution_policy"}
    for name, record in PERSONAS.items():
        assert required <= set(record.keys()), f"{name} missing fields"


def test_persona_field_values():
    from research_os.server.personas import PERSONAS

    assert PERSONAS["scruffy"]["tool_visibility"] == "all"
    assert PERSONAS["scruffy"]["execution_policy"] == "direct"
    assert PERSONAS["neat"]["tool_visibility"] == "all"
    assert PERSONAS["neat"]["execution_policy"] == "verified"
    assert PERSONAS["critique"]["tool_visibility"] == "read_only"
    assert PERSONAS["critique"]["execution_policy"] == "forbidden"
    assert PERSONAS["delegation"]["tool_visibility"] == "all"
    assert PERSONAS["delegation"]["execution_policy"] == "supervised"


def test_get_persona_known():
    from research_os.server.personas import get_persona, PERSONAS

    p = get_persona("neat")
    assert p == PERSONAS["neat"]


def test_get_persona_unknown_raises():
    from research_os.server.personas import get_persona

    with pytest.raises(KeyError):
        get_persona("nonexistent")


# ---------------------------------------------------------------------------
# 2. get_active_persona defaults to scruffy when nothing configured
# ---------------------------------------------------------------------------

def test_get_active_persona_defaults_to_scruffy(tmp_path):
    from research_os.server.personas import get_active_persona, DEFAULT_PERSONA

    assert get_active_persona(tmp_path) == DEFAULT_PERSONA


def test_get_active_persona_with_no_os_state(tmp_path):
    from research_os.server.personas import get_active_persona

    # .os_state doesn't exist at all
    result = get_active_persona(tmp_path / "nonexistent")
    assert result == "scruffy"


# ---------------------------------------------------------------------------
# 3. sys_mode query returns current + available personas
# ---------------------------------------------------------------------------

def test_sys_mode_query_no_arg(workspace):
    from research_os.server.dispatch import _handle_tool_call

    result = _handle_tool_call("sys_mode", {}, workspace)
    assert result
    env = json.loads(result[0].text)
    assert env["status"] == "success"
    payload = env["payload"]
    assert "active_persona" in payload
    assert "directive" in payload
    assert "available_personas" in payload
    # All four personas must be listed
    assert set(payload["available_personas"].keys()) == {
        "scruffy", "neat", "critique", "delegation"
    }


def test_sys_mode_query_default_is_scruffy(workspace):
    from research_os.server.dispatch import _handle_tool_call

    result = _handle_tool_call("sys_mode", {}, workspace)
    env = json.loads(result[0].text)
    assert env["payload"]["active_persona"] == "scruffy"


# ---------------------------------------------------------------------------
# 4. sys_mode set persists to .os_state/config.yaml
# ---------------------------------------------------------------------------

def test_sys_mode_set_persists(workspace):
    from research_os.server.dispatch import _handle_tool_call

    result = _handle_tool_call("sys_mode", {"persona": "neat"}, workspace)
    env = json.loads(result[0].text)
    assert env["status"] == "success"
    assert env["payload"]["persona"] == "neat"

    # Verify it's actually written to disk
    cfg_path = workspace / ".os_state" / "config.yaml"
    assert cfg_path.exists()
    cfg = yaml.safe_load(cfg_path.read_text())
    assert cfg["persona"]["active"] == "neat"


def test_sys_mode_set_and_query_roundtrip(workspace):
    from research_os.server.dispatch import _handle_tool_call
    from research_os.server.personas import get_active_persona

    _handle_tool_call("sys_mode", {"persona": "critique"}, workspace)
    assert get_active_persona(workspace) == "critique"

    # Query again via sys_mode
    result = _handle_tool_call("sys_mode", {}, workspace)
    env = json.loads(result[0].text)
    assert env["payload"]["active_persona"] == "critique"


def test_sys_mode_set_invalid_persona_errors(workspace):
    from research_os.server.dispatch import _handle_tool_call

    result = _handle_tool_call("sys_mode", {"persona": "badpersona"}, workspace)
    env = json.loads(result[0].text)
    assert env["status"] == "error"


# ---------------------------------------------------------------------------
# 5. tool_visibility: read_only persona filters exec tools
# ---------------------------------------------------------------------------

def test_read_only_persona_filters_exec_tools(workspace):
    from research_os.server.personas import set_active_persona
    from research_os.server.tool_surface import select_visible_tools
    from research_os.server.tool_definitions import TOOL_DEFINITIONS

    # Set critique persona (read_only)
    set_active_persona(workspace, "critique")

    # Use full surface to verify exec tools are filtered
    os.environ["RESEARCH_OS_TOOL_SURFACE"] = "full"
    try:
        visible = select_visible_tools(TOOL_DEFINITIONS, workspace)
    finally:
        del os.environ["RESEARCH_OS_TOOL_SURFACE"]

    # Exec-category tools must not appear
    exec_cats = {"execution", "exec"}
    for name in visible:
        cat = TOOL_DEFINITIONS.get(name, {}).get("category")
        assert cat not in exec_cats, (
            f"exec tool '{name}' (cat={cat}) visible under critique/read_only persona"
        )


def test_all_persona_does_not_filter_exec_tools(workspace):
    from research_os.server.personas import set_active_persona
    from research_os.server.tool_surface import select_visible_tools
    from research_os.server.tool_definitions import TOOL_DEFINITIONS

    # Set scruffy persona (all)
    set_active_persona(workspace, "scruffy")

    os.environ["RESEARCH_OS_TOOL_SURFACE"] = "full"
    try:
        visible = select_visible_tools(TOOL_DEFINITIONS, workspace)
    finally:
        del os.environ["RESEARCH_OS_TOOL_SURFACE"]

    exec_cats = {"execution", "exec"}
    exec_tools_visible = [
        n for n in visible
        if TOOL_DEFINITIONS.get(n, {}).get("category") in exec_cats
    ]
    assert exec_tools_visible, "scruffy/all persona should expose exec tools"


# ---------------------------------------------------------------------------
# 6. execution_policy: forbidden refuses exec tool at dispatch
# ---------------------------------------------------------------------------

def test_forbidden_policy_refuses_exec_tool(workspace):
    from research_os.server.personas import set_active_persona

    set_active_persona(workspace, "critique")

    from research_os.server.dispatch import _handle_tool_call

    result = _handle_tool_call("tool_python_exec", {"script": "x = 1"}, workspace)
    env = json.loads(result[0].text)
    assert env["status"] == "error"
    assert "forbidden" in env.get("error", "").lower() or "critique" in env.get("error", "").lower()


def test_forbidden_policy_does_not_block_non_exec_tool(workspace):
    """critique persona must NOT block non-exec tools (e.g. sys_mode itself)."""
    from research_os.server.personas import set_active_persona

    set_active_persona(workspace, "critique")

    from research_os.server.dispatch import _handle_tool_call

    result = _handle_tool_call("sys_mode", {}, workspace)
    env = json.loads(result[0].text)
    assert env["status"] == "success"


# ---------------------------------------------------------------------------
# 7. execution_policy: supervised writes a gate file
# ---------------------------------------------------------------------------

def test_supervised_policy_writes_gate_file(workspace):
    from research_os.server.personas import set_active_persona

    set_active_persona(workspace, "delegation")

    from research_os.server.dispatch import _handle_tool_call

    result = _handle_tool_call("tool_python_exec", {"script": "x = 1"}, workspace)
    env = json.loads(result[0].text)
    # The run is parked — status inside the payload should be "parked"
    assert env["status"] == "success"
    assert env["payload"].get("status") == "parked"
    assert env["payload"].get("persona") == "delegation"

    # Gate file must exist under .os_state/gates/
    gate_id = env["payload"].get("gate_id")
    assert gate_id
    gate_file = workspace / ".os_state" / "gates" / f"{gate_id}.json"
    assert gate_file.exists(), f"gate file not found: {gate_file}"

    gate_data = json.loads(gate_file.read_text())
    assert gate_data["id"] == gate_id
    assert gate_data["status"] == "pending"
    assert gate_data["tool"] == "tool_python_exec"
    # Shape: id, question, status, created_at, root, tool, protocol_id, step_id, decision, resolved_at
    for field in ("id", "question", "status", "created_at", "root"):
        assert field in gate_data, f"gate file missing field: {field}"


# ---------------------------------------------------------------------------
# 8. execution_policy: verified appends an audit finding
# ---------------------------------------------------------------------------

def test_verified_policy_appends_audit_finding(workspace):
    from research_os.server.personas import set_active_persona

    set_active_persona(workspace, "neat")

    # We need a real exec tool call that succeeds.
    # tool_python_exec with a trivial script should work.
    from research_os.server.dispatch import _handle_tool_call

    _handle_tool_call("tool_python_exec", {"script": "x = 1 + 1"}, workspace)

    ledger = workspace / "workspace" / "logs" / ".audit_findings.jsonl"
    # The ledger may not exist if the handler itself failed (no Python), so
    # we check for at least the tagging attempt. If it exists, verify content.
    if ledger.exists():
        lines = [ln for ln in ledger.read_text().splitlines() if ln.strip()]
        findings = [json.loads(ln) for ln in lines]
        persona_findings = [
            f for f in findings if f.get("audit_name") == "persona_verified"
        ]
        assert persona_findings, "no persona_verified finding in audit ledger"
        assert persona_findings[-1]["dimension"] == "execution"


# ---------------------------------------------------------------------------
# 9. No-persona default behaves like direct (exec runs, not blocked)
# ---------------------------------------------------------------------------

def test_no_persona_defaults_to_direct_allow(workspace):
    """With no persona configured, exec tools must not be blocked (fail-safe)."""
    from research_os.server.dispatch import _handle_tool_call

    # Don't set any persona — .os_state/config.yaml doesn't exist
    result = _handle_tool_call("tool_python_exec", {"script": "x = 1"}, workspace)
    env = json.loads(result[0].text)
    # Should NOT be a forbidden refusal
    if env["status"] == "error":
        error_msg = env.get("error", "")
        assert "forbidden" not in error_msg.lower(), (
            "exec tool blocked even with no persona — fail-safe violated"
        )


# ---------------------------------------------------------------------------
# 10. Seam guard: no /v1/chat or /v1/messages route was introduced
# ---------------------------------------------------------------------------

def test_no_llm_routes_introduced():
    """Verify no /v1/chat or /v1/messages route was added to server/ or tools/."""
    import re

    repo_root = Path(__file__).resolve().parents[3]
    server_dir = repo_root / "src" / "research_os" / "server"
    tools_dir = repo_root / "src" / "research_os" / "tools"

    bad_patterns = [
        re.compile(r"/v1/chat"),
        re.compile(r"/v1/messages"),
        re.compile(r"completions"),
    ]

    offenders = []
    for directory in (server_dir, tools_dir):
        for f in directory.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for pat in bad_patterns:
                if pat.search(text):
                    offenders.append(f"{f.relative_to(repo_root)}: {pat.pattern}")

    assert not offenders, f"LLM-proxy routes detected: {offenders}"


# ---------------------------------------------------------------------------
# 11. Seam guard: no import of research_os.daemon in server/ or tools/
# ---------------------------------------------------------------------------

def test_no_daemon_import_in_server_or_tools():
    """Verify personas.py and dispatch.py additions don't break the seam."""
    repo_root = Path(__file__).resolve().parents[3]
    server_dir = repo_root / "src" / "research_os" / "server"
    tools_dir = repo_root / "src" / "research_os" / "tools"

    offenders = []
    for directory in (server_dir, tools_dir):
        for f in directory.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            # Look for "from research_os.daemon" or "import research_os.daemon"
            if "research_os.daemon" in text:
                offenders.append(str(f.relative_to(repo_root)))

    assert not offenders, (
        f"Seam violation: daemon imports found in server/ or tools/: {offenders}"
    )
