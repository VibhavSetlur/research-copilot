"""Handler tests for sys_daemon — the MCP<->daemon bridge (Phase 3).

Verifies the reasoning-layer tool discovers a running daemon via its
on-disk descriptor and degrades cleanly in every failure mode, WITHOUT
importing the daemon package (the descriptor read + HTTP probe are pure
stdlib).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from research_os.server.handlers import meta_workspace as mw


def _payload(resp):
    return json.loads(resp[0].text)


def _write_descriptor(root: Path, *, pid: int, port: int = 8787) -> None:
    p = root / ".os_state" / "daemon.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({
            "schema": 1,
            "host": "127.0.0.1",
            "port": port,
            "pid": pid,
            "version": "9.9.9",
            "started_at": "2026-06-23T00:00:00+00:00",
            "base_url": f"http://127.0.0.1:{port}",
        }),
        encoding="utf-8",
    )


def test_no_descriptor_reports_not_running(tmp_path):
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    assert r["status"] == "success"
    assert r["payload"]["running"] is False
    assert "daemon start" in r["payload"]["hint"]


def test_corrupt_descriptor_reports_not_running(tmp_path):
    p = tmp_path / ".os_state" / "daemon.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ broken", encoding="utf-8")
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    assert r["payload"]["running"] is False


def test_stale_pid_reports_not_running_with_stale_hint(tmp_path):
    # A descriptor whose PID is not alive = crashed daemon, stale file.
    _write_descriptor(tmp_path, pid=2**31 - 1)
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    assert r["payload"]["running"] is False
    assert "stale" in r["payload"]["hint"].lower()


def test_alive_pid_unreachable_http_reports_reachable_false(tmp_path, monkeypatch):
    _write_descriptor(tmp_path, pid=os.getpid())
    monkeypatch.setattr(mw, "_daemon_http_get", lambda *a, **k: None)
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    assert r["payload"]["running"] is True
    assert r["payload"]["reachable"] is False
    assert r["payload"]["pid"] == os.getpid()


def test_alive_pid_reachable_returns_telemetry(tmp_path, monkeypatch):
    _write_descriptor(tmp_path, pid=os.getpid())

    def fake_get(base_url, path, timeout):
        if path == "/v1/orient":
            return {
                "narrative": "Two runs recorded; all fresh.",
                "recommended_next_action": "proceed",
                "field": {"label": "Machine Learning"},
            }
        if path == "/v1/jobs":
            return {
                "jobs": [{"status": "running"}, {"status": "done"}],
                "counts": {"running": 1, "done": 1},
                "total": 2,
            }
        return None

    monkeypatch.setattr(mw, "_daemon_http_get", fake_get)
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    p = r["payload"]
    assert p["running"] is True and p["reachable"] is True
    assert p["recommended_next_action"] == "proceed"
    assert p["narrative"].startswith("Two runs")
    assert p["jobs"]["total"] == 2
    assert p["jobs"]["by_status"] == {"running": 1, "done": 1}
    assert p["version"] == "9.9.9"


def test_jobs_counts_fallback_when_no_counts_key(tmp_path, monkeypatch):
    _write_descriptor(tmp_path, pid=os.getpid())

    def fake_get(base_url, path, timeout):
        if path == "/v1/jobs":
            # No 'counts' key — handler must recompute from items.
            return {"jobs": [{"status": "QUEUED"}, {"status": "queued"}]}
        return None  # orient unreachable

    monkeypatch.setattr(mw, "_daemon_http_get", fake_get)
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    assert r["payload"]["jobs"]["by_status"] == {"queued": 2}


def test_surfaces_budget_and_undelivered_notifications(tmp_path, monkeypatch):
    """sys_daemon surfaces the resource budget + undelivered pages in one call.

    Closes the MCP<->daemon connection gap: the AI sees the budget it must
    cite and what the researcher was paged about without extra calls.
    """
    _write_descriptor(tmp_path, pid=os.getpid())

    def fake_get(base_url, path, timeout):
        if path == "/v1/sandbox":
            return {
                "best_tier": "resource",
                "resource_budget": {"configured": True,
                                    "limits": {"address_space_mb": 16384}},
                "effective_limits": {"address_space_mb": 16384,
                                     "cpu_seconds": 7200},
            }
        if path.startswith("/v1/notifications"):
            return {"notifications": [
                {"level": "action_required", "title": "Job 'fit' FAILED",
                 "ts": "2026-06-24T00:00:00Z"},
            ]}
        if path == "/v1/jobs":
            return {"jobs": [], "total": 0}
        return None  # orient unreachable

    monkeypatch.setattr(mw, "_daemon_http_get", fake_get)
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    p = r["payload"]
    assert p["sandbox"]["best_tier"] == "resource"
    assert p["sandbox"]["resource_budget"]["limits"]["address_space_mb"] == 16384
    assert p["sandbox"]["effective_limits"]["cpu_seconds"] == 7200
    assert len(p["undelivered_notifications"]) == 1
    assert p["undelivered_notifications"][0]["level"] == "action_required"


def test_no_undelivered_notifications_omits_field(tmp_path, monkeypatch):
    _write_descriptor(tmp_path, pid=os.getpid())

    def fake_get(base_url, path, timeout):
        if path.startswith("/v1/notifications"):
            return {"notifications": []}
        if path == "/v1/jobs":
            return {"jobs": [], "total": 0}
        return None

    monkeypatch.setattr(mw, "_daemon_http_get", fake_get)
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    assert "undelivered_notifications" not in r["payload"]


def test_descriptor_without_address_does_not_probe_none_url(tmp_path, monkeypatch):
    p = tmp_path / ".os_state" / "daemon.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"pid": os.getpid(), "version": "9.9.9"}),
        encoding="utf-8",
    )

    def fail_get(*args, **kwargs):
        raise AssertionError("HTTP probe should not run without a bridge base URL")

    monkeypatch.setattr(mw, "_daemon_http_get", fail_get)
    r = _payload(mw._handle_sys_daemon("sys_daemon", {}, tmp_path))
    assert r["payload"]["running"] is True
    assert r["payload"]["reachable"] is False
    assert "base_url" not in r["payload"]



def test_timeout_arg_is_clamped(tmp_path, monkeypatch):
    _write_descriptor(tmp_path, pid=os.getpid())
    seen = {}

    def fake_get(base_url, path, timeout):
        seen["timeout"] = timeout
        return None

    monkeypatch.setattr(mw, "_daemon_http_get", fake_get)
    # Absurd timeout clamps to 30.0 ceiling.
    mw._handle_sys_daemon("sys_daemon", {"timeout": 9999}, tmp_path)
    assert seen["timeout"] == 30.0
    # Garbage timeout falls back to 2.0 default.
    mw._handle_sys_daemon("sys_daemon", {"timeout": "abc"}, tmp_path)
    assert seen["timeout"] == 2.0
