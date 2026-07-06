"""Tests for §12.2 (CAS wiring) and §12.3 (environment snapshot).

Covers:
- capture_environment() schema and graceful degradation
- environment snapshot attached to every run manifest
- archive_artifacts_to_cas() helper — blob stored, artifact annotated
- CAS failure does not corrupt the run manifest
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_os.daemon.provenance import capture_environment
from research_os.daemon.runstore import (
    RunJournal,
    RunStore,
    archive_artifacts_to_cas,
    build_manifest,
)


# ── §12.3 capture_environment() ───────────────────────────────────────────────


def test_capture_environment_returns_dict():
    snap = capture_environment()
    assert isinstance(snap, dict)


def test_capture_environment_required_keys():
    snap = capture_environment()
    assert snap.get("schema_version") == "1.0"
    assert "platform" in snap
    assert "python_version" in snap


def test_capture_environment_pip_freeze_is_list_if_present():
    snap = capture_environment()
    if "pip_freeze" in snap:
        assert isinstance(snap["pip_freeze"], list)
        # Each entry should be a non-empty string (e.g. "pkg==1.0")
        for line in snap["pip_freeze"]:
            assert isinstance(line, str)


def test_capture_environment_conda_export_is_list_if_present():
    snap = capture_environment()
    if "conda_export" in snap:
        assert isinstance(snap["conda_export"], list)


def test_capture_environment_never_raises_when_pip_fails(monkeypatch):
    """Monkeypatching subprocess.check_output to always raise must not raise
    capture_environment — both pip_freeze and conda_export are simply omitted."""
    import subprocess

    def _raise(*args, **kwargs):
        raise FileNotFoundError("mocked: pip not found")

    monkeypatch.setattr(subprocess, "check_output", _raise)

    snap = capture_environment()
    # Must return a dict with the required fields — no raise
    assert isinstance(snap, dict)
    assert snap.get("schema_version") == "1.0"
    # Optional keys must be absent (not None, absent)
    assert "pip_freeze" not in snap
    assert "conda_export" not in snap


def test_capture_environment_pip_timeout_graceful(monkeypatch):
    """A subprocess.TimeoutExpired must be swallowed."""
    import subprocess

    call_count = [0]

    def _timeout_then_ok(*args, **kwargs):
        call_count[0] += 1
        raise subprocess.TimeoutExpired(cmd="pip", timeout=30)

    monkeypatch.setattr(subprocess, "check_output", _timeout_then_ok)

    snap = capture_environment()
    assert isinstance(snap, dict)
    assert snap.get("schema_version") == "1.0"


def test_capture_environment_partial_failure_pip_ok_conda_fails(monkeypatch):
    """If pip succeeds but conda fails, pip_freeze is present, conda_export absent."""
    import subprocess

    original_check_output = subprocess.check_output

    def _selective(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        # Identify conda call by checking "conda" in first arg or list
        if isinstance(cmd, list) and "conda" in cmd:
            raise FileNotFoundError("conda not found")
        # Let pip calls through to real implementation
        return original_check_output(*args, **kwargs)

    monkeypatch.setattr(subprocess, "check_output", _selective)

    snap = capture_environment()
    assert isinstance(snap, dict)
    # pip_freeze may or may not be present (depends on real pip); conda_export absent
    assert "conda_export" not in snap


# ── environment snapshot wired into run manifest ──────────────────────────────


def _ev(kind: str, data: dict) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, data=data)


def _wait_for_env(rs: RunStore, run_id: str, timeout: float = 90.0) -> dict | None:
    """Poll until the manifest has an 'environment' key (set by background thread)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        m = rs.read_manifest(run_id)
        if m and "environment" in m:
            return m
        time.sleep(0.05)
    return rs.read_manifest(run_id)


def test_manifest_has_environment_schema_version(tmp_path):
    """A run submitted through RunJournal must have environment.schema_version == '1.0'.
    The env snapshot is captured asynchronously, so we poll until it lands."""
    rs = RunStore(tmp_path)
    j = RunJournal(rs)

    snap = {
        "id": "env-run-1",
        "name": "env-test",
        "kind": "subprocess",
        "status": "queued",
        "root": str(tmp_path),
        "spec": {"cmd": "echo hi"},
        "provenance": {},
        "submitted_at": time.time(),
    }
    j.handle(_ev("job.submitted", {"job_id": "env-run-1", "job": snap}))

    m = _wait_for_env(rs, "env-run-1")
    assert m is not None
    env = m.get("environment")
    assert env is not None, "manifest must have 'environment' key (background thread did not patch)"
    assert env.get("schema_version") == "1.0"
    assert "platform" in env
    assert "python_version" in env


