"""Unit tests for research_os.config.detect.detect_environment."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from research_os.config.detect import detect_environment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _which_factory(present: set[str]):
    """Return a ``shutil.which`` replacement that only finds names in *present*."""

    def _which(name: str, *args, **kwargs):
        return f"/usr/bin/{name}" if name in present else None

    return _which


# ---------------------------------------------------------------------------
# Compute detection
# ---------------------------------------------------------------------------


def test_compute_hpc_when_sbatch_present(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory({"sbatch"}))
    result = detect_environment(root=tmp_path)
    assert result["compute"] == "hpc"


def test_compute_docker_when_only_docker_present(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory({"docker"}))
    result = detect_environment(root=tmp_path)
    assert result["compute"] == "docker"


def test_compute_local_when_neither_present(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    result = detect_environment(root=tmp_path)
    assert result["compute"] == "local"


def test_compute_hpc_takes_priority_over_docker(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory({"sbatch", "docker"}))
    result = detect_environment(root=tmp_path)
    assert result["compute"] == "hpc"


# ---------------------------------------------------------------------------
# Python version
# ---------------------------------------------------------------------------


def test_python_version_format(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    result = detect_environment(root=tmp_path)
    assert result["python"] == f"{sys.version_info.major}.{sys.version_info.minor}"
    # Must be "MAJOR.MINOR" — exactly two numeric parts separated by a dot.
    parts = result["python"].split(".")
    assert len(parts) == 2
    assert all(p.isdigit() for p in parts)


# ---------------------------------------------------------------------------
# Marker-file / inferred_client detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marker", [
    "CLAUDE.md",
    ".cursorrules",
    ".cursor",
    "AGENTS.md",
    "GEMINI.md",
])
def test_marker_file_detected(tmp_path, monkeypatch, marker):
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    # Create file or directory marker.
    target = tmp_path / marker
    if marker.startswith(".cursor") and "rules" not in marker:
        target.mkdir()
    else:
        target.touch()
    result = detect_environment(root=tmp_path)
    assert result["inferred_client"] == marker


def test_no_markers_omits_inferred_client(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    result = detect_environment(root=tmp_path)
    assert "inferred_client" not in result


def test_first_marker_wins(tmp_path, monkeypatch):
    """When multiple markers are present the first in _CLIENT_MARKERS wins."""
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    # Create all markers.
    for name in ["CLAUDE.md", ".cursorrules", "AGENTS.md"]:
        (tmp_path / name).touch()
    result = detect_environment(root=tmp_path)
    # CLAUDE.md is the first in the ordered list.
    assert result["inferred_client"] == "CLAUDE.md"


def test_root_defaults_to_cwd(monkeypatch, tmp_path):
    """Passing root=None uses Path.cwd(); patch cwd to tmp_path."""
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "AGENTS.md").touch()
    result = detect_environment(root=None)
    assert result["inferred_client"] == "AGENTS.md"


# ---------------------------------------------------------------------------
# Git config parsing
# ---------------------------------------------------------------------------


def _make_check_output(mapping: dict[str, str]):
    """Return a ``subprocess.check_output`` replacement driven by *mapping*."""

    def _check_output(cmd, **kwargs):
        # cmd is ["git", "config", <key>]
        key = cmd[2]
        if key in mapping:
            return mapping[key] + "\n"
        raise subprocess.CalledProcessError(1, cmd)

    return _check_output


def test_git_user_name_and_email_detected(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    monkeypatch.setattr(
        "subprocess.check_output",
        _make_check_output({"user.name": "Ada Lovelace", "user.email": "ada@example.com"}),
    )
    result = detect_environment(root=tmp_path)
    assert result["user_name"] == "Ada Lovelace"
    assert result["user_email"] == "ada@example.com"


def test_git_missing_omits_keys(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    monkeypatch.setattr(
        "subprocess.check_output",
        _make_check_output({}),
    )
    result = detect_environment(root=tmp_path)
    assert "user_name" not in result
    assert "user_email" not in result


def test_git_not_on_path_omits_keys(monkeypatch, tmp_path):
    """FileNotFoundError (git binary absent) must not crash detect_environment."""
    monkeypatch.setattr("shutil.which", _which_factory(set()))

    def _explode(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr("subprocess.check_output", _explode)
    result = detect_environment(root=tmp_path)
    assert "user_name" not in result
    assert "user_email" not in result


def test_git_subprocess_error_omits_keys(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory(set()))

    def _explode(*args, **kwargs):
        raise subprocess.SubprocessError("broken pipe")

    monkeypatch.setattr("subprocess.check_output", _explode)
    result = detect_environment(root=tmp_path)
    assert "user_name" not in result
    assert "user_email" not in result


# ---------------------------------------------------------------------------
# Package manager
# ---------------------------------------------------------------------------


def test_package_manager_conda_when_conda_present(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory({"conda"}))
    result = detect_environment(root=tmp_path)
    assert result["package_manager"] == "conda"


def test_package_manager_pip_when_no_conda(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    result = detect_environment(root=tmp_path)
    assert result["package_manager"] == "pip"


# ---------------------------------------------------------------------------
# Always-present keys
# ---------------------------------------------------------------------------


def test_always_present_keys(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which_factory(set()))
    monkeypatch.setattr("subprocess.check_output", _make_check_output({}))
    result = detect_environment(root=tmp_path)
    for key in ("compute", "python", "package_manager"):
        assert key in result, f"key '{key}' must always be present"
