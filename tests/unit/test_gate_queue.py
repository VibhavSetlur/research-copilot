"""Unit tests for ``research_os.daemon.gates`` (GateQueue + GateRequest).

Coverage
--------
- enqueue writes <id>.json with status=pending and returns the id.
- A passed-in event_bus receives a gate.pending publish with the right payload.
- pending() returns only pending gates.
- After resolve(id, "approve") the gate is excluded from pending(); its file
  shows status=approved, decision set, resolved_at set; resolve() returns True.
- resolve(id, "reject") → status rejected, returns False.
- resolve of an unknown id → returns False, no exception.
- Persistence across "restart": a second GateQueue on the same root sees the
  same gates (state is on disk).
- get(id) and all() work correctly.
- A corrupt gate file is skipped, not fatal (pending / all / get are safe).
- gates_dir(root) returns <root>/.os_state/gates.
- enqueue with event_bus=None does not raise.
"""
from __future__ import annotations

import json


from research_os.daemon.gates import GateQueue, GateRequest, gates_dir


# ── helpers ───────────────────────────────────────────────────────────────────

class _FakeBus:
    """Minimal event bus that records publish calls for inspection."""

    def __init__(self):
        self.calls: list[dict] = []

    def publish(self, kind: str, data: dict | None = None, root: str | None = None):
        self.calls.append({"kind": kind, "data": dict(data or {}), "root": root})


def _make_request(**kwargs) -> GateRequest:
    defaults = dict(
        id="",
        protocol_id="analysis/evaluate",
        step_id="s1",
        question="Should I proceed with outlier removal?",
        root="/tmp/proj",
    )
    defaults.update(kwargs)
    return GateRequest(**defaults)


# ── gates_dir helper ──────────────────────────────────────────────────────────

def test_gates_dir_returns_canonical_path(tmp_path):
    result = gates_dir(tmp_path)
    assert result == tmp_path / ".os_state" / "gates"


def test_gates_dir_accepts_string(tmp_path):
    result = gates_dir(str(tmp_path))
    assert result == tmp_path / ".os_state" / "gates"


# ── enqueue ───────────────────────────────────────────────────────────────────

def test_enqueue_writes_json_file_with_status_pending(tmp_path):
    q = GateQueue(tmp_path)
    req = _make_request()
    gate_id = q.enqueue(req)

    file = tmp_path / ".os_state" / "gates" / f"{gate_id}.json"
    assert file.exists(), "gate file must exist after enqueue"
    data = json.loads(file.read_text())
    assert data["status"] == "pending"
    assert data["id"] == gate_id
    assert data["question"] == req.question


def test_enqueue_returns_id(tmp_path):
    q = GateQueue(tmp_path)
    req = _make_request()
    gate_id = q.enqueue(req)
    assert isinstance(gate_id, str) and len(gate_id) > 0


def test_enqueue_generates_id_when_empty(tmp_path):
    q = GateQueue(tmp_path)
    req = _make_request(id="")
    gate_id = q.enqueue(req)
    assert gate_id  # non-empty
    assert req.id == gate_id  # mutated in place


def test_enqueue_preserves_caller_id(tmp_path):
    q = GateQueue(tmp_path)
    req = _make_request(id="myfixedid")
    gate_id = q.enqueue(req)
    assert gate_id == "myfixedid"


def test_enqueue_sets_created_at_if_absent(tmp_path):
    q = GateQueue(tmp_path)
    req = _make_request(created_at="")
    q.enqueue(req)
    assert req.created_at  # stamped


def test_enqueue_preserves_created_at_if_set(tmp_path):
    q = GateQueue(tmp_path)
    req = _make_request(created_at="2026-01-01T00:00:00+00:00")
    q.enqueue(req)
    assert req.created_at == "2026-01-01T00:00:00+00:00"


# ── event_bus integration ─────────────────────────────────────────────────────

def test_enqueue_publishes_gate_pending_to_bus(tmp_path):
    bus = _FakeBus()
    q = GateQueue(tmp_path, event_bus=bus)
    req = _make_request()
    gate_id = q.enqueue(req)

    assert len(bus.calls) == 1
    call = bus.calls[0]
    assert call["kind"] == "gate.pending"
    assert call["data"]["gate_id"] == gate_id
    assert call["data"]["question"] == req.question
    assert call["root"] == req.root


def test_enqueue_with_no_bus_does_not_raise(tmp_path):
    q = GateQueue(tmp_path, event_bus=None)
    req = _make_request()
    gate_id = q.enqueue(req)  # must not raise
    assert gate_id


def test_enqueue_with_broken_bus_does_not_raise(tmp_path):
    class _BrokenBus:
        def publish(self, *a, **kw):
            raise RuntimeError("bus exploded")

    q = GateQueue(tmp_path, event_bus=_BrokenBus())
    req = _make_request()
    gate_id = q.enqueue(req)  # must not raise
    assert gate_id


# ── pending() ────────────────────────────────────────────────────────────────