def test_manifest_environment_not_recaptured_on_subsequent_transitions(tmp_path):
    """The environment snapshot is patched by a background thread on first event
    and must persist (not be overwritten) on subsequent transitions."""
    rs = RunStore(tmp_path)
    j = RunJournal(rs)

    snap = {
        "id": "env-run-2",
        "name": "env-persist",
        "kind": "subprocess",
        "status": "queued",
        "root": str(tmp_path),
        "spec": {},
        "provenance": {},
        "submitted_at": time.time(),
    }
    j.handle(_ev("job.submitted", {"job_id": "env-run-2", "job": snap}))

    # Wait for the background env-snapshot thread to patch the manifest
    m1 = _wait_for_env(rs, "env-run-2")
    assert m1 is not None
    env1 = m1.get("environment", {})

    # Transition to succeeded — the env key must still be there
    snap2 = dict(snap, status="succeeded", result={"returncode": 0})
    j.handle(_ev("job.succeeded", {"job_id": "env-run-2", "job": snap2}))
    m2 = rs.read_manifest("env-run-2")
    assert m2 is not None
    env2 = m2.get("environment", {})

    # Both must share the same schema_version (env captured once, not overwritten)
    assert env1.get("schema_version") == "1.0"
    assert env2.get("schema_version") == "1.0"


def test_build_manifest_environment_none_by_default():
    """Existing callers that don't pass environment= must get no 'environment' key."""
    m = build_manifest(
        run_id="x",
        name="n",
        kind="callable",
        status="queued",
        root=None,
    )
    assert "environment" not in m


def test_build_manifest_environment_included_when_passed():
    env = {"schema_version": "1.0", "platform": "linux-x86_64", "python_version": "3.11"}
    m = build_manifest(
        run_id="x",
        name="n",
        kind="callable",
        status="queued",
        root=None,
        environment=env,
    )
    assert m["environment"] == env


# ── §12.2 archive_artifacts_to_cas() ─────────────────────────────────────────


def test_archive_artifacts_to_cas_stores_blob(tmp_path):
    """A created artifact file is copied into the CAS; its entry gains blob_id."""
    output_file = tmp_path / "result.txt"
    content = b"experiment output"
    output_file.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    artifacts = [
        {"path": "result.txt", "change": "created", "size": len(content), "mtime": 0.0},
    ]

    updated = archive_artifacts_to_cas(tmp_path, "run-cas-1", artifacts)

    assert len(updated) == 1
    assert updated[0].get("blob_id") == expected_hash

    # Verify the blob actually landed in the CAS at the expected shard path
    blob_path = tmp_path / ".os_state" / "blobs" / expected_hash[:2] / expected_hash
    assert blob_path.exists(), f"blob not found at {blob_path}"
    assert blob_path.read_bytes() == content


def test_archive_artifacts_to_cas_blob_id_matches_sha256(tmp_path):
    """blob_id must equal the sha256 hexdigest of the file content."""
    content = b"reproducible data"
    (tmp_path / "data.bin").write_bytes(content)
    artifacts = [{"path": "data.bin", "change": "created", "size": len(content)}]

    updated = archive_artifacts_to_cas(tmp_path, "run-cas-sha", artifacts)
    assert updated[0]["blob_id"] == hashlib.sha256(content).hexdigest()


def test_archive_artifacts_to_cas_missing_file_skipped(tmp_path):
    """An artifact whose file no longer exists on disk must be skipped (no blob_id)."""
    artifacts = [{"path": "gone.txt", "change": "created", "size": 10}]

    updated = archive_artifacts_to_cas(tmp_path, "run-cas-missing", artifacts)
    assert "blob_id" not in updated[0]


def test_archive_artifacts_to_cas_none_root_returns_unchanged():
    """When root is None, artifacts are returned as-is, no CAS activity."""
    artifacts = [{"path": "f.txt", "change": "created"}]
    result = archive_artifacts_to_cas(None, "run-x", artifacts)
    assert result is artifacts  # same list object, unchanged
    assert "blob_id" not in result[0]


def test_archive_artifacts_to_cas_empty_list_no_error(tmp_path):
    result = archive_artifacts_to_cas(tmp_path, "run-empty", [])
    assert result == []


