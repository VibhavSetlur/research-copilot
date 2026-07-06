"""sys_consent — the in-band consent loop (the consent_required path).

docs/UNSKIPPABLE_GATES.md + DAEMON_BRIDGE.md. When a floor gate under a
daemon returns consent_required, the agent uses sys_consent to request +
check + fetch a daemon-minted token WITHOUT importing the daemon. These
tests drive the handler against a mocked bridge (the bridge itself is
tested in test_daemon_bridge.py).
"""
from __future__ import annotations

import importlib
import json
import os

from research_os.server.handlers import meta_workspace as mw


def _bridge_mod():
    """The daemon_bridge module the handler will actually resolve.

    test_router_no_deg_false_positive.py reloads research_os.* mid-suite, so
    a module imported at test-collection time can become stale. Resolve it
    fresh (importlib) so monkeypatching hits the object the handler sees.
    """
    return importlib.import_module("research_os.server.daemon_bridge")


def _payload(resp):
    return json.loads(resp[0].text)


def _live_descriptor(root):
    p = root / ".os_state" / "daemon.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"pid": os.getpid(), "host": "127.0.0.1", "port": 8787}),
        encoding="utf-8",
    )


def test_no_daemon_reports_unavailable(tmp_path):
    r = _payload(mw._handle_sys_consent("sys_consent", {"action": "status"}, tmp_path))
    assert r["payload"]["available"] is False
    assert "degrades" in r["payload"]["hint"]


def test_request_queues_and_returns_id(tmp_path, monkeypatch):
    _live_descriptor(tmp_path)
    captured = {}

    def fake_post(base_url, path, payload, timeout=2.0):
        captured["path"] = path
        captured["payload"] = payload
        return 201, {"request": {"id": "req-123"}}

    monkeypatch.setattr(_bridge_mod(), "http_post", fake_post)
    r = _payload(mw._handle_sys_consent("sys_consent", {
        "action": "request", "gate_key": "tool_typst_compile",
        "arg_fingerprint": "abc", "tool": "tool_typst_compile",
        "reason": "compile paper",
    }, tmp_path))
    assert r["payload"]["requested"] is True
    assert r["payload"]["request_id"] == "req-123"
    assert captured["path"] == "/v1/consent/request"
    assert captured["payload"]["gate_key"] == "tool_typst_compile"


def test_request_requires_gate_key_and_fingerprint(tmp_path):
    _live_descriptor(tmp_path)
    r = _payload(mw._handle_sys_consent(
        "sys_consent", {"action": "request", "gate_key": "x"}, tmp_path
    ))
    assert r["status"] == "error"


def test_request_surfaces_server_error(tmp_path, monkeypatch):
    _live_descriptor(tmp_path)
    monkeypatch.setattr(_bridge_mod(), "http_post",
                        lambda *a, **k: (400, {"error": "bad_request"}))
    r = _payload(mw._handle_sys_consent("sys_consent", {
        "action": "request", "gate_key": "g", "arg_fingerprint": "f",
    }, tmp_path))
    assert r["status"] == "error"
    assert "bad_request" in str(r)


def test_status_lists_pending_and_grants(tmp_path, monkeypatch):
    _live_descriptor(tmp_path)

    def fake_get(base_url, path, timeout=2.0, headers=None):
        if path == "/v1/consent/pending":
            return 200, {"requests": [{"id": "r1"}]}
        if path == "/v1/consent/grants":
            return 200, {"grants": [{"token": "t", "gate_key": "g"}]}
        return None, None

    monkeypatch.setattr(_bridge_mod(), "http_get", fake_get)
    r = _payload(mw._handle_sys_consent("sys_consent", {"action": "status"}, tmp_path))
    assert r["payload"]["pending"] == [{"id": "r1"}]
    assert r["payload"]["grants"][0]["token"] == "t"


def test_token_returns_matching_unconsumed_grant(tmp_path, monkeypatch):
    _live_descriptor(tmp_path)
    monkeypatch.setattr(_bridge_mod(), "http_get", lambda b, p, t=2.0, headers=None: (
        200, {"grants": [{"token": "TOK", "gate_key": "g", "arg_fingerprint": "f", "consumed": False}]}
    ) if p == "/v1/consent/grants" else (None, None))
    r = _payload(mw._handle_sys_consent("sys_consent", {
        "action": "token", "gate_key": "g", "arg_fingerprint": "f",
    }, tmp_path))
    assert r["payload"]["consent_token"] == "TOK"


def test_token_skips_consumed_and_mismatched(tmp_path, monkeypatch):
    _live_descriptor(tmp_path)
    monkeypatch.setattr(_bridge_mod(), "http_get", lambda b, p, t=2.0, headers=None: (
        200, {"grants": [
            {"token": "OLD", "gate_key": "g", "arg_fingerprint": "f", "consumed": True},
            {"token": "OTHER", "gate_key": "g", "arg_fingerprint": "zzz", "consumed": False},
        ]}
    ) if p == "/v1/consent/grants" else (None, None))
    r = _payload(mw._handle_sys_consent("sys_consent", {
        "action": "token", "gate_key": "g", "arg_fingerprint": "f",
    }, tmp_path))
    assert r["payload"]["consent_token"] is None


def test_unknown_action_errors(tmp_path):
    _live_descriptor(tmp_path)
    r = _payload(mw._handle_sys_consent("sys_consent", {"action": "nope"}, tmp_path))
    assert r["status"] == "error"
