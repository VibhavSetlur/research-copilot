"""Provenance integrity verification + daemon watch (4.1.x improvements)."""
from __future__ import annotations

from pathlib import Path

from research_os.project_ops import scaffold_minimal_workspace
from research_os.tools.actions.state.provenance import (
    verify_provenance_integrity,
    write_output_provenance,
)
from research_os.tools.actions.state.structure_audit import audit_structure


def _proj_with_output(tmp: Path):
    root = tmp / "p"
    scaffold_minimal_workspace(root, "T", mode="analysis")
    sd = root / "workspace" / "01_baseline"
    (sd / "outputs" / "figures").mkdir(parents=True, exist_ok=True)
    (sd / "data" / "past_step_input").mkdir(parents=True, exist_ok=True)
    inp = sd / "data" / "past_step_input" / "clean.csv"
    inp.write_text("a,b\n1,2\n")
    out = sd / "outputs" / "figures" / "01_curve.png"
    out.write_text("PNG")
    write_output_provenance(
        output_path=out, root=root,
        inputs=[str(inp.relative_to(root))],
        produced_by={"script": "scripts/01_v1.py"},
    )
    return root, inp, out


def test_clean_provenance_is_intact(tmp_path):
    root, _, _ = _proj_with_output(tmp_path)
    r = verify_provenance_integrity(root)
    assert r["ok"] is True
    assert r["findings"] == []


def test_input_drift_marks_output_stale(tmp_path):
    root, inp, _ = _proj_with_output(tmp_path)
    inp.write_text("a,b\n1,2\n3,4\n")  # input changed after output was built
    r = verify_provenance_integrity(root)
    assert r["ok"] is False
    assert r["stale_outputs"] == 1
    assert any(f["code"] == "input_drift" for f in r["findings"])


def test_output_edit_is_flagged(tmp_path):
    root, _, out = _proj_with_output(tmp_path)
    out.write_text("EDITED-BY-HAND")
    r = verify_provenance_integrity(root)
    assert any(f["code"] == "output_drift" for f in r["findings"])


def test_missing_input_is_blocking(tmp_path):
    root, inp, _ = _proj_with_output(tmp_path)
    inp.unlink()
    r = verify_provenance_integrity(root)
    assert any(f["code"] == "input_missing" for f in r["findings"])
    assert r["ok"] is False


def test_daemon_structure_watch_surfaces_provenance_drift(tmp_path):
    root, inp, _ = _proj_with_output(tmp_path)
    inp.write_text("CHANGED")
    codes = [f["code"] for f in audit_structure(root)["findings"]]
    assert "input_drift" in codes
