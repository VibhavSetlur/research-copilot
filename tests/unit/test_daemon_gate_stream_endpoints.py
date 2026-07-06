"""Tests — FIX 5: POST /v1/gates/respond decision validation.

Verifies that the daemon's gate-respond endpoint enforces
``decision in {"approve", "reject"}`` and returns HTTP 400 for anything
else, rather than silently mapping typos to a rejected gate.
"""
from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeBus:
    def __init__(self):
        self.calls: list[dict] = []

    def publish(self, kind, data=None, root=None):
        self.calls.append({"kind": kind, "data": data or {}})


class _FakeConfig:
    host = "127.0.0.1"
    port = 9999
    base_url = "http://127.0.0.1:9999"
    enable_gateway = True
    gateway_token_env = "RESEARCH_OS_GATEWAY_TOKEN"
    enable_dashboard = False
    sandbox_mode = "auto"
    task_workers = 1
    state_cache_ttl = 30
    notify_command = ""


class _FakeDaemon:
    """Minimal stub of Daemon for server endpoint testing."""

    def __init__(self, tmp_path):
        from research_os.daemon.gates import GateQueue
        from research_os.daemon.events import EventBus

        self.root = tmp_path
        self.events = EventBus()
        self.gates = GateQueue(tmp_path, event_bus=self.events)
        self.config = _FakeConfig()
        self._serving = True

    @property
    def serving(self):
        return self._serving


def _make_app(daemon):
    """Build the server ASGI app against the fake daemon."""
    from research_os.daemon.server import build_app
    return build_app(daemon)


def _auth_headers(token="test-token"):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# FIX 5: decision validation
# ---------------------------------------------------------------------------

class TestGateRespondDecisionValidation:
    """POST /v1/gates/respond must accept only 'approve' or 'reject'.

    Any other value should return 400 {"error": ..., "code": "bad_request"}
    rather than silently mapping the typo to a rejected decision.
    """

    @pytest.fixture
    def app_and_daemon(self, tmp_path, monkeypatch):
        """Return (app, daemon) with gateway auth set up."""
        monkeypatch.setenv("RESEARCH_OS_GATEWAY_TOKEN", "test-token")
        daemon = _FakeDaemon(tmp_path)
        app = _make_app(daemon)
        return app, daemon

    @pytest.fixture
    def pending_gate_id(self, app_and_daemon):
        """Enqueue a gate and return its id."""
        from research_os.daemon.gates import GateRequest
        _, daemon = app_and_daemon
        req = GateRequest(
            id="",
            protocol_id="analysis/eval",
            step_id="s1",
            question="Proceed?",
            root=str(daemon.root),
        )
        daemon.gates.enqueue(req)
        return req.id

    def _post_respond(self, app, gate_id, decision, token="test-token"):
        """Send POST /v1/gates/respond via starlette TestClient."""
        from starlette.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        return client.post(
            "/v1/gates/respond",
            json={"gate_id": gate_id, "decision": decision},
            headers=_auth_headers(token),
        )

    def test_approve_succeeds(self, app_and_daemon, pending_gate_id):
        app, _ = app_and_daemon
        resp = self._post_respond(app, pending_gate_id, "approve")
        assert resp.status_code == 200
        body = resp.json()
        assert body["approved"] is True
        assert body["decision"] == "approve"

    def test_reject_succeeds(self, app_and_daemon, tmp_path, monkeypatch):
        from research_os.daemon.gates import GateRequest
        monkeypatch.setenv("RESEARCH_OS_GATEWAY_TOKEN", "test-token")
        daemon = _FakeDaemon(tmp_path)
        req = GateRequest(id="", protocol_id="analysis/eval", step_id="s1",
                          question="Proceed?", root=str(tmp_path))
        daemon.gates.enqueue(req)
        app = _make_app(daemon)
        resp = self._post_respond(app, req.id, "reject")
        assert resp.status_code == 200
        body = resp.json()
        assert body["approved"] is False
        assert body["decision"] == "reject"

    def test_case_insensitive_approve(self, app_and_daemon, pending_gate_id):
        """FIX 5: 'Approve' and 'APPROVE' are normalised and accepted."""
        app, _ = app_and_daemon
        resp = self._post_respond(app, pending_gate_id, "APPROVE")
        assert resp.status_code == 200
        assert resp.json()["approved"] is True

    def test_case_insensitive_reject(self, app_and_daemon, tmp_path, monkeypatch):
        from research_os.daemon.gates import GateRequest
        monkeypatch.setenv("RESEARCH_OS_GATEWAY_TOKEN", "test-token")
        daemon = _FakeDaemon(tmp_path)
        req = GateRequest(id="", protocol_id="p", step_id="s",
                          question="?", root=str(tmp_path))
        daemon.gates.enqueue(req)
        app = _make_app(daemon)
        resp = self._post_respond(app, req.id, "Reject")
        assert resp.status_code == 200
        assert resp.json()["approved"] is False

    def test_typo_returns_400(self, app_and_daemon, pending_gate_id):
        """FIX 5: a typo like 'approved' must return 400, not silently reject."""
        app, _ = app_and_daemon
        for bad in ("approved", "yes", "no", "ok", "denied", "1", ""):
            if not bad:
                # Empty string is caught by the earlier "not decision" check.
                continue
            resp = self._post_respond(app, pending_gate_id, bad)
            assert resp.status_code == 400, (
                f"Expected 400 for decision={bad!r}, got {resp.status_code}"
            )
            body = resp.json()
            assert body["code"] == "bad_request"
            assert "approve" in body["error"] and "reject" in body["error"], (
                f"Error message should mention valid values; got: {body['error']!r}"
            )

    def test_missing_decision_returns_400(self, app_and_daemon, pending_gate_id):
        """Missing 'decision' field → 400."""
        app, _ = app_and_daemon
        from starlette.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/v1/gates/respond",
            json={"gate_id": pending_gate_id},
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_missing_gate_id_returns_400(self, app_and_daemon):
        """Missing 'gate_id' field → 400."""
        app, _ = app_and_daemon
        from starlette.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/v1/gates/respond",
            json={"decision": "approve"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 400

    def test_unknown_gate_id_returns_404(self, app_and_daemon):
        """Unknown gate_id → 404."""
        app, _ = app_and_daemon
        resp = self._post_respond(app, "no-such-gate", "approve")
        assert resp.status_code == 404

    def test_no_auth_returns_503_or_401(self, app_and_daemon, pending_gate_id):
        """No bearer token → 503 (gateway not configured) or 401."""
        app, _ = app_and_daemon
        from starlette.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/v1/gates/respond",
            json={"gate_id": pending_gate_id, "decision": "approve"},
        )
        assert resp.status_code in (401, 503)