def test_pending_returns_only_pending_gates(tmp_path):
    q = GateQueue(tmp_path)
    id1 = q.enqueue(_make_request(question="Q1"))
    id2 = q.enqueue(_make_request(question="Q2"))

    pend = q.pending()
    ids = {g.id for g in pend}
    assert id1 in ids and id2 in ids
    assert all(g.status == "pending" for g in pend)


def test_pending_excludes_resolved_gates(tmp_path):
    q = GateQueue(tmp_path)
    id1 = q.enqueue(_make_request(question="Q1"))
    _id2 = q.enqueue(_make_request(question="Q2"))
    q.resolve(id1, "approve")

    pend = q.pending()
    assert all(g.id != id1 for g in pend)


def test_pending_empty_when_none(tmp_path):
    q = GateQueue(tmp_path)
    assert q.pending() == []


# ── resolve — approve ─────────────────────────────────────────────────────────

def test_resolve_approve_returns_true(tmp_path):
    q = GateQueue(tmp_path)
    gate_id = q.enqueue(_make_request())
    result = q.resolve(gate_id, "approve")
    assert result is True


def test_resolve_approve_updates_file(tmp_path):
    q = GateQueue(tmp_path)
    gate_id = q.enqueue(_make_request())
    q.resolve(gate_id, "approve")

    file = tmp_path / ".os_state" / "gates" / f"{gate_id}.json"
    data = json.loads(file.read_text())
    assert data["status"] == "approved"
    assert data["decision"] == "approve"
    assert data["resolved_at"]  # non-empty timestamp


def test_resolve_approve_removes_from_pending(tmp_path):
    q = GateQueue(tmp_path)
    gate_id = q.enqueue(_make_request())
    q.resolve(gate_id, "approve")
    assert all(g.id != gate_id for g in q.pending())


def test_resolve_approve_publishes_gate_resolved(tmp_path):
    bus = _FakeBus()
    q = GateQueue(tmp_path, event_bus=bus)
    gate_id = q.enqueue(_make_request())
    bus.calls.clear()  # clear the enqueue publish

    q.resolve(gate_id, "approve")
    assert len(bus.calls) == 1
    call = bus.calls[0]
    assert call["kind"] == "gate.resolved"
    assert call["data"]["gate_id"] == gate_id
    assert call["data"]["decision"] == "approve"


# ── resolve — reject ──────────────────────────────────────────────────────────

def test_resolve_reject_returns_false(tmp_path):
    q = GateQueue(tmp_path)
    gate_id = q.enqueue(_make_request())
    result = q.resolve(gate_id, "reject")
    assert result is False


def test_resolve_reject_updates_file(tmp_path):
    q = GateQueue(tmp_path)
    gate_id = q.enqueue(_make_request())
    q.resolve(gate_id, "reject")

    file = tmp_path / ".os_state" / "gates" / f"{gate_id}.json"
    data = json.loads(file.read_text())
    assert data["status"] == "rejected"
    assert data["decision"] == "reject"
    assert data["resolved_at"]


# ── resolve — unknown id ──────────────────────────────────────────────────────

def test_resolve_unknown_id_returns_false(tmp_path):
    q = GateQueue(tmp_path)
    result = q.resolve("nonexistent_id", "approve")
    assert result is False


def test_resolve_unknown_id_does_not_raise(tmp_path):
    q = GateQueue(tmp_path)
    q.resolve("does_not_exist", "reject")  # must not raise


# ── get() ─────────────────────────────────────────────────────────────────────

def test_get_returns_gate_by_id(tmp_path):
    q = GateQueue(tmp_path)
    gate_id = q.enqueue(_make_request(question="Is it safe?"))
    gr = q.get(gate_id)
    assert gr is not None
    assert gr.id == gate_id
    assert gr.question == "Is it safe?"


def test_get_returns_none_for_unknown_id(tmp_path):
    q = GateQueue(tmp_path)
    assert q.get("no-such-gate") is None


def test_get_after_resolve_shows_new_status(tmp_path):
    q = GateQueue(tmp_path)
    gate_id = q.enqueue(_make_request())
    q.resolve(gate_id, "approve")
    gr = q.get(gate_id)
    assert gr is not None
    assert gr.status == "approved"


# ── all() ─────────────────────────────────────────────────────────────────────

def test_all_returns_all_gates_regardless_of_status(tmp_path):
    q = GateQueue(tmp_path)
    id1 = q.enqueue(_make_request(question="Q1"))
    id2 = q.enqueue(_make_request(question="Q2"))
    q.resolve(id1, "approve")

    gates = q.all()
    ids = {g.id for g in gates}
    assert id1 in ids and id2 in ids


