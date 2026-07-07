"""Daemon-side consent authority — store + HTTP endpoints.

Covers research_os.daemon.consent.ConsentStore (mint/approve/deny/consume,
TTL, one-shot, arg-binding) and the /v1/consent/* routes, including the
end-to-end contract with the reasoning-side reader:

    daemon mints a grant  →  server/consent.find_valid_grant accepts it
                          →  server/autopilot_gate clears the floor gate

That round-trip is the whole point: the agent cannot forge the token; only
the daemon mints it, and the gate only trusts the daemon's ledger.
"""
from __future__ import annotations

import pytest

from research_os.daemon.consent import ConsentStore
from research_os.server import consent as reader

starlette = pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from research_os.daemon import Daemon  # noqa: E402
from research_os.daemon.server import build_app  # noqa: E402

_TOOL = "tool_audit"
_ARGS = {"scope": "step", "dimension": "reproducibility"}
_GATE_KEY = "tool_audit:reproducibility"


def _fp():
    return reader.arg_fingerprint(_TOOL, _ARGS)


# ── store unit tests ───────────────────────────────────────────────────────

def test_request_queues_pending_without_granting(tmp_path):
    store = ConsentStore(tmp_path)
    req = store.request(gate_key=_GATE_KEY, tool=_TOOL, arg_fingerprint=_fp())
    assert req["status"] == "pending"
    assert store.list_pending()[0]["id"] == req["id"]
    assert store.list_grants() == []  # nothing minted yet


def test_approve_mints_bound_grant_and_clears_pending(tmp_path):
    store = ConsentStore(tmp_path)
    req = store.request(gate_key=_GATE_KEY, tool=_TOOL, arg_fingerprint=_fp())
    grant = store.approve(req["id"])
    assert grant is not None
    assert grant["gate_key"] == _GATE_KEY
    assert grant["arg_fingerprint"] == _fp()
    assert grant["consumed"] is False
    assert store.list_pending() == []  # moved out of pending


def test_minted_grant_is_accepted_by_reader(tmp_path):
    """The cross-process contract: daemon mint → reader validates."""
    store = ConsentStore(tmp_path)
    req = store.request(gate_key=_GATE_KEY, tool=_TOOL, arg_fingerprint=_fp())
    grant = store.approve(req["id"])
    found = reader.find_valid_grant(
        tmp_path, _GATE_KEY, _fp(), grant["token"]
    )
    assert found is not None
    assert found["token"] == grant["token"]


def test_approve_unknown_request_returns_none(tmp_path):
    store = ConsentStore(tmp_path)
    assert store.approve("nope") is None


def test_deny_removes_pending(tmp_path):
    store = ConsentStore(tmp_path)
    req = store.request(gate_key=_GATE_KEY, tool=_TOOL, arg_fingerprint=_fp())
    assert store.deny(req["id"]) is True
    assert store.list_pending() == []
    assert store.deny(req["id"]) is False  # already gone


def test_consume_marks_one_shot(tmp_path):
    store = ConsentStore(tmp_path)
    req = store.request(gate_key=_GATE_KEY, tool=_TOOL, arg_fingerprint=_fp())
    grant = store.approve(req["id"])
    assert store.consume(grant["token"]) is True
    # After consume, the reader must reject it (one-shot).
    assert reader.find_valid_grant(
        tmp_path, _GATE_KEY, _fp(), grant["token"]
    ) is None
    assert store.consume(grant["token"]) is False  # already spent


def test_short_ttl_grant_expires_for_reader(tmp_path):
    store = ConsentStore(tmp_path)
    req = store.request(gate_key=_GATE_KEY, tool=_TOOL, arg_fingerprint=_fp())
    grant = store.approve(req["id"], ttl_seconds=1)
    import time

    time.sleep(1.2)
    assert reader.find_valid_grant(
        tmp_path, _GATE_KEY, _fp(), grant["token"]
    ) is None


# ── HTTP endpoint tests ────────────────────────────────────────────────────

def _gw_daemon(tmp_path):
    (tmp_path / ".os_state").mkdir(exist_ok=True)
    return Daemon.for_root(tmp_path)


def test_request_endpoint_open_no_auth(tmp_path):
    c = TestClient(build_app(_gw_daemon(tmp_path)))
    r = c.post(
        "/v1/consent/request",
        json={"gate_key": _GATE_KEY, "tool": _TOOL, "arg_fingerprint": _fp()},
    )
    assert r.status_code == 201
    assert r.json()["request"]["gate_key"] == _GATE_KEY


def test_request_endpoint_requires_fields(tmp_path):
    c = TestClient(build_app(_gw_daemon(tmp_path)))
    r = c.post("/v1/consent/request", json={"gate_key": _GATE_KEY})
    assert r.status_code == 400


def test_approve_requires_auth_when_token_set_and_missing(tmp_path, monkeypatch):
    """Token configured but not presented → 401 (not 503)."""
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    c = TestClient(build_app(_gw_daemon(tmp_path)))
    r = c.post("/v1/consent/approve", json={"request_id": "x"})
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_approve_rejects_bad_token(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    c = TestClient(build_app(_gw_daemon(tmp_path)))
    r = c.post(
        "/v1/consent/approve",
        headers={"Authorization": "Bearer wrong"},
        json={"request_id": "x"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_full_http_round_trip(tmp_path, monkeypatch):
    """request (open) → approve (auth) → reader validates the minted token."""
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))

    # 1. agent requests (no auth)
    rq = c.post(
        "/v1/consent/request",
        json={"gate_key": _GATE_KEY, "tool": _TOOL, "arg_fingerprint": _fp()},
    )
    assert rq.status_code == 201
    request_id = rq.json()["request"]["id"]

    # 2. it shows up in pending (read surface, no auth)
    pend = c.get("/v1/consent/pending")
    assert pend.status_code == 200
    assert any(p["id"] == request_id for p in pend.json()["pending"])

    # 3. authority approves (auth required)
    ap = c.post(
        "/v1/consent/approve",
        headers={"Authorization": "Bearer secret-123"},
        json={"request_id": request_id},
    )
    assert ap.status_code == 201
    token = ap.json()["grant"]["token"]

    # 4. the reasoning-side reader accepts the minted token for this action
    assert reader.find_valid_grant(
        tmp_path, _GATE_KEY, _fp(), token
    ) is not None

    # 5. consume makes it one-shot
    cons = c.post(
        "/v1/consent/consume",
        headers={"Authorization": "Bearer secret-123"},
        json={"token": token},
    )
    assert cons.status_code == 200 and cons.json()["consumed"] is True
    assert reader.find_valid_grant(tmp_path, _GATE_KEY, _fp(), token) is None


def test_approve_unknown_request_404(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    c = TestClient(build_app(_gw_daemon(tmp_path)))
    r = c.post(
        "/v1/consent/approve",
        headers={"Authorization": "Bearer secret-123"},
        json={"request_id": "does-not-exist"},
    )
    assert r.status_code == 404
