"""Tests for EventBus JSONL persistence and Phase-6 event-kind constants.

Covers:
- Publishing with persist_path writes valid JSONL (parseable, correct kind/data).
- persist_path=None behaves exactly as before (no file created).
- publish() never raises even when the persist path is un-writable.
- replay() returns events, respects the `since` filter, returns [] for missing file.
- PHASE6_EVENT_KINDS contains exactly the 7 expected kinds.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from research_os.daemon.events import (
    GATE_PENDING,
    GATE_RESOLVED,
    MEMORY_STORED,
    PHASE6_EVENT_KINDS,
    PROTOCOL_STEP_STARTED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    EventBus,
    replay,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _read_jsonl(path: Path) -> list[dict]:
    """Parse all non-empty lines in a JSONL file."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ── PHASE6_EVENT_KINDS ────────────────────────────────────────────────────────


def test_phase6_event_kinds_count():
    assert len(PHASE6_EVENT_KINDS) == 7


def test_phase6_event_kinds_contains_all():
    expected = {
        "run.started",
        "run.completed",
        "run.failed",
        "protocol.step_started",
        "gate.pending",
        "gate.resolved",
        "memory.stored",
    }
    assert PHASE6_EVENT_KINDS == expected


def test_named_constants_match_frozenset():
    """Each named constant must appear in PHASE6_EVENT_KINDS."""
    for const in (
        RUN_STARTED,
        RUN_COMPLETED,
        RUN_FAILED,
        PROTOCOL_STEP_STARTED,
        GATE_PENDING,
        GATE_RESOLVED,
        MEMORY_STORED,
    ):
        assert const in PHASE6_EVENT_KINDS, f"{const!r} missing from PHASE6_EVENT_KINDS"


# ── persist_path=None (backward-compat) ──────────────────────────────────────


def test_no_persist_path_no_file(tmp_path: Path):
    bus = EventBus()
    bus.publish(RUN_STARTED, {"run_id": "r1", "command": "python", "cwd": "/tmp"})
    # No file should have been created anywhere in tmp_path (nothing to check,
    # but the bus must work without error).
    assert bus.last_seq == 1


def test_no_persist_path_does_not_create_file(tmp_path: Path):
    candidate = tmp_path / "events.jsonl"
    bus = EventBus()  # no persist_path
    bus.publish("test.event", {"x": 1})
    assert not candidate.exists()


# ── persist_path set — happy path ────────────────────────────────────────────


def test_persist_writes_jsonl(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)
    bus.publish(RUN_STARTED, {"run_id": "abc", "command": "echo hi", "cwd": "/tmp"})
    bus.publish(RUN_COMPLETED, {"run_id": "abc", "exit_code": 0, "duration": 1.2, "artifacts": []})

    assert p.exists()
    records = _read_jsonl(p)
    assert len(records) == 2


def test_persist_event_fields(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)
    bus.publish(GATE_PENDING, {"gate_id": "g1", "question": "proceed?"}, root="proj-x")

    records = _read_jsonl(p)
    assert len(records) == 1
    rec = records[0]
    assert rec["kind"] == GATE_PENDING
    assert rec["root"] == "proj-x"
    assert rec["data"]["gate_id"] == "g1"
    assert rec["data"]["question"] == "proceed?"
    assert isinstance(rec["seq"], int) and rec["seq"] >= 1
    assert isinstance(rec["ts"], float)


def test_persist_monotonic_seq(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)
    for kind in (RUN_STARTED, PROTOCOL_STEP_STARTED, GATE_RESOLVED, MEMORY_STORED):
        bus.publish(kind, {})

    records = _read_jsonl(p)
    seqs = [r["seq"] for r in records]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 4  # all unique


def test_persist_creates_parent_dirs(tmp_path: Path):
    p = tmp_path / "deep" / "nested" / "events.jsonl"
    bus = EventBus(persist_path=p)
    bus.publish(MEMORY_STORED, {"record_id": "r1", "kind": "note"})
    assert p.exists()
    records = _read_jsonl(p)
    assert records[0]["kind"] == MEMORY_STORED


