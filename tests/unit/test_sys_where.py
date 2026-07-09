"""Tests for sys_where + sys_boot(lean=true) — W08 orientation tools.

Verifies:
  * sys_where returns the 5-field shape (project_root, tier, active_plan,
    unresolved_blocks, last_protocol) in <100ms.
  * sys_where reads .os_state/current_tier.json + .os_state/active_plan.json
    + workspace/logs/.audit_findings.jsonl correctly.
  * sys_boot(lean=true) returns only the lean-mode keys (active_plan,
    pause_classification, current_tier, root, active_packs).
  * Both shapes include active_packs.
  * Token cost is small (<100 tokens for sys_where, <200 for lean boot).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from research_os.server.handlers.meta_workspace import _handle_sys_where
from research_os.tools.actions.router import sys_boot


def _payload(resp):
    text = resp[0].text if hasattr(resp[0], "text") else resp[0]["text"]
    obj = json.loads(text)
    # _success envelope wraps the payload; normalize.
    if "payload" in obj and isinstance(obj["payload"], dict):
        return obj["payload"]
    return obj


def _scaffold(tmp_path: Path) -> Path:
    (tmp_path / ".os_state").mkdir()
    (tmp_path / "workspace" / "logs").mkdir(parents=True)
    return tmp_path


# ── sys_where ────────────────────────────────────────────────────────


def test_sys_where_returns_5_field_shape(tmp_path):
    root = _scaffold(tmp_path)
    resp = _handle_sys_where("sys_where", {}, root)
    p = _payload(resp)
    for k in ("project_root", "tier", "active_plan", "unresolved_blocks",
              "last_protocol"):
        assert k in p, f"sys_where missing key {k}"
    # Empty project — defaults.
    assert p["project_root"] == root.name
    assert p["tier"] is None
    assert p["active_plan"] is None
    assert p["unresolved_blocks"] == 0
    assert p["last_protocol"] is None


def test_sys_where_reads_tier_state(tmp_path):
    root = _scaffold(tmp_path)
    (root / ".os_state" / "current_tier.json").write_text(
        json.dumps({"current_tier": "intake", "history": []})
    )
    resp = _handle_sys_where("sys_where", {}, root)
    p = _payload(resp)
    assert p["tier"] == "intake"


def test_sys_where_reads_active_plan_step_total(tmp_path):
    root = _scaffold(tmp_path)
    (root / ".os_state" / "active_plan.json").write_text(
        json.dumps({
            "decomposition": ["a", "b", "c", "d"],
            "current_step": 2,
            "status": "in_progress",
        })
    )
    resp = _handle_sys_where("sys_where", {}, root)
    p = _payload(resp)
    assert p["active_plan"] == {"step": 2, "total": 4}


def test_sys_where_counts_block_findings(tmp_path):
    root = _scaffold(tmp_path)
    ledger = root / "workspace" / "logs" / ".audit_findings.jsonl"
    ledger.write_text(
        json.dumps({"severity": "BLOCK", "code": "X1", "message": "m"}) + "\n"
        + json.dumps({"severity": "CAUTION", "code": "X2", "message": "m"}) + "\n"
        + json.dumps({"severity": "BLOCKER", "code": "X3", "message": "m"}) + "\n"
    )
    resp = _handle_sys_where("sys_where", {}, root)
    p = _payload(resp)
    assert p["unresolved_blocks"] == 2


def test_sys_where_completes_under_100ms(tmp_path):
    root = _scaffold(tmp_path)
    t0 = time.perf_counter()
    _handle_sys_where("sys_where", {}, root)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 100, f"sys_where took {elapsed_ms:.1f}ms"


def test_sys_where_token_cost_small(tmp_path):
    root = _scaffold(tmp_path)
    resp = _handle_sys_where("sys_where", {}, root)
    text = resp[0].text if hasattr(resp[0], "text") else resp[0]["text"]
    obj = json.loads(text)
    # The envelope ships an authoritative tokens_estimate for the payload.
    # Lightweight orientation tool should land under ~100 tokens even with
    # the §13.1 active_persona field (name + directive string).
    assert obj.get("tokens_estimate", 999) < 100, (
        f"sys_where payload too large: {obj.get('tokens_estimate')} tokens"
    )
    # Belt-and-braces: the payload object itself (sans envelope) should
    # serialize to <400 chars (allows for active_persona name + directive).
    payload_only = json.dumps(obj["payload"])
    assert len(payload_only) < 400, (
        f"sys_where payload serializes to {len(payload_only)} chars"
    )


def test_sys_where_survives_unscaffolded_root(tmp_path):
    # No .os_state — still returns the shape with defaults.
    resp = _handle_sys_where("sys_where", {}, tmp_path)
    p = _payload(resp)
    assert p["project_root"] == tmp_path.name
    assert p["tier"] is None
    assert p["active_plan"] is None


# ── sys_boot(lean=true) ──────────────────────────────────────────────


def test_sys_boot_lean_returns_minimal_shape(tmp_path):
    res = sys_boot(tmp_path, lean=True)
    assert res["status"] == "success"
    # Lean-mode keys.
    for k in ("active_plan", "pause_classification", "current_tier",
              "root", "active_packs"):
        assert k in res, f"sys_boot(lean=true) missing key {k}"
    # Skipped (full-mode-only) keys.
    for k in ("dep_inventory", "paths_summary", "history_tail",
              "next_protocol", "freshness", "advice"):
        assert k not in res, f"sys_boot(lean=true) leaked full-mode key {k}"


def test_sys_boot_lean_includes_active_packs(tmp_path):
    res = sys_boot(tmp_path, lean=True)
    assert "active_packs" in res
    assert isinstance(res["active_packs"], list)


def test_sys_boot_full_includes_active_packs(tmp_path):
    res = sys_boot(tmp_path)
    assert "active_packs" in res, "full sys_boot must include active_packs"
    assert isinstance(res["active_packs"], list)
    assert "current_tier" in res, "full sys_boot must include current_tier"


def test_sys_boot_lean_default_false(tmp_path):
    # Default sys_boot() (no lean arg) returns the full payload.
    res = sys_boot(tmp_path)
    assert "dep_inventory" in res
    assert "paths_summary" in res


def test_sys_boot_lean_default_kwarg_off(tmp_path):
    res = sys_boot(tmp_path, lean=False)
    assert "dep_inventory" in res
