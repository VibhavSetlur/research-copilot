"""End-to-end MCP workflow — scaffold, protocol load, path create, audit."""

from research_os.project_ops import scaffold_minimal_workspace
from research_os.server import _handle_tool_call


def test_full_workflow(tmp_path):
    # 1. Scaffold (workspace creation is now a project_ops helper, not a tool)
    scaffold_minimal_workspace(tmp_path, "Test Project")

    # 2. Load a real protocol (uses the installed protocols/ dir)
    res = _handle_tool_call(
        "sys_protocol_get", {"protocol_name": "guidance/session_boot"}, tmp_path
    )
    assert "success" in res[0].text

    # 3. Create a path — consolidated into sys_state_get(operation='create')
    res = _handle_tool_call(
        "sys_state_get",
        {"operation": "create", "name": "baseline", "hypothesis": "Test H"},
        tmp_path,
    )
    assert "Unknown tool" not in res[0].text

    # 4. Write a workspace file via MCP (synthesis paper)
    paper = (
        "# Title\n\n"
        "## Abstract\nbody\n\n## Introduction\nbody\n\n## Methods\nbody\n\n"
        "## Results\nThe sum is 21.\n\n## Discussion\nThis proves our hypothesis.\n\n"
        "## References\n[1] Smith et al.\n"
    )
    res = _handle_tool_call(
        "sys_file_write",
        {"filepath": "synthesis/paper.md", "content": paper, "force": True},
        tmp_path,
    )
    assert "success" in res[0].text

    # 5. Audit — consolidated tool_audit reaches its handler
    res = _handle_tool_call(
        "tool_audit",
        {"scope": "project", "dimension": "synthesis",
         "paper_path": "synthesis/paper.md"},
        tmp_path,
    )
    assert "Unknown tool" not in res[0].text


def test_dot_notation_routes_to_underscore(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Dot Test")

    # Dot notation
    res = _handle_tool_call(
        "sys.protocol.get", {"protocol_name": "guidance/session_boot"}, tmp_path
    )
    assert "success" in res[0].text


def test_legacy_tool_name_alias(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Alias Test")

    # `tool_audit_statistical_power` is a retained live alias → tool_audit.
    res = _handle_tool_call(
        "tool_audit_statistical_power",
        {"filepath": "workspace/dummy.csv",
         "effect_size": 0.5, "alpha": 0.05, "n": 100},
        tmp_path,
    )
    # Alias resolves and reaches the handler (may error on missing file).
    assert "Unknown tool" not in res[0].text