def test_persist_appends_across_instances(tmp_path: Path):
    """A second bus pointing at the same file appends, not overwrites."""
    p = tmp_path / "events.jsonl"
    bus1 = EventBus(persist_path=p)
    bus1.publish(RUN_STARTED, {"run_id": "r1"})

    bus2 = EventBus(persist_path=p)
    bus2.publish(RUN_FAILED, {"run_id": "r1", "error": "oom", "exit_code": 1})

    records = _read_jsonl(p)
    assert len(records) == 2
    assert records[0]["kind"] == RUN_STARTED
    assert records[1]["kind"] == RUN_FAILED


# ── publish never raises on bad paths ────────────────────────────────────────


def test_publish_never_raises_on_unwritable_path(tmp_path: Path):
    """Point persist_path at a path whose parent is a *file* — must not raise."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir")
    bad_path = blocker / "events.jsonl"  # parent is a file → mkdir will fail

    # Construction must not raise.
    bus = EventBus(persist_path=bad_path)

    # publish must not raise regardless.
    event = bus.publish(RUN_STARTED, {"run_id": "x"})
    assert event.seq == 1


def test_publish_never_raises_when_persist_path_becomes_unwritable(tmp_path: Path):
    """Even if the file becomes unwritable after init, publish must not raise."""
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)
    bus.publish(RUN_STARTED, {})

    # Make the file read-only.
    p.chmod(0o444)
    try:
        # publish must still not raise
        event = bus.publish(RUN_COMPLETED, {"exit_code": 0})
        assert event.seq == 2
    finally:
        p.chmod(0o644)  # restore so tmp_path cleanup works


# ── heartbeat sentinels NOT persisted ────────────────────────────────────────


def test_heartbeats_not_persisted(tmp_path: Path):
    """Heartbeat events (seq=-1) come from subscribe(), not publish(), so the
    JSONL file must only contain real events with seq >= 1."""
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)
    bus.publish(GATE_RESOLVED, {"gate_id": "g2", "decision": "approve"})

    records = _read_jsonl(p)
    assert all(r["seq"] >= 1 for r in records)
    assert all(r["kind"] != "heartbeat" for r in records)


# ── replay() ─────────────────────────────────────────────────────────────────


def test_replay_missing_file(tmp_path: Path):
    result = replay(tmp_path / "nonexistent.jsonl")
    assert result == []


def test_replay_returns_all(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)
    bus.publish(RUN_STARTED, {"run_id": "r1"})
    bus.publish(RUN_COMPLETED, {"run_id": "r1", "exit_code": 0})

    result = replay(p)
    assert len(result) == 2
    assert result[0]["kind"] == RUN_STARTED
    assert result[1]["kind"] == RUN_COMPLETED


def test_replay_since_filter(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)

    bus.publish(RUN_STARTED, {"run_id": "r1"})
    time.sleep(0.01)
    t_mid = time.time()
    time.sleep(0.01)
    bus.publish(RUN_COMPLETED, {"run_id": "r1", "exit_code": 0})

    # Only the second event should be returned.
    result = replay(p, since=t_mid)
    assert len(result) == 1
    assert result[0]["kind"] == RUN_COMPLETED


def test_replay_since_none_returns_all(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)
    for kind in (RUN_STARTED, PROTOCOL_STEP_STARTED, GATE_PENDING):
        bus.publish(kind, {})

    result = replay(p, since=None)
    assert len(result) == 3


def test_replay_skips_malformed_lines(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    bus = EventBus(persist_path=p)
    bus.publish(MEMORY_STORED, {"record_id": "m1", "kind": "note"})

    # Inject a malformed line between two valid ones.
    good_line = p.read_text()
    p.write_text(good_line + "NOT JSON !!!\n" + good_line)

    result = replay(p)
    assert len(result) == 2  # malformed line skipped, two valid ones returned


def test_replay_empty_file(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    p.write_text("")
    assert replay(p) == []
