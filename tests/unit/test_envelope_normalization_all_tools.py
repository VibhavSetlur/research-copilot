"""W01 / FIX-7 — dispatcher-level envelope normalizer regression tests.

Pack and adapter tools historically returned the legacy
`{"status": "success", "data": {...}}` shape, missing the v2.1.0 envelope
fields (`payload`, `audit_findings`, `next_recommended_call`,
`tier_transition`, `tokens_estimate`, `ro_version`). The dispatcher now
funnels every handler return through `_normalize_envelope`, so MCP
clients only ever see the full v2.1.0 envelope.

This module parametrizes over `TOOL_DEFINITIONS` (every in-tree, pack,
and adapter tool) and asserts conformance with `REQUIRED_ENVELOPE_KEYS`.
"""
from __future__ import annotations

import json

import pytest

import research_os.server as _srv  # noqa: F401 — triggers pack/adapter discovery


@pytest.fixture
def project_root(tmp_path):
    (tmp_path / ".os_state").mkdir()
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "logs").mkdir()
    return tmp_path


def _envelope(result):
    """Parse the TextContent[] -> JSON envelope dict, or pass dicts through."""
    if isinstance(result, list) and result:
        return json.loads(result[0].text)
    if isinstance(result, dict):
        return result
    raise AssertionError(f"unexpected handler return shape: {type(result)}")


# ---------------------------------------------------------------------------
# Unit tests for the normalizer helper itself
# ---------------------------------------------------------------------------


def test_legacy_success_envelope_is_upgraded():
    from research_os.server.envelopes import (
        REQUIRED_ENVELOPE_KEYS, _normalize_envelope, _text,
    )

    legacy = _text({"status": "success", "data": {"hello": "world"}})
    out = _normalize_envelope(legacy, "tool_fake_legacy_success")
    env = _envelope(out)
    assert REQUIRED_ENVELOPE_KEYS.issubset(env.keys())
    assert env["status"] == "success"
    assert env["payload"] == {"hello": "world"}
    assert env["data"] == env["payload"]  # one-cycle alias preserved
    assert env["audit_findings"] == []
    assert env["next_recommended_call"] is None
    assert env["tier_transition"] is None
    assert isinstance(env["tokens_estimate"], int)
    assert isinstance(env["ro_version"], str) and env["ro_version"]


def test_legacy_error_envelope_is_upgraded():
    from research_os.server.envelopes import (
        REQUIRED_ENVELOPE_KEYS, _normalize_envelope, _text,
    )

    legacy = _text({"status": "error", "error": "boom"})
    env = _envelope(_normalize_envelope(legacy, "tool_fake_legacy_error"))
    assert REQUIRED_ENVELOPE_KEYS.issubset(env.keys())
    assert env["status"] == "error"
    assert env["error"] == "boom"
    assert env["payload"] == env["data"]
    assert env["payload"]["what"] == "boom"


def test_v210_envelope_is_passthrough():
    from research_os.server.envelopes import (
        _normalize_envelope, _success, _text,
    )

    # Already a v2.1.0 envelope; normalizer must NOT touch it.
    original = _text(_success({"k": "v"}, next_recommended_call="tool_x()"))
    out = _normalize_envelope(original, "tool_fake_modern")
    assert out is original  # same TextContent list, no rewrap
    env = _envelope(out)
    assert env["payload"] == {"k": "v"}
    assert env["next_recommended_call"] == "tool_x()"


def test_non_envelope_passthrough():
    from research_os.server.envelopes import _normalize_envelope

    assert _normalize_envelope([], "x") == []
    assert _normalize_envelope("plain string", "x") == "plain string"
    assert _normalize_envelope(None, "x") is None


# ---------------------------------------------------------------------------
# End-to-end: every registered tool dispatches into a v2.1.0 envelope
# ---------------------------------------------------------------------------

# Tools that need very specific args or external state to even produce a
# response — skip the contract check for these, they are exercised elsewhere.
_NEEDS_NETWORK_OR_HEAVY_STATE = frozenset({
    # nothing today — every tool below either succeeds or returns a normalized
    # error envelope, which still conforms to REQUIRED_ENVELOPE_KEYS.
})

# Minimal stub args per tool. The goal is reachability — we don't care
# whether the call succeeds, only that the returned envelope conforms to
# v2.1.0. A pack/adapter tool that errors on missing args returns an
# error envelope (which the normalizer also upgrades).
_STUB_ARGS: dict[str, dict] = {
    # Pack tools
    "tool_humanities_archive_lookup":      {"query": "Beowulf"},
    "tool_humanities_transcribe":          {"image_path": "workspace/img.png"},
    # Stub args use the REAL schema keys so each handler reaches its main
    # branch (or its proper not-found/graceful path) — not the generic
    # missing-arg error branch. The point is to exercise envelope shape.
    "tool_humanities_citation_chain":      {"quotation": "Smith 2020"},
    "tool_qualitative_codebook_diff":      {"codebook_v1": "a.yaml", "codebook_v2": "b.yaml"},
    "tool_qualitative_quote_provenance":   {"quote": "x", "participant_id": "P1"},
    "tool_qualitative_select_standard":    {"standard": "coreq"},
    "tool_theory_math_lean_check":         {"file_path": "x.lean"},
    "tool_theory_math_coq_check":          {"file_path": "x.v"},
    "tool_theory_math_dep_graph":          {"source_dir": "src"},
    "tool_wet_lab_plate_map_render":       {"spec_path": "plate.yaml"},
    "tool_wet_lab_reagent_query":          {"supplier": "neb", "catalog_number": "M0491"},
    "tool_wet_lab_sample_lineage_export":  {"lineage_spec_path": "lineage.yaml"},
    "tool_wet_lab_run_log_init":           {"instrument_family": "qpcr"},
    "tool_wet_lab_checksum_raw":           {"file_path": "raw.fcs"},
    "tool_engineering_fmea_render":        {"spec_path": "fmea.yaml"},
    "tool_engineering_fault_tree_render":  {"spec_path": "fta.yaml"},
    "tool_engineering_requirements_matrix": {"spec_path": "req.yaml"},
    # Adapter tools
    "tool_slurm_job_status":          {"job_id": "12345"},
    "tool_slurm_estimate_cost":       {"step_id": "01", "cost_per_node_hour": 0.1},
    "tool_snakemake_dryrun":          {"snakefile": "Snakefile"},
    "tool_snakemake_dag_render":      {"snakefile": "Snakefile"},
    "tool_nextflow_validate":         {"pipeline_path": "main.nf"},
    "tool_cytoscape_export_static":   {"cys_file": "demo.cys"},
    "tool_redcap_schema_describe":    {"step_id": "01"},
    "tool_synapse_entity_info":       {"entity_id": "syn123456"},
}