def test_all_is_newest_first(tmp_path):
    """Gates with a later created_at come first."""
    import time
    q = GateQueue(tmp_path)
    req1 = _make_request(created_at="2026-01-01T00:00:00+00:00", question="Q1")
    req2 = _make_request(created_at="2026-06-01T00:00:00+00:00", question="Q2")
    q.enqueue(req1)
    time.sleep(0.01)
    q.enqueue(req2)

    gates = q.all()
    # req2 (2026-06) should come before req1 (2026-01)
    assert gates[0].question == "Q2"
    assert gates[1].question == "Q1"


def test_all_respects_limit(tmp_path):
    q = GateQueue(tmp_path)
    for i in range(5):
        q.enqueue(_make_request(question=f"Q{i}"))
    assert len(q.all(limit=3)) == 3


def test_all_empty_when_none(tmp_path):
    q = GateQueue(tmp_path)
    assert q.all() == []


# ── persistence across restart ────────────────────────────────────────────────

def test_pending_gates_survive_restart(tmp_path):
    q1 = GateQueue(tmp_path)
    id1 = q1.enqueue(_make_request(question="Will this persist?"))

    # Simulate daemon restart by constructing a fresh GateQueue on same root
    q2 = GateQueue(tmp_path)
    pend = q2.pending()
    ids = {g.id for g in pend}
    assert id1 in ids


def test_resolved_state_survives_restart(tmp_path):
    q1 = GateQueue(tmp_path)
    gate_id = q1.enqueue(_make_request())
    q1.resolve(gate_id, "approve")

    q2 = GateQueue(tmp_path)
    assert q2.pending() == []  # not in pending after restart
    gr = q2.get(gate_id)
    assert gr is not None
    assert gr.status == "approved"
    assert gr.resolved_at


def test_mixed_state_survives_restart(tmp_path):
    q1 = GateQueue(tmp_path)
    id_pend = q1.enqueue(_make_request(question="Pending one"))
    id_done = q1.enqueue(_make_request(question="Resolved one"))
    q1.resolve(id_done, "reject")

    q2 = GateQueue(tmp_path)
    pend = {g.id for g in q2.pending()}
    assert id_pend in pend
    assert id_done not in pend

    all_gates = {g.id for g in q2.all()}
    assert id_pend in all_gates
    assert id_done in all_gates


# ── corrupt file resilience ───────────────────────────────────────────────────

def test_corrupt_gate_file_is_skipped_in_pending(tmp_path):
    q = GateQueue(tmp_path)
    good_id = q.enqueue(_make_request(question="Good gate"))

    # Inject a corrupt file
    bad_file = tmp_path / ".os_state" / "gates" / "badf00d.json"
    bad_file.write_text("{{not valid json", encoding="utf-8")

    # Should not raise; corrupt file silently skipped
    pend = q.pending()
    ids = {g.id for g in pend}
    assert good_id in ids
    assert "badf00d" not in ids


def test_corrupt_gate_file_is_skipped_in_all(tmp_path):
    q = GateQueue(tmp_path)
    good_id = q.enqueue(_make_request(question="Good gate"))

    bad_file = tmp_path / ".os_state" / "gates" / "corrupt1.json"
    bad_file.write_text("not json at all", encoding="utf-8")

    gates = q.all()
    ids = {g.id for g in gates}
    assert good_id in ids
    assert "corrupt1" not in ids


def test_get_corrupt_file_returns_none(tmp_path):
    gdir = tmp_path / ".os_state" / "gates"
    gdir.mkdir(parents=True, exist_ok=True)
    bad = gdir / "corruptgate.json"
    bad.write_text("{bad", encoding="utf-8")

    q = GateQueue(tmp_path)
    assert q.get("corruptgate") is None


# ── GateRequest dataclass helpers ─────────────────────────────────────────────

def test_gate_request_round_trips_through_dict():
    req = GateRequest(
        id="abc123",
        protocol_id="analysis/evaluate",
        step_id="step2",
        question="Proceed?",
        status="approved",
        created_at="2026-01-01T00:00:00+00:00",
        resolved_at="2026-01-01T01:00:00+00:00",
        decision="approve",
        root="/proj",
    )
    d = req.to_dict()
    req2 = GateRequest.from_dict(d)
    assert req2.id == req.id
    assert req2.protocol_id == req.protocol_id
    assert req2.step_id == req.step_id
    assert req2.question == req.question
    assert req2.status == req.status
    assert req2.created_at == req.created_at
    assert req2.resolved_at == req.resolved_at
    assert req2.decision == req.decision
    assert req2.root == req.root


def test_gate_request_from_dict_defaults_on_missing_keys():
    req = GateRequest.from_dict({"question": "Minimal?"})
    assert req.id == ""
    assert req.protocol_id is None
    assert req.step_id is None
    assert req.status == "pending"
    assert req.created_at == ""
    assert req.resolved_at is None
    assert req.decision is None
    assert req.root is None


# ── event constants are the string values expected by the spec ────────────────

def test_event_constants_have_expected_values():
    from research_os.daemon.events import GATE_PENDING, GATE_RESOLVED
    assert GATE_PENDING == "gate.pending"
    assert GATE_RESOLVED == "gate.resolved"
