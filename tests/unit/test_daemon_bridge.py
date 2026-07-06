"""Daemon bridge — the canonical MCP↔daemon contract (docs/DAEMON_BRIDGE.md).

One definition of the .os_state/ contract paths + daemon-presence check,
shared by every reasoning-side reader. These tests pin the primitives so a
future change to the contract is caught here.
"""
from __future__ import annotations

import json
import os

from research_os.server import daemon_bridge as db


def _write_descriptor(root, *, pid, base_url=None, host=None, port=None):
    p = root / ".os_state" / "daemon.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    desc = {"pid": pid}
    if base_url:
        desc["base_url"] = base_url
    if host:
        desc["host"] = host
    if port:
        desc["port"] = port
    p.write_text(json.dumps(desc), encoding="utf-8")


# --- contract paths --------------------------------------------------------

def test_state_path_joins_under_os_state(tmp_path):
    assert db.state_path(tmp_path, db.CONSENT_GRANTED) == (
        tmp_path / ".os_state" / "consent" / "granted.json"
    )


def test_descriptor_path(tmp_path):
    assert db.descriptor_path(tmp_path) == tmp_path / ".os_state" / "daemon.json"


def test_contract_constants_are_stable():
    # These strings ARE the cross-process contract; pin them.
    assert db.STATE_DIR == ".os_state"
    assert db.DAEMON_DESCRIPTOR == "daemon.json"
    assert db.CONSENT_GRANTED == "consent/granted.json"
    assert db.NOTIFICATIONS_OUTBOX == "notifications/outbox.jsonl"
    assert db.STALENESS_VERDICT == "staleness/verdict.json"
    assert db.RUNS_DIR == "runs"


# --- read_descriptor -------------------------------------------------------

def test_read_descriptor_absent(tmp_path):
    assert db.read_descriptor(tmp_path) is None


def test_read_descriptor_corrupt(tmp_path):
    p = tmp_path / ".os_state" / "daemon.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ broken", encoding="utf-8")
    assert db.read_descriptor(tmp_path) is None


def test_read_descriptor_returns_dict_even_if_pid_dead(tmp_path):
    _write_descriptor(tmp_path, pid=2**31 - 1)
    desc = db.read_descriptor(tmp_path)
    assert isinstance(desc, dict) and desc["pid"] == 2**31 - 1


# --- daemon_present --------------------------------------------------------

def test_daemon_present_false_when_absent(tmp_path):
    assert db.daemon_present(tmp_path) is False


def test_daemon_present_false_when_pid_dead(tmp_path):
    _write_descriptor(tmp_path, pid=2**31 - 1)
    assert db.daemon_present(tmp_path) is False


def test_daemon_present_true_when_pid_alive(tmp_path):
    _write_descriptor(tmp_path, pid=os.getpid())
    assert db.daemon_present(tmp_path) is True


def test_daemon_present_false_when_pid_not_int(tmp_path):
    _write_descriptor(tmp_path, pid="nope")
    assert db.daemon_present(tmp_path) is False


# --- daemon_base_url -------------------------------------------------------

def test_base_url_from_explicit_field(tmp_path):
    _write_descriptor(tmp_path, pid=os.getpid(), base_url="http://127.0.0.1:8787")
    assert db.daemon_base_url(tmp_path) == "http://127.0.0.1:8787"


def test_base_url_from_host_port(tmp_path):
    _write_descriptor(tmp_path, pid=os.getpid(), host="127.0.0.1", port=8800)
    assert db.daemon_base_url(tmp_path) == "http://127.0.0.1:8800"


def test_base_url_none_when_pid_dead(tmp_path):
    _write_descriptor(tmp_path, pid=2**31 - 1, base_url="http://127.0.0.1:8787")
    assert db.daemon_base_url(tmp_path) is None


# --- http_get fail-safe ----------------------------------------------------

def test_http_get_returns_none_on_unreachable():
    # Nothing listening on this port → (None, None), never raises.
    status, body = db.http_get("http://127.0.0.1:1", "/v1/orient", timeout=0.2)
    assert status is None
    assert body is None
