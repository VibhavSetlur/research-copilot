"""Precondition gate — protocols declare what must be true, verifier checks it.

docs/PRECONDITION_GATE.md. server/preconditions.py evaluates a protocol's
compiled requires.checks against a workspace; sys_protocol_get surfaces the
unmet ones so the AI does the missing step instead of proceeding on a
missing foundation.
"""
from __future__ import annotations

import json

import pytest

from research_os.server import preconditions as pc


def _meta(checks):
    return {"p/test": checks}


# --- file_exists -----------------------------------------------------------

def test_file_exists_unmet_when_absent(tmp_path):
    m = _meta([{"kind": "file_exists", "path": "workspace/methods.md",
               "because": "needed"}])
    unmet = pc.unmet_preconditions("p/test", tmp_path, meta=m)
    assert len(unmet) == 1
    assert unmet[0]["because"] == "needed"


def test_file_exists_met_when_present(tmp_path):
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "methods.md").write_text("content")
    m = _meta([{"kind": "file_exists", "path": "workspace/methods.md"}])
    assert pc.unmet_preconditions("p/test", tmp_path, meta=m) == []


def test_file_exists_non_empty_unmet_when_empty(tmp_path):
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "methods.md").write_text("")
    m = _meta([{"kind": "file_exists", "path": "workspace/methods.md",
               "non_empty": True}])
    assert len(pc.unmet_preconditions("p/test", tmp_path, meta=m)) == 1


# --- glob_min --------------------------------------------------------------

def test_glob_min_unmet_when_too_few(tmp_path):
    (tmp_path / "inputs").mkdir()
    m = _meta([{"kind": "glob_min", "pattern": "inputs/*", "min": 1}])
    assert len(pc.unmet_preconditions("p/test", tmp_path, meta=m)) == 1


def test_glob_min_met(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "a.csv").write_text("x")
    m = _meta([{"kind": "glob_min", "pattern": "inputs/*", "min": 1}])
    assert pc.unmet_preconditions("p/test", tmp_path, meta=m) == []


# --- protocol_completed ----------------------------------------------------

def test_protocol_completed_unmet_when_no_log(tmp_path):
    m = _meta([{"kind": "protocol_completed", "protocol": "literature/x"}])
    assert len(pc.unmet_preconditions("p/test", tmp_path, meta=m)) == 1


def test_protocol_completed_met(tmp_path):
    log = tmp_path / ".os_state" / "protocol_execution_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"protocol": "literature/x", "status": "completed"}) + "\n")
    m = _meta([{"kind": "protocol_completed", "protocol": "literature/x"}])
    assert pc.unmet_preconditions("p/test", tmp_path, meta=m) == []


def test_protocol_completed_unmet_when_only_started(tmp_path):
    log = tmp_path / ".os_state" / "protocol_execution_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"protocol": "literature/x", "status": "started"}) + "\n")
    m = _meta([{"kind": "protocol_completed", "protocol": "literature/x"}])
    assert len(pc.unmet_preconditions("p/test", tmp_path, meta=m)) == 1


# --- state_field -----------------------------------------------------------

def test_state_field_unmet_when_missing(tmp_path):
    m = _meta([{"kind": "state_field", "field": "research_question"}])
    assert len(pc.unmet_preconditions("p/test", tmp_path, meta=m)) == 1


def test_state_field_met_when_set(tmp_path):
    led = tmp_path / ".os_state" / "state_ledger.json"
    led.parent.mkdir(parents=True)
    led.write_text(json.dumps({"research_question": "does X cause Y?"}))
    m = _meta([{"kind": "state_field", "field": "research_question"}])
    assert pc.unmet_preconditions("p/test", tmp_path, meta=m) == []


def test_state_field_unmet_when_blank(tmp_path):
    led = tmp_path / ".os_state" / "state_ledger.json"
    led.parent.mkdir(parents=True)
    led.write_text(json.dumps({"research_question": "   "}))
    m = _meta([{"kind": "state_field", "field": "research_question"}])
    assert len(pc.unmet_preconditions("p/test", tmp_path, meta=m)) == 1


# --- fail-safe -------------------------------------------------------------

def test_unknown_kind_does_not_block(tmp_path):
    m = _meta([{"kind": "phase_of_moon", "value": "full"}])
    assert pc.unmet_preconditions("p/test", tmp_path, meta=m) == []


def test_no_checks_for_protocol_is_empty(tmp_path):
    assert pc.unmet_preconditions("p/unknown", tmp_path, meta={}) == []


def test_preconditions_met_helper(tmp_path):
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "m.md").write_text("x")
    m = _meta([{"kind": "file_exists", "path": "workspace/m.md"}])
    # All checks satisfied → met path returns empty unmet list.
    assert pc.unmet_preconditions("p/test", tmp_path, meta=m) == []


