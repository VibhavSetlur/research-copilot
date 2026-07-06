"""Server-side autopilot floor-gate enforcement.

guidance/autopilot.yaml enumerates 8 mandatory confirmation gates that
the dispatcher must refuse when autonomy_level == 'autopilot' AND the
caller did not pass ``confirmed=true``. Each gate is covered twice:

  * confirmed=false (or omitted) → autopilot_gate_blocked error
  * confirmed=true               → call proceeds (no gate error)

These tests bypass the full handler stack by calling the gate helper
directly — that way they don't depend on every gated tool's full
arg surface (which varies). A single end-to-end test exercises the
dispatcher wiring via _handle_tool_call for sys_file_write into
synthesis/ with force=true.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from research_os.server.autopilot_gate import (
    _requires_confirmation,
    enforce_autopilot_gate,
)
from research_os.server.dispatch import _handle_tool_call
from research_os.server.errors import RoError


def _set_autonomy(root: Path, level: str) -> None:
    """Write a minimal researcher_config.yaml with the chosen autonomy level."""
    cfg_dir = root / "inputs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "researcher_config.yaml").write_text(
        yaml.safe_dump({"interaction": {"autonomy_level": level}})
    )


# The floor gates from guidance/autopilot.yaml step `mandatory_gates`.
# Each row: (tool_name, arguments_dict).
FLOOR_GATES: list[tuple[str, dict]] = [
    # 1. final-deliverable PDF compile
    ("tool_typst_compile", {}),
    # 2. reproducibility audit
    ("tool_audit", {"scope": "step", "dimension": "reproducibility"}),
    # 3. paid search candidate (consolidated search entry point)
    ("tool_search", {"query": "lit review", "source": "paid"}),
    # 4. sys_file_write to synthesis/ with force=true
    ("sys_file_write", {"filepath": "synthesis/paper.typ", "content": "x", "force": True}),
    # 5. package install
    ("tool_package_install", {"packages": ["numpy"]}),
    # 6. expensive task (operation='run')
    ("tool_task", {"operation": "run", "command": "ls"}),
]


@pytest.mark.parametrize("tool_name,arguments", FLOOR_GATES)
def test_autopilot_gate_blocks_without_confirmed(tmp_path, tool_name, arguments):
    """Each floor gate must refuse the call in autopilot mode without confirmed=true."""
    _set_autonomy(tmp_path, "autopilot")
    # The synthesis-force gate only trips on an actual OVERWRITE; create
    # the target so the gate has something to protect.
    if tool_name == "sys_file_write":
        syn = tmp_path / "synthesis"
        syn.mkdir(parents=True, exist_ok=True)
        (syn / "paper.typ").write_text("existing")
    with pytest.raises(RoError) as exc:
        enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)
    assert exc.value.what == "autopilot_gate_blocked"
    assert tool_name in (exc.value.why or "")
    # The next_action must give a concrete recovery call.
    assert "confirmed=true" in (exc.value.next_action or "")


@pytest.mark.parametrize("tool_name,arguments", FLOOR_GATES)
def test_autopilot_gate_passes_with_confirmed(tmp_path, tool_name, arguments):
    """Each floor gate must pass through when confirmed=true is set."""
    _set_autonomy(tmp_path, "autopilot")
    args = dict(arguments)
    args["confirmed"] = True
    # No exception = pass-through.
    enforce_autopilot_gate(tool_name, args, tmp_path)


@pytest.mark.parametrize("tool_name,arguments", FLOOR_GATES)
def test_supervised_mode_skips_gate(tmp_path, tool_name, arguments):
    """In supervised / non-autopilot modes the gate is a no-op."""
    _set_autonomy(tmp_path, "supervised")
    enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)


def test_sys_file_write_outside_synthesis_not_gated(tmp_path):
    """sys_file_write to workspace/ with force=true is NOT a gate."""
    _set_autonomy(tmp_path, "autopilot")
    enforce_autopilot_gate(
        "sys_file_write",
        {"filepath": "workspace/notes.md", "content": "x", "force": True},
        tmp_path,
    )


def test_sys_file_write_synthesis_no_force_not_gated(tmp_path):
    """sys_file_write to synthesis/ WITHOUT force=true is NOT a gate."""
    _set_autonomy(tmp_path, "autopilot")
    enforce_autopilot_gate(
        "sys_file_write",
        {"filepath": "synthesis/paper.md", "content": "x"},
        tmp_path,
    )


def test_sys_path_list_not_gated(tmp_path):
    """sys_path with operation='list' is NOT a gate (read-only)."""
    _set_autonomy(tmp_path, "autopilot")
    enforce_autopilot_gate("sys_path", {"operation": "list"}, tmp_path)


def test_tool_task_status_not_gated(tmp_path):
    """tool_task with operation='status' is NOT a gate."""
    _set_autonomy(tmp_path, "autopilot")
    enforce_autopilot_gate(
        "tool_task", {"operation": "status", "task_id": "abc"}, tmp_path
    )


def test_tool_audit_completeness_not_gated(tmp_path):
    """Only reproducibility audits are floor-gated; completeness is fine."""
    _set_autonomy(tmp_path, "autopilot")
    enforce_autopilot_gate(
        "tool_audit",
        {"scope": "step", "dimension": "completeness"},
        tmp_path,
    )


def test_tool_research_tool_free_not_gated(tmp_path):
    """tool_research_tool WITHOUT source='paid' is not a gate."""
    _set_autonomy(tmp_path, "autopilot")
    enforce_autopilot_gate(
        "tool_research_tool", {"task": "search arxiv"}, tmp_path
    )


def test_dotfile_prefix_not_confused_for_synthesis():
    """A path starting with '.' must not be mangled into 'synthesis/'.

    The old normalization used str.lstrip('./') which strips CHARACTERS, so
    '.synthesis/x' became 'synthesis/x' and got falsely gated.
    """
    # A dotfile directory that merely contains 'synthesis' is NOT synthesis/.
    assert not _requires_confirmation(
        "sys_file_write", {"filepath": ".synthesis/x", "force": True}
    )
    # The real synthesis path is still gated, with or without a leading "./".
    assert _requires_confirmation(
        "sys_file_write", {"filepath": "./synthesis/paper.typ", "force": True}
    )
    assert _requires_confirmation(
        "sys_file_write", {"filepath": "synthesis/paper.typ", "force": True}
    )


def test_unit_requires_confirmation_truth_table():
    """Sanity check the gate-decision helper directly (no config IO)."""
    assert _requires_confirmation("tool_package_install", {})
    assert _requires_confirmation(
        "sys_file_write",
        {"filepath": "synthesis/paper.md", "force": True, "content": "x"},
    )
    assert not _requires_confirmation(
        "sys_file_write",
        {"filepath": "synthesis/paper.md", "content": "x"},
    )
    assert _requires_confirmation("tool_task", {"operation": "run"})
    assert not _requires_confirmation("tool_task", {"operation": "kill"})
    assert _requires_confirmation(
        "tool_search", {"query": "x", "source": "paid"}
    )
    assert _requires_confirmation(
        "tool_search", {"query": "x", "paid": True}
    )
    assert not _requires_confirmation("tool_search", {"query": "x"})
    assert _requires_confirmation(
        "tool_audit", {"scope": "step", "dimension": "reproducibility"}
    )
    assert not _requires_confirmation(
        "tool_audit", {"scope": "step", "dimension": "completeness"}
    )
    assert _requires_confirmation("tool_typst_compile", {})
    # Unknown tool — never gated.
    assert not _requires_confirmation("sys_unknown_tool", {})


# ---------------------------------------------------------------------------
# Integration: full dispatcher wiring (one canonical case).
# ---------------------------------------------------------------------------


def test_dispatcher_returns_gate_envelope_for_sys_file_write(tmp_path):
    """End-to-end: _handle_tool_call routes the gate error into the envelope."""
    _set_autonomy(tmp_path, "autopilot")
    # Materialize an existing deliverable so force=true is a real overwrite.
    syn = tmp_path / "synthesis"
    syn.mkdir(parents=True, exist_ok=True)
    (syn / "paper.typ").write_text("existing deliverable")
    res = _handle_tool_call(
        "sys_file_write",
        {"filepath": "synthesis/paper.typ", "content": "x", "force": True},
        tmp_path,
    )
    payload = json.loads(res[0].text)
    assert payload.get("status") == "error"
    err_text = json.dumps(payload)
    assert "autopilot_gate_blocked" in err_text
    assert "sys_file_write" in err_text


def test_dispatcher_no_gate_in_supervised_mode(tmp_path):
    """Supervised mode: dispatcher does not raise an autopilot gate error.

    The call may still fail downstream (handler-side), but the failure
    message must NOT contain ``autopilot_gate_blocked``.
    """
    _set_autonomy(tmp_path, "supervised")
    res = _handle_tool_call(
        "sys_file_write",
        {"filepath": "synthesis/paper.md", "content": "x", "force": True},
        tmp_path,
    )
    body = res[0].text if res else ""
    assert "autopilot_gate_blocked" not in body
