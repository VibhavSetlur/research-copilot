"""4.0.3: analysis-step script naming validator + daemon watch."""
from __future__ import annotations

import re
from pathlib import Path

from research_os.project_ops import scaffold_minimal_workspace
from research_os.tools.actions.audit.script_naming import (
    audit_step_script_naming,
    is_helper_module,
    suggest_script_name,
    validate_script_name,
)
from research_os.tools.actions.state.path import create_path
from research_os.tools.actions.state.structure_audit import audit_structure


def _step(tmp_path: Path) -> Path:
    scaffold_minimal_workspace(tmp_path, "T", mode="analysis")
    create_path("load and qc the counts", tmp_path)
    return [d for d in (tmp_path / "workspace").iterdir()
            if d.is_dir() and re.match(r"\d+_", d.name)][0]


def test_validate_good_names():
    assert validate_script_name("01a_load_counts_v1.py", "01") is None
    assert validate_script_name("01_fit_baseline_v1.py", "01") is None
    assert validate_script_name("12c_pca_v3.R", "12") is None
    assert validate_script_name("01_load_v1.ipynb", "01") is None


def test_validate_bad_names():
    assert validate_script_name("load_counts.py", "01") is not None      # no NN/version
    assert validate_script_name("1_thing.py", "01") is not None          # no version
    assert "does not match" in validate_script_name("analysis_final.py", "01")


def test_wrong_step_number_flagged():
    why = validate_script_name("02_foo_v1.py", "01")
    assert why is not None and "does not match this step's number" in why


def test_helpers_are_exempt():
    assert is_helper_module("utils.py")
    assert is_helper_module("__init__.py")
    assert is_helper_module("lib_io.py")
    assert validate_script_name("utils.py", "01") is None


def test_non_script_extensions_ignored():
    assert validate_script_name("data.csv", "01") is None
    assert validate_script_name("notes.md", "01") is None


def test_suggest_produces_conforming_name():
    s = suggest_script_name("analysis_final.py", "01")
    assert validate_script_name(s, "01") is None
    assert s.startswith("01_") and s.endswith("_v1.py")


def test_audit_step_flags_violations(tmp_path):
    sd = _step(tmp_path)
    (sd / "scripts" / "01a_load_counts_v1.py").write_text("print(1)")
    (sd / "scripts" / "analysis.py").write_text("print(2)")
    (sd / "scripts" / "utils.py").write_text("x=1")  # exempt
    res = audit_step_script_naming(sd)
    assert res["status"] == "error"
    assert len(res["violations"]) == 1
    assert "analysis.py" in res["violations"][0]["script"]


def test_clean_step_passes(tmp_path):
    sd = _step(tmp_path)
    (sd / "scripts" / "01a_load_v1.py").write_text("print(1)")
    (sd / "scripts" / "01b_qc_v1.py").write_text("print(2)")
    res = audit_step_script_naming(sd)
    assert res["status"] == "success"
    assert res["violations"] == []


def test_daemon_structure_audit_watches_script_naming(tmp_path):
    """The daemon's structure_audit must surface a script_naming finding so the
    self-check / sys_boot flags the drift (the user's core 4.0.3 ask)."""
    sd = _step(tmp_path)
    (sd / "scripts" / "badname.py").write_text("print(1)")
    res = audit_structure(tmp_path)
    codes = [f["code"] for f in res["findings"]]
    assert "script_naming" in codes
