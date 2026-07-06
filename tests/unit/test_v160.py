"""Regression tests for v1.6.0 — lean variants, coaching, dry-run, bundling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.tools.actions.protocol import load_protocol
from research_os.tools.actions.state.mistake_replay import mistake_replay


# -- Theme 2: lean variants --------------------------------------------------


def test_lean_format_returns_shorter_than_full():
    full = load_protocol("guidance/analysis_plan", format="full")
    lean = load_protocol("guidance/analysis_plan", format="lean")
    full_bytes = len(json.dumps(full))
    lean_bytes = len(json.dumps(lean))
    assert lean_bytes < full_bytes, (
        f"lean ({lean_bytes}b) should be smaller than full ({full_bytes}b)"
    )
    # Step cap honoured.
    assert len(lean.get("steps") or []) <= 3
    # Distillation source marker present.
    assert lean.get("_lean_source") in {"auto-distilled", "explicit"}


def test_lean_format_trims_step_descriptions():
    lean = load_protocol("guidance/analysis_plan", format="lean")
    for step in lean.get("steps") or []:
        desc = step.get("description") or ""
        # 200 chars + ellipsis room — allow up to 220 with the trailing "…".
        assert len(desc) <= 220, f"step description not trimmed: {len(desc)}b"


def test_lean_format_uses_explicit_lean_variant_when_present(tmp_path, monkeypatch):
    # Import inside the test so `load_protocol` and `protocol_mod` come from
    # the same current `research_os.tools.actions.protocol` module — a prior
    # `_fresh_import()` in the suite (test_v170) can otherwise clear
    # sys.modules and rebind the top-level import to a different module than
    # `protocol_mod`, leaving the monkeypatch on the wrong module.
    from research_os.tools.actions import protocol as protocol_mod
    from research_os.tools.actions.protocol import load_protocol as _load
    src = tmp_path / "tmp" / "lean_test.yaml"
    src.parent.mkdir(parents=True)
    src.write_text(
        "id: lean_test\nname: Lean test\ntrigger: testing\n"
        "steps:\n  - id: a\n    name: A\n    description: full step\n"
        "  - id: b\n    name: B\n    description: full step b\n"
        "lean_variant:\n  id: lean_test\n  name: Lean test\n  steps:\n"
        "    - id: only\n      name: Only step\n      description: short\n"
    )
    monkeypatch.setattr(protocol_mod, "PROTOCOLS_DIR", tmp_path)

    lean = _load("tmp/lean_test", format="lean")
    assert lean.get("_lean_source") == "explicit"
    steps = lean.get("steps") or []
    assert len(steps) == 1
    assert steps[0]["id"] == "only"


# -- Theme 13: dry-run mode --------------------------------------------------


def test_dryrun_format_returns_sequence_without_writes():
    out = load_protocol("guidance/analysis_plan", format="dryrun")
    assert out.get("format") == "dryrun"
    assert "sequence" in out
    seq = out["sequence"]
    assert isinstance(seq, list)
    assert out["total_steps"] == len(seq)
    for step in seq:
        assert "step_id" in step
        assert "predicted_tool_calls" in step
        assert isinstance(step["predicted_tool_calls"], list)


def test_dryrun_finds_tool_calls_in_descriptions():
    out = load_protocol("guidance/analysis_plan", format="dryrun")
    # The analysis_plan protocol references many tools in step bodies; the
    # dry-run should surface at least a handful.
    assert out["total_predicted_tool_calls"] >= 5


# -- Theme 7: coaching mode + tool_mistake_replay ----------------------------


def test_mistake_replay_empty_workspace_returns_no_patterns(tmp_path):
    out = mistake_replay(tmp_path)
    assert out["status"] == "success"
    assert out["patterns"] == []
    assert "nothing to coach" in out["message"]


def test_mistake_replay_aggregates_reliability_events(tmp_path):
    rel = tmp_path / "workspace" / ".os_state" / "reliability.jsonl"
    rel.parent.mkdir(parents=True)
    events = [
        {"event_type": "gate_fire", "protocol_name": "audit", "payload": {"gate": "stack_plan"}},
        {"event_type": "gate_fire", "protocol_name": "audit", "payload": {"gate": "stack_plan"}},
        {"event_type": "gate_fire", "protocol_name": "audit", "payload": {"gate": "literature_loop"}},
        {"event_type": "tool_error", "protocol_name": "literature_search", "payload": {"tool": "tool_literature_download"}},
        {"event_type": "protocol_complete", "protocol_name": "synthesis"},  # not a coaching event
    ]
    rel.write_text("\n".join(json.dumps(e) for e in events))
    out = mistake_replay(tmp_path)
    assert out["status"] == "success"
    assert out["total_events"] == 5
    # gate_fire on `audit` (3x) should rank first.
    top = out["patterns"][0]
    assert top["protocol"] == "audit"
    assert top["event_type"] == "gate_fire"
    assert top["count"] == 3


# -- Schema validation -------------------------------------------------------


def test_sys_protocol_get_schema_enumerates_formats():
    from research_os.server import TOOL_DEFINITIONS
    schema = TOOL_DEFINITIONS["sys_protocol_get"]["inputSchema"]
    fmt = schema["properties"]["format"]
    assert "enum" in fmt
    assert set(fmt["enum"]) == {"ref", "summary", "step", "full", "lean", "dryrun"}
    assert schema.get("additionalProperties") is False


def test_tool_dry_run_schema_rejects_extras():
    from research_os.server import TOOL_DEFINITIONS
    schema = TOOL_DEFINITIONS["tool_dry_run"]["inputSchema"]
    assert schema.get("additionalProperties") is False
    assert "protocol_name" in schema["required"]


# -- Wiring ------------------------------------------------------------------


def test_three_new_tools_wired():
    """tool_dry_run remains top-level surface; tool_lessons stays wired."""
    from research_os.server import _HANDLERS, TOOL_DEFINITIONS
    for name in ("tool_dry_run", "tool_lessons"):
        assert name in TOOL_DEFINITIONS, f"{name} not in TOOL_DEFINITIONS"
        assert name in _HANDLERS, f"{name} not in _HANDLERS"
        assert callable(_HANDLERS[name]), f"{name} handler not callable"


def test_template_researcher_config_documents_coaching():
    repo_root = Path(__file__).resolve().parents[2]
    tmpl = (repo_root / "templates" / "researcher_config.yaml").read_text()
    assert "coaching" in tmpl
    assert "manual | supervised | autopilot | coaching" in tmpl
