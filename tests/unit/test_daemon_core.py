"""Unit tests for the v4 daemon core (research_os.daemon.core).

Covers the Daemon holder, the DaemonStatus snapshot (uninitialized vs.
initialized project), the not-yet-implemented serve() contract, and the
lazy-import discipline (importing the package must not pull the heavy web
serving stack).
"""
from __future__ import annotations

import sys

import pytest

from research_os.daemon import Daemon, DaemonConfig, DaemonStatus


def test_package_import_does_not_pull_heavy_web_deps():
    """`import research_os.daemon` must stay cheap — no starlette/uvicorn.

    The serving stack lives in the optional [daemon] extra and is imported
    lazily by later phases. Importing the package at all must never require
    it (core-only installs must work).

    Run in a FRESH subprocess: a shared interpreter's sys.modules is
    polluted by other tests that legitimately import starlette, so the only
    robust way to test our import-time discipline is process isolation.
    """
    import subprocess

    code = (
        "import sys, research_os.daemon\n"
        "leaked = [m for m in ('starlette', 'uvicorn', 'sse_starlette') "
        "if m in sys.modules]\n"
        "print(','.join(leaked))\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, f"import failed: {res.stderr}"
    leaked = res.stdout.strip()
    assert not leaked, f"daemon import leaked heavy web deps: {leaked}"


def test_for_root_builds_daemon_with_config(tmp_path):
    d = Daemon.for_root(tmp_path, port=4242)
    assert d.root == tmp_path
    assert isinstance(d.config, DaemonConfig)
    assert d.config.port == 4242
    assert d.serving is False


def test_status_uninitialized_project(tmp_path):
    d = Daemon.for_root(tmp_path)
    status = d.status()
    assert isinstance(status, DaemonStatus)
    assert status.serving is False
    assert status.project_initialized is False
    assert status.root == str(tmp_path)
    assert any("os_state" in n for n in status.notes)
    # serializable
    assert status.to_dict()["project_initialized"] is False


def test_status_with_none_root():
    d = Daemon(root=None, config=DaemonConfig())
    status = d.status()
    assert status.root is None
    assert status.project_initialized is False
    assert any("no project root" in n for n in status.notes)


def test_status_initialized_project_reads_state(tmp_path):
    """An initialized project (has .os_state) reports initialized + no
    spurious 'run init' note, and never raises while reading engine state."""
    (tmp_path / ".os_state").mkdir()
    d = Daemon.for_root(tmp_path)
    status = d.status()
    assert status.project_initialized is True
    assert not any("run 'research-os init'" in n for n in status.notes)
    # progress is always a dict; active_protocol is str|None
    assert isinstance(status.progress, dict)
    assert status.active_protocol is None or isinstance(status.active_protocol, str)


def test_status_includes_config_block(tmp_path):
    d = Daemon.for_root(tmp_path, host="127.0.0.1", port=8787)
    cfg = d.status().to_dict()["config"]
    assert cfg["base_url"] == "http://127.0.0.1:8787"
    assert cfg["sandbox_mode"] == "auto"
    assert cfg["auth_token_env"] == "RESEARCH_OS_DAEMON_TOKEN"


def test_serve_is_implemented(tmp_path):
    """Phase 1: serve() is real — it must NOT raise NotImplementedError.

    We don't actually bind a port here (that blocks); we assert the method
    exists, is wired to the lazy server module, and builds a valid ASGI app
    for this daemon. The real bind/serve loop is exercised via the HTTP
    endpoint tests (test_daemon_server.py) against a TestClient.
    """
    (tmp_path / ".os_state").mkdir()
    d = Daemon.for_root(tmp_path)
    # serve() must be callable and not the Phase-0 stub.
    import inspect

    src = inspect.getsource(d.serve)
    assert "NotImplementedError" not in src
    # The lazy server module builds a working app from this daemon.
    pytest.importorskip("starlette")
    from research_os.daemon.server import build_app

    app = build_app(d)
    assert app is not None


def test_autoresolve_returns_daemon(monkeypatch, tmp_path):
    """autoresolve uses the server's resolver; force it to tmp_path."""
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE", str(tmp_path))
    d = Daemon.autoresolve()
    assert d.root == tmp_path.resolve()


# ── resumable runs (Phase 4) ──────────────────────────────────────────

def _run_to_terminal(daemon, job_id, timeout=30.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = daemon.tasks.get(job_id)
        if j and j.status.value in ("succeeded", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_resume_run_relaunches_interrupted_spec(tmp_path):
    daemon = Daemon(tmp_path, DaemonConfig.resolve(root=tmp_path))
    jid = daemon.run_command(["python", "-c", "print('hi')"], track_artifacts=False)
    _run_to_terminal(daemon, jid)
    import time
    time.sleep(0.4)  # let the journal flush the manifest
    m = daemon.runstore.read_manifest(jid)
    m["status"] = "interrupted"
    daemon.runstore.write_manifest(jid, m)

    res = daemon.resume_run(jid)
    assert res["resumed_from"] == jid
    assert res["new_run_id"] and res["new_run_id"] != jid
    assert "checkpoint" in res["checkpoint_dir"]
    # The new run records its linkage back to the original (in its spec, which
    # the journal persists natively).
    _run_to_terminal(daemon, res["new_run_id"])
    time.sleep(0.4)
    new_m = daemon.runstore.read_manifest(res["new_run_id"]) or {}
    spec = new_m.get("spec") or {}
    assert spec.get("resumed_from") == jid or new_m.get("resumed_from") == jid


def test_resume_run_scheduler_redispatches_via_scheduler(tmp_path):
    """F-3 (4.0.2): a scheduler (SLURM) run must resume via submit_job (sbatch),
    NOT be re-launched as a local subprocess on the daemon host."""
    daemon = Daemon(tmp_path, DaemonConfig.resolve(root=tmp_path))
    # craft an interrupted scheduler manifest
    rs = daemon.runstore
    rs.runs_dir.mkdir(parents=True, exist_ok=True)
    rid = "sched1"
    (rs.runs_dir / rid).mkdir(exist_ok=True)
    rs.write_manifest(rid, {
        "id": rid, "name": rid, "kind": "scheduler", "status": "interrupted",
        "spec": {"script": "train.sh", "scheduler": "slurm", "cmd": ["train.sh"]},
        "transitions": [], "provenance": {},
    })
    calls = {}
    daemon.submit_job = lambda script, **kw: calls.update(script=script, kw=kw) or "new-sched"
    daemon.run_command = lambda *a, **k: calls.update(LOCAL=True) or "WRONG"
    res = daemon.resume_run(rid)
    assert calls.get("script") == "train.sh"
    assert calls.get("kw", {}).get("scheduler") == "slurm"
    assert "LOCAL" not in calls  # never fell through to the local path
    assert res["new_run_id"] == "new-sched"


def test_resume_run_rejects_unknown(tmp_path):
    import pytest
    daemon = Daemon(tmp_path, DaemonConfig.resolve(root=tmp_path))
    with pytest.raises(ValueError, match="no recorded run"):
        daemon.resume_run("does-not-exist")


def test_resume_run_rejects_succeeded(tmp_path):
    """A run that completed normally is not resumable."""
    daemon = Daemon(tmp_path, DaemonConfig.resolve(root=tmp_path))
    jid = daemon.run_command(["python", "-c", "print('ok')"], track_artifacts=False)
    _run_to_terminal(daemon, jid)
    import time
    time.sleep(0.4)
    import pytest
    with pytest.raises(ValueError, match="not resumable"):
        daemon.resume_run(jid)


def test_resume_run_refuses_when_original_pid_alive(tmp_path):
    """F-4 (4.0.2): if the original run's recorded PID is still alive on this
    host, resume_run must refuse rather than spawn a duplicate."""
    import os
    import socket

    import pytest

    daemon = Daemon(tmp_path, DaemonConfig.resolve(root=tmp_path))
    rs = daemon.runstore
    rs.runs_dir.mkdir(parents=True, exist_ok=True)
    rs.write_manifest("live1", {
        "id": "live1", "name": "x", "kind": "callable", "status": "interrupted",
        "spec": {"cmd": ["echo", "hi"]}, "pid": os.getpid(),
        "host": socket.gethostname(), "transitions": [], "provenance": {},
    })
    with pytest.raises(ValueError, match="live process"):
        daemon.resume_run("live1")

    # a dead PID resumes normally
    rs.write_manifest("dead1", {
        "id": "dead1", "name": "x", "kind": "callable", "status": "interrupted",
        "spec": {"cmd": ["echo", "hi"]}, "pid": 999999,
        "host": socket.gethostname(), "transitions": [], "provenance": {},
    })
    res = daemon.resume_run("dead1")
    assert res["new_run_id"]


def test_self_check_interval_config_default():
    """B1: daemon has a periodic self-check interval (default 5 min, 0 disables)."""
    from research_os.daemon.config import DaemonConfig
    c = DaemonConfig.resolve()
    assert c.self_check_interval == 300.0


def test_serve_starts_periodic_self_check_thread(tmp_path, monkeypatch):
    """B1: serve() launches a background thread that re-runs write_notes."""
    import threading as _t
    from research_os.daemon import core as _core
    from research_os.daemon.config import DaemonConfig

    calls = {"n": 0}

    # Fast interval; stub the web serve so it returns immediately after we let
    # the tick fire once.
    cfg = DaemonConfig.resolve(root=tmp_path)
    object.__setattr__(cfg, "self_check_interval", 0.05)
    d = _core.Daemon(tmp_path, cfg)

    import research_os.daemon.health_notes as _h
    monkeypatch.setattr(_h, "write_notes", lambda root: calls.__setitem__("n", calls["n"] + 1))

    # Make the blocking serve return after a short sleep so the tick runs.
    import research_os.daemon.server as _srv
    def _fake_serve(daemon):
        import time as _time
        _time.sleep(0.2)
    monkeypatch.setattr(_srv, "serve", _fake_serve)
    monkeypatch.setattr(_srv, "_require_web_stack", lambda: None)

    d.serve()
    assert calls["n"] >= 1  # the periodic tick fired at least once