def _all_pack_and_adapter_tools() -> list[str]:
    # Packs/adapters were archived; kept as a stable (empty) hook.
    return []


@pytest.mark.parametrize("tool_name", _all_pack_and_adapter_tools())
def test_every_pack_and_adapter_tool_emits_v210_envelope(tool_name, project_root):
    """Dispatcher must upgrade every pack/adapter response to v2.1.0."""
    from research_os.server.envelopes import REQUIRED_ENVELOPE_KEYS

    if tool_name in _NEEDS_NETWORK_OR_HEAVY_STATE:
        pytest.skip(f"{tool_name} needs heavy state / network")

    args = _STUB_ARGS.get(tool_name, {})
    result = _srv._handle_tool_call(tool_name, args, project_root)
    env = _envelope(result)
    missing = REQUIRED_ENVELOPE_KEYS - set(env.keys())
    assert not missing, (
        f"{tool_name} envelope missing v2.1.0 fields: {missing} (got keys={sorted(env.keys())})"
    )
    # data alias must mirror payload (back-compat for one minor cycle).
    assert env["data"] == env["payload"], f"{tool_name}: data should alias payload"
    assert env["status"] in {"success", "warning", "error"}, (
        f"{tool_name} returned non-standard status {env.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# env-08 — CORE-handler envelope conformance.
# The conformance test above only covered pack/adapter tools, so an entire
# class of core handlers leaked non-v2.1.0 envelopes (bare {status,...} /
# {status,message} / raw markdown / dict-as-error). This curated set is the
# core handlers the 3.2.6 audit flagged; dispatching each must yield a
# conformant envelope (success OR a clean error), never a raw dict/string.
# ---------------------------------------------------------------------------

_CORE_TOOL_STUBS = {
    "tool_state_freshness_check": {},
    "tool_rigor_signals_scan": {},
    "tool_resolve_gate_strictness": {},
    "tool_project_tier_strictness": {},
    "tool_list_certifications": {},
    "tool_intake_freshness": {},
    "tool_reliability": {"operation": "report"},
    "tool_writing_discussion_from_verdicts": {},
    "tool_discussion_coverage_audit": {},
    "tool_step_complete": {"step_id": "01_x"},
    "sys_session_handoff": {},
    "tool_latex_compile": {},
    "tool_dry_run": {"protocol_name": "guidance/analysis_plan"},
    "tool_audit": {"scope": "project", "dimension": "coherence"},
    "tool_path_finalize": {},
    # Broader sweep of simple state/meta core handlers to flush out any other
    # status-less raw-dict returns the normalizer can't classify.
    "tool_self_certify": {"domain": "stats", "scope": "this project's models",
                          "rationale": "I hold a doctorate in statistics."},
    "tool_quick_route": {"prompt": "quick eda"},
    "tool_promote_to_step": {"scratch_path": "workspace/scratch/x.py", "step_slug": "probe"},
    "mem_citations_generate": {},
    "mem_intake_regenerate": {},
    "sys_dep_inventory": {},
    "tool_progress_digest": {},
    "tool_deprecations_summary": {},
}


@pytest.mark.parametrize("tool_name", sorted(_CORE_TOOL_STUBS))
def test_core_handler_emits_v210_envelope(tool_name, project_root):
    """Every flagged core handler must emit a conformant v2.1.0 envelope."""
    from research_os.server.envelopes import REQUIRED_ENVELOPE_KEYS

    if tool_name not in _srv.TOOL_DEFINITIONS:
        pytest.skip(f"{tool_name} not registered")
    result = _srv._handle_tool_call(tool_name, _CORE_TOOL_STUBS[tool_name], project_root)
    env = _envelope(result)
    missing = REQUIRED_ENVELOPE_KEYS - set(env.keys())
    assert not missing, (
        f"{tool_name} envelope missing v2.1.0 fields: {missing} (keys={sorted(env.keys())})"
    )
    assert env["status"] in {"success", "warning", "error"}, (
        f"{tool_name} returned non-standard status {env.get('status')!r}"
    )
    if env["status"] == "error":
        assert isinstance(env.get("error"), str) and env["error"], (
            f"{tool_name} error envelope must carry a string 'error'"
        )
