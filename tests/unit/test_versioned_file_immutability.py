"""Tests for versioned-artifact immutability (the bump-don't-overwrite rule).

A file named ``*_v<N>.<ext>`` carries an explicit version suffix BECAUSE
edits are meant to land in a NEW version. sys_file_write refuses to overwrite
an existing versioned artifact under workspace/ or synthesis/ unless force=true,
and points the AI at the bumped name.
"""
from __future__ import annotations

import json

from research_os.server import _handle_tool_call
from research_os.tools.actions.audit.script_naming import (
    highest_existing_version,
    is_versioned_name,
    next_version_name,
    parse_versioned_name,
    suggest_version_bump,
)


# ── pure helpers ──────────────────────────────────────────────────────


def test_parse_versioned_name():
    assert parse_versioned_name("01_fit_baseline_v2.py") == ("01_fit_baseline", 2, ".py")
    assert parse_versioned_name("report_v10.md") == ("report", 10, ".md")
    assert parse_versioned_name("model_v1") == ("model", 1, "")
    assert parse_versioned_name("no_version.py") is None
    assert parse_versioned_name("utils.py") is None


def test_is_versioned_name():
    assert is_versioned_name("01a_load_v1.py")
    assert not is_versioned_name("01a_load.py")


def test_next_version_name():
    assert next_version_name("01_fit_v2.py") == "01_fit_v3.py"
    assert next_version_name("plain.py") is None


def test_highest_existing_version(tmp_path):
    (tmp_path / "01_fit_v1.py").write_text("a")
    (tmp_path / "01_fit_v2.py").write_text("b")
    (tmp_path / "01_fit_v5.py").write_text("c")
    (tmp_path / "other_v9.py").write_text("d")
    assert highest_existing_version(tmp_path, "01_fit", ".py") == 5
    assert highest_existing_version(tmp_path, "missing", ".py") == 0


def test_suggest_version_bump_lands_above_highest_sibling(tmp_path):
    (tmp_path / "01_fit_v1.py").write_text("a")
    (tmp_path / "01_fit_v2.py").write_text("b")
    (tmp_path / "01_fit_v3.py").write_text("c")
    # Even if the AI opened v1, the bump must clear v3.
    assert suggest_version_bump(tmp_path / "01_fit_v1.py") == "01_fit_v4.py"


# ── the live write-time gate ──────────────────────────────────────────


def _write(tmp_path, filepath, content="x", **extra):
    args = {"filepath": filepath, "content": content, **extra}
    res = _handle_tool_call("sys_file_write", args, tmp_path)
    return json.loads(res[0].text)


def test_overwrite_versioned_artifact_is_refused(tmp_path):
    step = tmp_path / "workspace" / "01_load" / "scripts"
    step.mkdir(parents=True)
    (step / "01_load_v1.py").write_text("original")
    payload = _write(tmp_path, "workspace/01_load/scripts/01_load_v1.py", "edited")
    assert payload["status"] == "error"
    assert "01_load_v2.py" in payload["error"]
    # The original must be untouched.
    assert (step / "01_load_v1.py").read_text() == "original"


def test_overwrite_versioned_artifact_with_force_succeeds(tmp_path):
    step = tmp_path / "workspace" / "01_load" / "scripts"
    step.mkdir(parents=True)
    (step / "01_load_v1.py").write_text("original")
    payload = _write(
        tmp_path, "workspace/01_load/scripts/01_load_v1.py", "edited", force=True,
    )
    assert payload["status"] == "success"
    assert (step / "01_load_v1.py").read_text() == "edited"


def test_writing_new_version_succeeds(tmp_path):
    step = tmp_path / "workspace" / "01_load" / "scripts"
    step.mkdir(parents=True)
    (step / "01_load_v1.py").write_text("original")
    payload = _write(tmp_path, "workspace/01_load/scripts/01_load_v2.py", "new version")
    assert payload["status"] == "success"
    assert (step / "01_load_v1.py").read_text() == "original"
    assert (step / "01_load_v2.py").read_text() == "new version"


def test_writing_first_version_succeeds(tmp_path):
    step = tmp_path / "workspace" / "01_load" / "scripts"
    step.mkdir(parents=True)
    payload = _write(tmp_path, "workspace/01_load/scripts/01_load_v1.py", "first")
    assert payload["status"] == "success"


def test_non_versioned_overwrite_unaffected(tmp_path):
    """A plain (un-versioned) workspace file overwrites freely — the rule is
    scoped to _v<N> artifacts only."""
    step = tmp_path / "workspace" / "01_load"
    step.mkdir(parents=True)
    (step / "notes.md").write_text("a")
    payload = _write(tmp_path, "workspace/01_load/notes.md", "b")
    assert payload["status"] == "success"


def test_versioned_overwrite_outside_artifact_trees_unaffected(tmp_path):
    """The gate is scoped to workspace/ + synthesis/. A versioned file under
    inputs/ (e.g. a config the researcher versions) is not gated here."""
    d = tmp_path / "inputs" / "context"
    d.mkdir(parents=True)
    (d / "spec_v1.md").write_text("a")
    payload = _write(tmp_path, "inputs/context/spec_v1.md", "b")
    assert payload["status"] == "success"
