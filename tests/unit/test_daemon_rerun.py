"""Unit tests for Daemon.rerun_run (Phase 7 §13.4).

Style mirrors test_daemon_core.py: Daemon(...) or Daemon.for_root(tmp_path),
real subprocess commands that are trivial+fast, poll via _run_to_terminal(),
then read the written manifest back and assert on spec fields.
"""
from __future__ import annotations

import time

import pytest

from research_os.daemon import Daemon, DaemonConfig
from research_os.daemon.runstore import build_manifest


# ── helpers ───────────────────────────────────────────────────────────


def _run_to_terminal(daemon, job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = daemon.tasks.get(job_id)
        if j and j.status.value in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach a terminal state within {timeout}s")


def _make_daemon(tmp_path):
    return Daemon(tmp_path, DaemonConfig.resolve(root=tmp_path))


def _record_simple_run(daemon, cmd, *, run_id="orig1111"):
    """Submit a real run, wait for it to finish, return the manifest."""
    jid = daemon.run_command(cmd, track_artifacts=False)
    _run_to_terminal(daemon, jid)
    time.sleep(0.4)  # let the journal flush
    m = daemon.runstore.read_manifest(jid)
    # Rename to a predictable id for lineage testing (write under a stable id).
    m["id"] = run_id
    daemon.runstore.write_manifest(run_id, m)
    return run_id, m


# ── rerun_run basic behaviour ─────────────────────────────────────────


def test_rerun_run_launches_new_run(tmp_path):
    """rerun_run returns a new_run_id that is different from the original."""
    d = _make_daemon(tmp_path)
    jid = d.run_command(["python", "-c", "print('original')"], track_artifacts=False)
    _run_to_terminal(d, jid)
    time.sleep(0.4)

    result = d.rerun_run(jid, overrides={})
    assert result["parent_id"] == jid
    new_id = result["new_run_id"]
    assert new_id and new_id != jid


def test_rerun_run_records_rerun_of_in_spec(tmp_path):
    """The new run's manifest must record spec.rerun_of == original run id."""
    d = _make_daemon(tmp_path)
    jid = d.run_command(["python", "-c", "print('x')"], track_artifacts=False)
    _run_to_terminal(d, jid)
    time.sleep(0.4)

    result = d.rerun_run(jid, overrides={})
    new_id = result["new_run_id"]
    _run_to_terminal(d, new_id)
    time.sleep(0.4)

    new_m = d.runstore.read_manifest(new_id) or {}
    spec = new_m.get("spec") or {}
    # Parent link preserved: spec.rerun_of == original run id.
    assert spec.get("rerun_of") == jid


def test_rerun_run_overrides_cmd(tmp_path):
    """When overrides include cmd, the new run uses the overridden command."""
    d = _make_daemon(tmp_path)
    jid = d.run_command(["python", "-c", "print('original')"], track_artifacts=False)
    _run_to_terminal(d, jid)
    time.sleep(0.4)

    new_cmd = ["python", "-c", "print('overridden')"]
    result = d.rerun_run(jid, overrides={"cmd": new_cmd})
    new_id = result["new_run_id"]
    _run_to_terminal(d, new_id)
    time.sleep(0.4)

    # The result dict reflects the override.
    assert result["command"] == new_cmd

    # The new run's manifest spec also reflects the override.
    new_m = d.runstore.read_manifest(new_id) or {}
    spec = new_m.get("spec") or {}
    assert spec.get("cmd") == new_cmd
    # Parent link is still there.
    assert spec.get("rerun_of") == jid


def test_rerun_run_overrides_cwd(tmp_path):
    """When overrides include cwd, the new run's manifest cwd reflects it."""
    import os

    d = _make_daemon(tmp_path)
    jid = d.run_command(["python", "-c", "import os; print(os.getcwd())"],
                        track_artifacts=False)
    _run_to_terminal(d, jid)
    time.sleep(0.4)

    alt_cwd = str(tmp_path)
    result = d.rerun_run(jid, overrides={"cwd": alt_cwd})
    assert result["cwd"] == alt_cwd


def test_rerun_run_kwarg_cwd_takes_precedence(tmp_path):
    """The cwd keyword argument takes precedence over overrides['cwd']."""
    d = _make_daemon(tmp_path)
    jid = d.run_command(["python", "-c", "print('y')"], track_artifacts=False)
    _run_to_terminal(d, jid)
    time.sleep(0.4)

    kwarg_cwd = str(tmp_path)
    result = d.rerun_run(jid, overrides={"cwd": "/should/be/ignored"},
                         cwd=kwarg_cwd)
    assert result["cwd"] == kwarg_cwd


def test_rerun_run_unknown_id_raises(tmp_path):
    """rerun_run raises ValueError with a clear message for unknown run ids."""
    d = _make_daemon(tmp_path)
    with pytest.raises(ValueError, match="no recorded run"):
        d.rerun_run("does-not-exist-xyz", overrides={})


def test_rerun_run_no_cmd_raises(tmp_path):
    """rerun_run raises ValueError when the original run has no recorded cmd."""
    d = _make_daemon(tmp_path)
    rs = d.runstore
    rs.runs_dir.mkdir(parents=True, exist_ok=True)
    # Craft a manifest with no cmd.
    nocmd_id = "nocmd-run"
    rs.write_manifest(nocmd_id, build_manifest(
        run_id=nocmd_id,
        name="nocmd",
        kind="callable",
        status="succeeded",
        root=str(tmp_path),
        spec={},          # no cmd field
        provenance={},
    ))
    with pytest.raises(ValueError, match="no recorded command"):
        d.rerun_run(nocmd_id, overrides={})


# ── rerun preserves lineage (spec.rerun_of) ───────────────────────────


def test_rerun_run_extra_overrides_forwarded_to_spec(tmp_path):
    """Arbitrary extra keys in overrides are forwarded into the new run's spec."""
    d = _make_daemon(tmp_path)
    jid = d.run_command(["python", "-c", "print('z')"], track_artifacts=False)
    _run_to_terminal(d, jid)
    time.sleep(0.4)

    result = d.rerun_run(jid, overrides={"my_custom_key": "my_value"})
    new_id = result["new_run_id"]
    _run_to_terminal(d, new_id)
    time.sleep(0.4)

    new_m = d.runstore.read_manifest(new_id) or {}
    spec = new_m.get("spec") or {}
    assert spec.get("my_custom_key") == "my_value"
    assert spec.get("rerun_of") == jid