def test_archive_artifacts_to_cas_failure_does_not_raise(tmp_path):
    """If the CAS root is not writable, archive_artifacts_to_cas must not raise
    and the original artifact dicts must be intact (no blob_id, but no crash)."""
    # Make the .os_state dir exist but blobs dir unwritable
    blobs_dir = tmp_path / ".os_state" / "blobs"
    blobs_dir.mkdir(parents=True)

    content = b"some output"
    (tmp_path / "out.txt").write_bytes(content)
    artifacts = [{"path": "out.txt", "change": "created", "size": len(content)}]

    # Monkeypatch CASStore.store to raise
    from research_os.daemon import cas as _cas_mod

    original_store = _cas_mod.CASStore.store

    def _bad_store(self, path, run_id):
        raise RuntimeError("disk full")

    _cas_mod.CASStore.store = _bad_store
    try:
        # Must not raise
        updated = archive_artifacts_to_cas(tmp_path, "run-fail", artifacts)
    finally:
        _cas_mod.CASStore.store = original_store

    # The artifact dict must be intact (original fields preserved, no blob_id)
    assert updated[0]["path"] == "out.txt"
    assert "blob_id" not in updated[0]


def test_archive_artifacts_preserves_existing_fields(tmp_path):
    """Existing artifact fields (sha256, mtime, etc.) must not be removed."""
    content = b"keep fields"
    (tmp_path / "keep.txt").write_bytes(content)
    artifacts = [{
        "path": "keep.txt",
        "change": "created",
        "size": len(content),
        "mtime": 12345.0,
        "sha256": "sha256:abc",
    }]

    updated = archive_artifacts_to_cas(tmp_path, "run-fields", artifacts)

    assert updated[0]["mtime"] == 12345.0
    assert updated[0]["sha256"] == "sha256:abc"
    assert updated[0]["change"] == "created"
    assert "blob_id" in updated[0]  # was added


# ── CAS wired end-to-end through RunJournal ───────────────────────────────────


def test_journal_terminal_run_populates_blob_id(tmp_path):
    """A successful run with an output artifact must have blob_id in the manifest."""
    rs = RunStore(tmp_path)
    j = RunJournal(rs)

    # Create an output file that the "run" would have produced
    output = tmp_path / "model.pkl"
    content = b"trained model weights"
    output.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    artifact_entry = {
        "path": "model.pkl",
        "change": "created",
        "size": len(content),
        "mtime": output.stat().st_mtime,
        "sha256": f"sha256:{expected_hash}",
    }

    snap = {
        "id": "end-to-end-1",
        "name": "train",
        "kind": "subprocess",
        "status": "queued",
        "root": str(tmp_path),
        "spec": {"cmd": "python train.py"},
        "provenance": {},
        "submitted_at": time.time(),
    }
    j.handle(_ev("job.submitted", {"job_id": "end-to-end-1", "job": snap}))

    snap2 = dict(snap, status="succeeded", result={
        "returncode": 0,
        "artifacts": [artifact_entry],
    })
    j.handle(_ev("job.succeeded", {"job_id": "end-to-end-1", "job": snap2}))

    m = rs.read_manifest("end-to-end-1")
    assert m is not None
    assert m["status"] == "succeeded"
    arts = m.get("artifacts", [])
    assert len(arts) == 1
    assert arts[0].get("blob_id") == expected_hash

    # Verify the blob is on disk
    blob_path = tmp_path / ".os_state" / "blobs" / expected_hash[:2] / expected_hash
    assert blob_path.exists()
    assert blob_path.read_bytes() == content


def test_journal_cas_failure_does_not_corrupt_run(tmp_path):
    """If CAS archiving fails entirely, the run manifest is still written correctly."""
    from research_os.daemon import cas as _cas_mod

    rs = RunStore(tmp_path)
    j = RunJournal(rs)

    content = b"output data"
    (tmp_path / "out.txt").write_bytes(content)

    # Patch CASStore so every store() call raises
    original_store = _cas_mod.CASStore.store

    def _bad_store(self, path, run_id):
        raise OSError("disk full")

    _cas_mod.CASStore.store = _bad_store
    try:
        snap = {
            "id": "cas-fail-run",
            "name": "fail-cas",
            "kind": "subprocess",
            "status": "queued",
            "root": str(tmp_path),
            "spec": {},
            "provenance": {},
            "submitted_at": time.time(),
        }
        j.handle(_ev("job.submitted", {"job_id": "cas-fail-run", "job": snap}))
        snap2 = dict(snap, status="succeeded", result={
            "returncode": 0,
            "artifacts": [{"path": "out.txt", "change": "created", "size": len(content)}],
        })
        j.handle(_ev("job.succeeded", {"job_id": "cas-fail-run", "job": snap2}))
    finally:
        _cas_mod.CASStore.store = original_store

    m = rs.read_manifest("cas-fail-run")
    assert m is not None, "manifest must still be written despite CAS failure"
    assert m["status"] == "succeeded"
    arts = m.get("artifacts", [])
    assert len(arts) == 1
    # No blob_id because CAS failed, but the artifact entry is intact
    assert arts[0]["path"] == "out.txt"
