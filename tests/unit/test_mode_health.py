"""Mode-aware daemon health checks — the daemon is involved in EVERY mode."""
from __future__ import annotations

import tempfile
from pathlib import Path

from research_os.project_ops import scaffold_minimal_workspace
from research_os.tools.actions.state.mode_health import mode_health_findings
from research_os.tools.actions.state.structure_audit import audit_structure
from research_os.daemon.health_notes import run_self_check


def _proj(mode: str) -> Path:
    root = Path(tempfile.mkdtemp()) / "p"
    scaffold_minimal_workspace(root, "T", mode=mode)
    return root


def _codes(findings):
    return [f.get("code") for f in findings]


def test_tool_build_flags_missing_eval():
    root = _proj("tool_build")
    assert "tool_build_no_eval" in _codes(mode_health_findings(root))


def test_notebook_flags_no_notebooks():
    root = _proj("notebook")
    assert "notebook_none_yet" in _codes(mode_health_findings(root))


def test_multi_study_flags_no_studies():
    root = _proj("multi_study")
    assert "multi_study_no_studies" in _codes(mode_health_findings(root))


def test_exploration_flags_unpromoted_probes():
    root = _proj("exploration")
    scratch = root / "workspace" / "scratch"
    for i in range(9):
        (scratch / f"probe_{i}.py").write_text("x = 1")
    assert "exploration_unpromoted" in _codes(mode_health_findings(root))


def test_mode_detected_from_config_when_quoted():
    # config writes mode: "exploration" (quoted) — must still resolve.
    root = _proj("exploration")
    from research_os.tools.actions.state.mode_health import _read_mode
    assert _read_mode(root) == "exploration"


def test_analysis_mode_intake_without_steps_flags_info():
    # Track B added _check_analysis: a fresh scaffold has intake.md but no
    # numbered steps, so the checker emits one info finding. An empty
    # workspace (no intake) stays silent.
    root = _proj("analysis")
    codes = _codes(mode_health_findings(root))
    assert codes == ["analysis_no_steps"]

    # Silence when intake is absent (truly blank project).
    root2 = _proj("analysis")
    (root2 / "inputs" / "intake.md").unlink()
    assert mode_health_findings(root2) == []


def test_daemon_self_check_surfaces_mode_health():
    root = _proj("notebook")
    codes = _codes(run_self_check(root)["findings"])
    assert "notebook_none_yet" in codes


def test_structure_audit_surfaces_mode_health():
    root = _proj("multi_study")
    codes = _codes(audit_structure(root)["findings"])
    assert "multi_study_no_studies" in codes


def test_fail_open_on_missing_workspace():
    root = Path(tempfile.mkdtemp()) / "empty"
    root.mkdir()
    assert mode_health_findings(root, "tool_build") == []


def test_multi_study_flags_stale_rollup():
    import time
    root = _proj("multi_study")
    (root / "studies" / "s1").mkdir(parents=True, exist_ok=True)
    (root / "roll_up").mkdir(exist_ok=True)
    (root / "roll_up" / "meta.md").write_text("old")
    time.sleep(0.02)
    (root / "studies" / "s1" / "result.csv").write_text("new data")  # newer than rollup
    assert "multi_study_rollup_stale" in _codes(mode_health_findings(root))


def test_multi_study_flags_missing_codebook():
    root = _proj("multi_study")
    # Remove the seeded codebook but keep shared/ non-empty.
    import os
    for f in (root / "shared").glob("codebook*"):
        os.remove(f)
    (root / "shared" / "notes.md").write_text("x")
    assert "multi_study_no_codebook" in _codes(mode_health_findings(root))
