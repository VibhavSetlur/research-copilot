"""Unit tests for `research-os doctor`.

Exercises every check function in isolation against a temporary
filesystem layout, then drives the CLI subcommand end-to-end to
confirm exit codes + JSON output + human-readable rendering.

The doctor is deliberately defensive (each check returns a tri-state
status instead of raising) so the tests focus on:

  * the status each check returns under known inputs,
  * the aggregate exit code derived from the worst status, and
  * the shape + sortability of the JSON payload.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from research_os import cli_doctor


# ── individual check functions ────────────────────────────────────────


def test_check_python_version_passes_on_current_interpreter():
    status, msg, _ = cli_doctor.check_python_version()
    # The conda env we run in is >= 3.10 — the project's own floor.
    assert status == "pass"
    assert ">= 3.10" in msg


def test_check_conda_active_warns_when_unset(monkeypatch):
    monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
    status, msg, fix = cli_doctor.check_conda_active()
    assert status == "warn"
    assert "conda" in msg.lower() or "CONDA" in msg
    assert fix and "conda activate" in fix


def test_check_conda_active_passes_when_set(monkeypatch):
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "research-os")
    status, msg, _ = cli_doctor.check_conda_active()
    assert status == "pass"
    assert "research-os" in msg


def test_check_version_consistency_pass_when_all_match(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        'version = "9.9.9"\n', encoding="utf-8")
    (tmp_path / "CITATION.cff").write_text(
        "version: 9.9.9\n", encoding="utf-8")
    # Force __init__ reader to return 9.9.9 for this test.
    monkeypatch.setattr(cli_doctor, "_read_version_init", lambda: "9.9.9")
    status, msg, _ = cli_doctor.check_version_consistency(root=tmp_path)
    assert status == "pass"
    assert "9.9.9" in msg


def test_check_version_consistency_fail_on_mismatch(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        'version = "1.0.0"\n', encoding="utf-8")
    (tmp_path / "CITATION.cff").write_text(
        "version: 1.0.1\n", encoding="utf-8")
    monkeypatch.setattr(cli_doctor, "_read_version_init", lambda: "1.0.0")
    status, msg, fix = cli_doctor.check_version_consistency(root=tmp_path)
    assert status == "fail"
    assert "mismatch" in msg.lower()
    assert fix is not None


def test_check_in_tree_packs_registered_passes():
    # The 5 bundled packs all ship in the wheel — they must register.
    status, msg, _ = cli_doctor.check_in_tree_packs_registered()
    assert status == "pass", msg
    assert "5" in msg


def test_check_external_pack_entrypoints_returns_pass():
    # External packs may or may not be installed; status is always pass.
    status, _, _ = cli_doctor.check_external_pack_entrypoints()
    assert status == "pass"


def test_check_embeddings_fresh_pass_when_embeddings_newer(tmp_path):
    # P1: the router_index kwarg now points at the compiled bundle.
    bundle = tmp_path / "_protocols.bundle"
    emb = tmp_path / "_embeddings.npz"
    bundle.write_bytes(b"fake-bundle")
    emb.write_bytes(b"fake")
    import os
    os.utime(bundle, (0, 0))
    os.utime(emb, (10, 10))
    status, _, _ = cli_doctor.check_embeddings_fresh(
        embeddings=emb, router_index=bundle)
    assert status == "pass"


def test_check_embeddings_fresh_warn_when_stale(tmp_path):
    bundle = tmp_path / "_protocols.bundle"
    emb = tmp_path / "_embeddings.npz"
    bundle.write_bytes(b"fake-bundle")
    emb.write_bytes(b"fake")
    import os
    os.utime(emb, (0, 0))
    os.utime(bundle, (10, 10))  # bundle newer than embeddings → stale
    status, msg, fix = cli_doctor.check_embeddings_fresh(
        embeddings=emb, router_index=bundle)
    assert status == "warn"
    assert "stale" in msg.lower()
    assert fix


def test_check_embeddings_fresh_warn_when_missing(tmp_path):
    bundle = tmp_path / "_protocols.bundle"
    bundle.write_bytes(b"fake-bundle")
    emb = tmp_path / "missing.npz"
    status, msg, _ = cli_doctor.check_embeddings_fresh(
        embeddings=emb, router_index=bundle)
    assert status == "warn"
    assert "missing" in msg.lower()


def test_check_embeddings_fresh_warn_when_bundle_missing(tmp_path):
    bundle = tmp_path / "missing.bundle"
    emb = tmp_path / "_embeddings.npz"
    emb.write_bytes(b"fake")
    status, msg, fix = cli_doctor.check_embeddings_fresh(
        embeddings=emb, router_index=bundle)
    assert status == "warn"
    assert "bundle" in msg.lower() and "missing" in msg.lower()
    assert fix and "build_protocols" in fix


def test_check_typst_on_path_status_is_known():
    status, _, _ = cli_doctor.check_typst_on_path()
    assert status in ("pass", "warn")


def test_check_chromium_on_path_status_is_known():
    status, _, _ = cli_doctor.check_chromium_on_path()
    assert status in ("pass", "warn")


# ── workspace-scoped checks ───────────────────────────────────────────


def _make_workspace(tmp_path: Path) -> Path:
    """Minimal Research OS workspace tree for workspace-level checks."""
    (tmp_path / ".os_state").mkdir()
    (tmp_path / "inputs").mkdir()
    (tmp_path / "workspace").mkdir()
    return tmp_path


def test_check_optional_deps_passes_when_no_workspace():
    status, _, _ = cli_doctor.check_optional_deps(workspace=None)
    assert status == "pass"


def test_check_optional_deps_passes_when_feature_off(tmp_path):
    ws = _make_workspace(tmp_path)
    (ws / "inputs" / "researcher_config.yaml").write_text(
        textwrap.dedent(
            """
            synthesis:
              interactive_figures: false
            """
        ).strip() + "\n",
        encoding="utf-8",
    )
    status, _, _ = cli_doctor.check_optional_deps(workspace=ws)
    assert status == "pass"


def test_check_mcp_configs_wired_warns_when_no_ide(tmp_path):
    ws = _make_workspace(tmp_path)
    status, msg, fix = cli_doctor.check_mcp_configs_wired(workspace=ws)
    assert status == "warn"
    assert "ide" in msg.lower()
    assert fix and "research-os ide add" in fix


def test_check_mcp_configs_wired_pass_when_wired(tmp_path):
    ws = _make_workspace(tmp_path)
    (ws / ".claude").mkdir()
    (ws / ".claude" / "mcp.json").write_text("{}", encoding="utf-8")
    status, msg, _ = cli_doctor.check_mcp_configs_wired(workspace=ws)
    assert status == "pass"
    assert "claude" in msg


def test_check_workspace_integrity_pass_on_empty_workspace(tmp_path):
    ws = _make_workspace(tmp_path)
    status, _, _ = cli_doctor.check_workspace_integrity(workspace=ws)
    assert status == "pass"


def test_check_workspace_integrity_flags_unresolved_block(tmp_path):
    ws = _make_workspace(tmp_path)
    (ws / ".audit_findings.jsonl").write_text(
        json.dumps({"level": "BLOCK", "resolved": False, "msg": "x"}) + "\n"
        + json.dumps({"level": "BLOCK", "resolved": True}) + "\n",
        encoding="utf-8",
    )
    status, msg, fix = cli_doctor.check_workspace_integrity(workspace=ws)
    assert status == "warn"
    assert "BLOCK" in msg
    assert fix


def test_check_disk_space_pass_for_empty_workspace(tmp_path):
    ws = _make_workspace(tmp_path)
    status, _, _ = cli_doctor.check_disk_space(workspace=ws, threshold_gb=5.0)
    assert status == "pass"


def test_check_disk_space_warn_when_over_threshold(tmp_path):
    ws = _make_workspace(tmp_path)
    big = ws / "huge.bin"
    big.write_bytes(b"x" * 4096)  # 4 KB
    status, msg, fix = cli_doctor.check_disk_space(
        workspace=ws, threshold_gb=4096 / (1024 ** 3) / 2)  # 2 KB threshold
    assert status == "warn"
    assert "exceeds" in msg.lower()
    assert fix


def test_check_git_clean_pass_when_not_a_repo(tmp_path):
    ws = _make_workspace(tmp_path)
    status, msg, _ = cli_doctor.check_git_clean(workspace=ws)
    assert status == "pass"
    assert "not a git repo" in msg.lower()


def test_check_gitignore_covers_state_warn_when_missing(tmp_path):
    ws = _make_workspace(tmp_path)
    status, msg, fix = cli_doctor.check_gitignore_covers_state(workspace=ws)
    assert status == "warn"
    assert ".gitignore" in msg
    assert fix


def test_check_gitignore_covers_state_pass_when_complete(tmp_path):
    ws = _make_workspace(tmp_path)
    (ws / ".gitignore").write_text(
        ".os_state/\nworkspace/cache/\nworkspace/logs/\n", encoding="utf-8")
    status, _, _ = cli_doctor.check_gitignore_covers_state(workspace=ws)
    assert status == "pass"


def test_check_gitignore_covers_state_warn_on_partial(tmp_path):
    ws = _make_workspace(tmp_path)
    (ws / ".gitignore").write_text(
        ".os_state/\n", encoding="utf-8")  # missing cache/scratch entry
    status, msg, _ = cli_doctor.check_gitignore_covers_state(workspace=ws)
    assert status == "warn"
    assert "workspace/cache" in msg or "missing" in msg.lower()


# ── orchestration + CLI ──────────────────────────────────────────────


def test_run_all_checks_returns_doctor_run():
    r = cli_doctor.run_all_checks()
    assert isinstance(r, cli_doctor.DoctorRun)
    assert len(r.checks) >= 5
    assert all(c.status in ("pass", "warn", "fail") for c in r.checks)


def test_exit_code_matches_worst_status():
    r = cli_doctor.DoctorRun()
    r.add("a", ("pass", "ok", None))
    assert r.exit_code == 0
    r.add("b", ("warn", "meh", None))
    assert r.exit_code == 1
    r.add("c", ("fail", "broken", None))
    assert r.exit_code == 2


def test_workspace_only_without_workspace_emits_failure(tmp_path, monkeypatch):
    # No .os_state at or above tmp_path → workspace-only must fail.
    monkeypatch.chdir(tmp_path)
    r = cli_doctor.run_all_checks(workspace_only=True)
    assert r.exit_code == 2
    names = [c.name for c in r.checks]
    assert "workspace_present" in names


def test_doctor_json_valid_via_subprocess():
    """End-to-end: spawn `python -m research_os.cli doctor --json` and
    confirm the output parses as JSON with the expected top-level keys.
    """
    cmd = [sys.executable, "-m", "research_os.cli", "doctor", "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    # Exit code may be 0, 1, or 2 depending on local install state.
    assert proc.returncode in (0, 1, 2), proc.stderr
    payload = json.loads(proc.stdout)
    assert set(payload.keys()) >= {"checks", "summary", "exit_code"}
    assert isinstance(payload["checks"], list)
    assert {"pass", "warn", "fail"} <= set(payload["summary"].keys())
    # Every check must have the canonical keys.
    for c in payload["checks"]:
        assert {"name", "status", "message", "scope"} <= set(c.keys())
        assert c["status"] in ("pass", "warn", "fail")


def test_doctor_cli_human_output_via_subprocess():
    """End-to-end: human output mentions the banner and summary."""
    cmd = [sys.executable, "-m", "research_os.cli", "doctor", "--no-color"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode in (0, 1, 2), proc.stderr
    assert "research-os doctor" in proc.stdout
    assert "Summary" in proc.stdout


@pytest.mark.parametrize("flag", ["--verbose", "--workspace-only"])
def test_doctor_flags_accepted(flag):
    """Each flag must be a valid argparse option (no crash)."""
    cmd = [sys.executable, "-m", "research_os.cli", "doctor", flag, "--json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert proc.returncode in (0, 1, 2), proc.stderr
    # Still emits valid JSON.
    json.loads(proc.stdout)
