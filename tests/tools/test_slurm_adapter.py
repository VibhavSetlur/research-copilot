"""SLURM adapter tests with subprocess fakes."""

from pathlib import Path
from types import SimpleNamespace

import research_os.tools.actions.exec.cluster as cluster


class _FakeProc(SimpleNamespace):
    pass


def test_submit_slurm_success(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cluster, "_has_slurm", lambda: True)
    monkeypatch.setattr(cluster.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0, stdout="Submitted batch job 12345\n", stderr=""))
    monkeypatch.setattr(cluster, "_cfg_defaults", lambda root: {})
    res = cluster.submit_slurm(tmp_path, cmd="python run.py")
    assert res["status"] == "success"
    assert res["job_id"] == "12345"
    assert (tmp_path / ".os_state" / "cluster" / "jobs" / "12345.json").exists()


def test_submit_slurm_offline_refuses(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cluster, "_has_slurm", lambda: True)
    res = cluster.submit_slurm(tmp_path, cmd="python run.py", offline=True)
    assert res["status"] == "error"
    assert res["offline"] is True


def test_status_slurm_maps_squeue_json(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cluster, "_has_slurm", lambda: True)
    monkeypatch.setattr(cluster.shutil, "which", lambda name: "/usr/bin/squeue" if name == "squeue" else None)
    monkeypatch.setattr(cluster.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0, stdout='RUNNING|00:01:00|none\n', stderr=""))
    res = cluster.status_slurm(tmp_path, job_id="12345")
    assert res["status"] == "success"
    job = res["jobs"][0]
    assert job["live"]["state"] == "RUNNING"


def test_status_slurm_handles_live_missing_and_sacct_query(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cluster, "_has_slurm", lambda: True)
    calls = []

    def fake_which(name):
        calls.append(name)
        return "/usr/bin/sacct" if name == "sacct" else None

    monkeypatch.setattr(cluster.shutil, "which", fake_which)
    monkeypatch.setattr(cluster.subprocess, "run", lambda *a, **k: _FakeProc(returncode=0, stdout="", stderr=""))
    res = cluster.status_slurm(tmp_path, job_id="9")
    assert res["status"] == "success"
    assert res["jobs"][0]["live"] is None
    assert "sacct" in calls


def test_status_slurm_missing_binaries_warns(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cluster, "_has_slurm", lambda: True)
    monkeypatch.setattr(cluster.shutil, "which", lambda name: None)
    res = cluster.status_slurm(tmp_path, job_id="9")
    assert res["status"] == "success"
    assert res["jobs"][0]["live"] is None