# --- shipped sidecar + handler integration --------------------------------

def test_shipped_analysis_plan_has_compiled_checks():
    """The committed sidecar carries analysis_plan's declared checks."""
    meta = pc._load_meta()
    assert "guidance/analysis_plan" in meta
    paths = {c.get("path") for c in meta["guidance/analysis_plan"]}
    assert "workspace/methods.md" in paths


def test_sys_protocol_get_surfaces_unmet(tmp_path):
    """sys_protocol_get on analysis_plan in an empty project flags the unmet
    file preconditions (tier-1 surfacing, no daemon)."""
    from research_os.server.handlers.meta_routing import _handle_sys_protocol_get

    resp = _handle_sys_protocol_get(
        "sys_protocol_get",
        {"protocol_name": "guidance/analysis_plan", "format": "summary"},
        tmp_path,
    )
    payload = json.loads(resp[0].text)["payload"]
    unmet = payload.get("unmet_preconditions") or []
    # Empty workspace → both methods.md + citations.md missing.
    kinds = {u["kind"] for u in unmet}
    assert "file_exists" in kinds
    assert len(unmet) >= 1


def test_sys_protocol_get_no_unmet_when_satisfied(tmp_path):
    from research_os.server.handlers.meta_routing import _handle_sys_protocol_get

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "methods.md").write_text("real methods")
    (ws / "citations.md").write_text("refs")
    resp = _handle_sys_protocol_get(
        "sys_protocol_get",
        {"protocol_name": "guidance/analysis_plan", "format": "summary"},
        tmp_path,
    )
    payload = json.loads(resp[0].text)["payload"]
    assert "unmet_preconditions" not in payload


# --- tier 2: world_state: preconditions_met gate predicate ----------------

def test_world_state_preconditions_met_fires_when_unmet(tmp_path):
    """The gate predicate FIRES (blocks) when a protocol's preconditions
    are not satisfied — empty project, analysis_plan needs methods.md."""
    from research_os.server import gate_spec as gs

    when = {"world_state": {"kind": "preconditions_met",
                            "protocol": "guidance/analysis_plan"}}
    assert gs._match_predicate(when, {}, tmp_path) is True


def test_world_state_preconditions_met_silent_when_satisfied(tmp_path):
    from research_os.server import gate_spec as gs

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "methods.md").write_text("methods")
    (ws / "citations.md").write_text("refs")
    when = {"world_state": {"kind": "preconditions_met",
                            "protocol": "guidance/analysis_plan"}}
    assert gs._match_predicate(when, {}, tmp_path) is False


def test_world_state_preconditions_no_protocol_does_not_fire(tmp_path):
    from research_os.server import gate_spec as gs

    when = {"world_state": {"kind": "preconditions_met"}}  # no protocol
    assert gs._match_predicate(when, {}, tmp_path) is False


def test_world_state_scalar_form_still_works(tmp_path):
    """The original scalar world_state form (staleness) is unaffected."""
    from research_os.server import gate_spec as gs

    # no stale verdict on disk → does not fire
    assert gs._match_predicate({"world_state": "no_stale_inputs"}, {}, tmp_path) is False


def test_synthesis_scaffold_blocked_under_daemon_when_preconditions_unmet(tmp_path):
    """Live tier-2: under a daemon, scaffolding a paper is blocked until
    synthesis_paper's foundations exist; confirmed=true does not bypass."""
    import os

    import yaml

    from research_os.server.autopilot_gate import enforce_autopilot_gate
    from research_os.server.errors import RoError

    (tmp_path / "inputs").mkdir(parents=True)
    (tmp_path / "inputs" / "researcher_config.yaml").write_text(
        yaml.safe_dump({"interaction": {"autonomy_level": "autopilot"}})
    )
    st = tmp_path / ".os_state"
    st.mkdir(exist_ok=True)
    (st / "daemon.json").write_text(json.dumps({"pid": os.getpid(), "port": 8787}))

    # Foundations missing → blocked, even with confirmed=true.
    with pytest.raises(RoError) as exc:
        enforce_autopilot_gate(
            "tool_synthesis_scaffold", {"kind": "paper", "confirmed": True}, tmp_path
        )
    assert exc.value.what == "consent_required"

    # Provide the foundations → gate stops firing.
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "methods.md").write_text("methods")
    (ws / "citations.md").write_text("[1]")
    (ws / "01").mkdir()
    (ws / "01" / "conclusions.md").write_text("## Findings\nx")
    enforce_autopilot_gate("tool_synthesis_scaffold", {"kind": "paper"}, tmp_path)
