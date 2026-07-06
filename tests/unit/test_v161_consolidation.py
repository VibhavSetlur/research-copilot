"""v1.6.1 Theme 6: surface consolidation tests.

Coverage:
  * Every deprecated alias resolves to a registered handler.
  * Param-injection map covers every deprecated alias.
  * Each old tool name still works end-to-end (back-compat).
  * New consolidated tools work with explicit operation/kind/source.
  * Old + new produce identical outputs for equivalent invocations.
  * Deprecation log entries are written for alias hits.
  * tool_deprecations_summary aggregates correctly.
  * Protocol loader honours redirect_to: + redirect_params.
  * Synthesis/printable redirect stubs load the consolidated body.
  * Preflight catches stub-with-steps + missing alias targets.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.server import (
    TOOL_DEFINITIONS,
    _ALIAS_PARAM_INJECTION,
    _DEPRECATED_ALIASES,
    _HANDLERS,
    _handle_tool_call,
    _resolve_tool_name,
)
from research_os.tools.actions import protocol as protocol_mod


# ── fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def project_root(tmp_path):
    (tmp_path / ".os_state").mkdir()
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "logs").mkdir()
    return tmp_path


def _result_text(result):
    return result[0].text


def _parse_envelope(result):
    return json.loads(_result_text(result))


# ── alias completeness ────────────────────────────────────────────


def test_every_deprecated_alias_resolves_to_a_handler():
    for old in _DEPRECATED_ALIASES:
        new = _resolve_tool_name(old)
        assert new in _HANDLERS, f"{old} → {new} (handler missing)"


def test_every_deprecated_alias_has_param_injection():
    missing = sorted(_DEPRECATED_ALIASES - set(_ALIAS_PARAM_INJECTION))
    assert not missing, f"missing injection for: {missing}"


def test_alias_param_injection_targets_are_valid_keys():
    # Sanity: every injected key must be one of the consolidation params
    # we expect (operation / kind / source / mode / scope / dimension).
    # Two value shapes are supported in _ALIAS_PARAM_INJECTION:
    #   * (key, value) — single-kwarg injection
    #   * tuple of (key, value) tuples — multi-kwarg injection
    # (the audit family injects both scope and dimension).
    valid_keys = {"operation", "kind", "source", "mode", "scope", "dimension"}
    for old, spec in _ALIAS_PARAM_INJECTION.items():
        # Multi-kwarg form: tuple of (key, value) pairs.
        if (
            isinstance(spec, tuple)
            and spec
            and all(isinstance(p, tuple) and len(p) == 2 for p in spec)
        ):
            pairs = spec
        else:
            pairs = (spec,)
        for key, _ in pairs:
            assert key in valid_keys, f"{old} injects unknown key '{key}'"


# ── new consolidated tools registered ─────────────────────────────


@pytest.mark.parametrize(
    "tool_name",
    [
        "tool_search",
        "tool_plan",
        "sys_state_get",
        "tool_ground",
        "tool_verify",
        "tool_lessons",
        "mem_log",
    ],
)
def test_new_consolidated_tools_registered(tool_name):
    assert tool_name in _HANDLERS, f"handler missing: {tool_name}"
    assert tool_name in TOOL_DEFINITIONS, f"TOOL_DEFINITIONS missing: {tool_name}"


# ── end-to-end: legacy aliases ────────────────────────────────────


# NOTE — Phase 14a (v2.0.0): the 21 v1.6.1-era aliases (mem_methods_append,
# mem_decision_log, mem_hypothesis_update, mem_analysis_log, sys_path_create/
# abandon/list, tool_plan_turn/advance/clear, tool_lessons_record/consult,
# tool_search_*, tool_grounding_register, tool_ground_from_context,
# tool_claim_verify, tool_grounding_verify) were hard-removed after their
# deprecation runway expired. The tests below confirm the consolidated tools
# work; the legacy-name back-compat tests were dropped — see
# test_v14a_removed_aliases for the negative coverage that confirms each
# removed name now returns a _REMOVED_TOOLS error pointing at the new path.


def test_new_mem_log_methods_writes_methods_md(project_root):
    r = _handle_tool_call(
        "mem_log", {"kind": "methods", "method": "GLM"}, project_root
    )
    env = _parse_envelope(r)
    assert env["status"] == "success"
    assert "GLM" in (project_root / "workspace" / "methods.md").read_text()


def test_new_sys_path_list_works(project_root):
    r = _handle_tool_call("sys_path", {"operation": "list"}, project_root)
    env = _parse_envelope(r)
    assert env["status"] == "success"
    assert "paths" in env["data"]


def test_new_tool_plan_clear_works(project_root):
    r = _handle_tool_call(
        "tool_plan", {"operation": "clear"}, project_root
    )
    env = _parse_envelope(r)
    assert env["status"] == "success"


def test_new_tool_lessons_unified(project_root):
    rec = _handle_tool_call(
        "tool_lessons",
        {"operation": "record", "outcome": "success", "reflection": "use Y"},
        project_root,
    )
    assert _parse_envelope(rec)["status"] == "success"
    con = _handle_tool_call(
        "tool_lessons",
        {"operation": "consult", "task": "plan a y"},
        project_root,
    )
    assert _parse_envelope(con)["status"] == "success"


def test_new_mem_log_hypothesis_routes(project_root):
    add = _handle_tool_call(
        "mem_hypothesis_add", {"statement": "X causes Y"}, project_root
    )
    assert _parse_envelope(add)["status"] == "success"
    upd = _handle_tool_call(
        "mem_log",
        {"kind": "hypothesis", "hypothesis_id": "H1", "status": "rejected"},
        project_root,
    )
    assert _parse_envelope(upd)["status"] == "success"


def test_new_mem_log_analysis_writes_entry(project_root):
    r = _handle_tool_call(
        "mem_log", {"kind": "analysis", "entry": "ran EDA pass"}, project_root
    )
    assert _parse_envelope(r)["status"] == "success"
    txt = (project_root / "workspace" / "analysis.md").read_text()
    assert "ran EDA pass" in txt


def test_new_mem_log_rejects_unknown_kind(project_root):
    r = _handle_tool_call(
        "mem_log", {"kind": "telepathy", "entry": "x"}, project_root
    )
    assert _parse_envelope(r)["status"] == "error"


def test_new_sys_path_rejects_unknown_operation(project_root):
    r = _handle_tool_call("sys_path", {"operation": "obliterate"}, project_root)
    assert _parse_envelope(r)["status"] == "error"


def test_new_tool_plan_rejects_unknown_operation(project_root):
    r = _handle_tool_call("tool_plan", {"operation": "wiggle"}, project_root)
    assert _parse_envelope(r)["status"] == "error"


# ── deprecation logging ───────────────────────────────────────────


def test_non_deprecated_alias_does_not_log(project_root):
    # `tool_audit_statistical_power` is a nickname, not a v1.6.1 consolidation.
    _handle_tool_call(
        "sys_state_summary", {}, project_root
    )  # resolves to sys_state_get
    log = project_root / ".os_state" / "deprecations.log"
    if log.exists():
        entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        assert all(e["source"] != "sys_state_summary" for e in entries)


def test_new_canonical_name_does_not_log(project_root):
    _handle_tool_call("mem_log", {"kind": "analysis", "entry": "x"}, project_root)
    log = project_root / ".os_state" / "deprecations.log"
    if log.exists():
        entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        assert all(e["source"] != "mem_log" for e in entries)


# ── tool_search consolidation ─────────────────────────────────────


def test_tool_search_unknown_source_returns_error(project_root):
    r = _handle_tool_call(
        "tool_search", {"query": "q", "source": "scihub"}, project_root
    )
    env = _parse_envelope(r)
    assert env["status"] == "error"


def test_tool_search_auto_picks_biomedical_providers_for_rna(
    project_root, monkeypatch
):
    """`source='auto'` with an RNA-flavoured query should call S2 + PubMed."""
    called = []

    def fake_s2(q, limit):
        called.append(("s2", q, limit))
        return [{"title": "rna paper", "_source": "semantic_scholar"}]

    def fake_pm(q, limit):
        called.append(("pm", q, limit))
        return [{"title": "rna paper pm", "_source": "pubmed"}]

    # Post-server-refactor: handler resolves provider via its module-level
    # binding pulled in by `from .._handlers_runtime import *`. Patch the
    # binding the handler actually reads (not just the public re-export).
    monkeypatch.setattr(
        "research_os.server.handlers.research_search.search_semantic_scholar",
        fake_s2,
    )
    monkeypatch.setattr(
        "research_os.server.handlers.research_search.search_pubmed", fake_pm
    )
    r = _handle_tool_call(
        "tool_search",
        {"query": "snRNA-seq dorsal raphe", "source": "auto", "limit": 4},
        project_root,
    )
    env = _parse_envelope(r)
    assert env["status"] == "success"
    assert env["data"]["mode"] == "auto"
    assert "semantic_scholar" in env["data"]["sources"]
    assert "pubmed" in env["data"]["sources"]
    called_providers = {c[0] for c in called}
    assert called_providers == {"s2", "pm"}


def test_new_tool_search_pubmed_routes_to_pubmed(project_root, monkeypatch):
    """tool_search(source='pubmed') is the v2 replacement for tool_search_pubmed."""
    called = []

    def fake_pm(q, limit):
        called.append((q, limit))
        return [{"title": "hit"}]

    monkeypatch.setattr(
        "research_os.server.handlers.research_search.search_pubmed", fake_pm
    )
    _handle_tool_call(
        "tool_search",
        {"query": "foo", "limit": 3, "source": "pubmed"},
        project_root,
    )
    assert called == [("foo", 3)]


# ── protocol redirect_to: ─────────────────────────────────────────


def test_protocol_loader_follows_redirect_to(monkeypatch, tmp_path):
    """Custom redirect stub points at a custom target; loader follows it."""
    import yaml

    dest = tmp_path / "cat"
    dest.mkdir()
    target = dest / "real.yaml"
    target.write_text(
        yaml.safe_dump(
            {
                "id": "real",
                "version": "1.6.1",
                "steps": [{"id": "s1", "name": "S1", "description": "do it"}],
            }
        )
    )
    stub = dest / "old.yaml"
    stub.write_text(
        yaml.safe_dump(
            {
                "id": "old",
                "redirect_to": "cat/real",
                "redirect_params": {"variant": "x"},
            }
        )
    )
    monkeypatch.setattr(protocol_mod, "PROTOCOLS_DIR", tmp_path)
    result = protocol_mod.load_protocol("cat/old")
    assert result.get("id") == "real"
    assert result.get("_redirected_from") == "cat/old"
    assert result.get("_redirect_params") == {"variant": "x"}


def test_redirect_cycle_raises(monkeypatch, tmp_path):
    import yaml

    dest = tmp_path / "cat"
    dest.mkdir()
    # a → a (self-cycle)
    (dest / "a.yaml").write_text(
        yaml.safe_dump({"id": "a", "redirect_to": "cat/a"})
    )
    monkeypatch.setattr(protocol_mod, "PROTOCOLS_DIR", tmp_path)
    with pytest.raises(ValueError, match="Redirect cycle"):
        protocol_mod.load_protocol("cat/a")


def test_synthesis_handout_redirect_resolves(monkeypatch, tmp_path):
    """The real synthesis_handout stub loads the consolidated printable body."""
    # Set a fake workspace so the redirect-log doesn't pollute the live project.
    (tmp_path / ".os_state").mkdir()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE", str(tmp_path))
    r = protocol_mod.load_protocol("synthesis/synthesis_handout")
    assert r.get("id") == "printable"
    assert r.get("_redirected_from") == "synthesis/synthesis_handout"
    assert r.get("_redirect_params") == {"format": "handout"}
    assert len(r.get("steps", [])) > 0


def test_synthesis_poster_redirect_resolves(monkeypatch, tmp_path):
    (tmp_path / ".os_state").mkdir()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE", str(tmp_path))
    r = protocol_mod.load_protocol("synthesis/synthesis_poster")
    assert r.get("id") == "printable"
    assert r.get("_redirect_params") == {"format": "poster"}


def test_redirect_log_written_to_deprecations_log(monkeypatch, tmp_path):
    (tmp_path / ".os_state").mkdir()
    monkeypatch.setenv("RESEARCH_OS_WORKSPACE", str(tmp_path))
    protocol_mod.load_protocol("synthesis/synthesis_handout")
    log = tmp_path / ".os_state" / "deprecations.log"
    assert log.exists()
    entries = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    redirect_entries = [e for e in entries if e["kind"] == "protocol_redirect"]
    assert any(
        e["source"] == "synthesis/synthesis_handout" for e in redirect_entries
    )


# ── preflight check coverage ──────────────────────────────────────


def test_preflight_alias_completeness_passes():
    """Live preflight check should report ok for the live alias table."""
    import importlib.util

    pf_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "preflight.py"
    )
    spec = importlib.util.spec_from_file_location("preflight", pf_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ok, msg = mod.check_alias_table_complete()
    assert ok, msg


def test_preflight_redirect_targets_passes():
    import importlib.util

    pf_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "preflight.py"
    )
    spec = importlib.util.spec_from_file_location("preflight", pf_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ok, msg = mod.check_redirect_targets()
    assert ok, msg


def test_preflight_catches_stub_with_steps(tmp_path, monkeypatch):
    """Preflight rejects a YAML that has BOTH redirect_to: and steps:."""
    import importlib.util
    import yaml

    pf_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "preflight.py"
    )
    spec = importlib.util.spec_from_file_location("preflight", pf_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Point PROTOCOLS_DIR at a temp dir with a violating stub.
    cat = tmp_path / "cat"
    cat.mkdir()
    (cat / "target.yaml").write_text(yaml.safe_dump({"id": "t", "steps": [{"id": "s"}]}))
    (cat / "bad.yaml").write_text(
        yaml.safe_dump(
            {"id": "bad", "redirect_to": "cat/target", "steps": [{"id": "x"}]}
        )
    )
    monkeypatch.setattr(mod, "PROTOCOLS_DIR", tmp_path)
    ok, msg = mod.check_redirect_targets()
    assert not ok
    assert "mutually exclusive" in msg


def test_preflight_catches_unresolved_redirect(tmp_path, monkeypatch):
    import importlib.util
    import yaml

    pf_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "preflight.py"
    )
    spec = importlib.util.spec_from_file_location("preflight", pf_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cat = tmp_path / "cat"
    cat.mkdir()
    (cat / "stub.yaml").write_text(
        yaml.safe_dump({"id": "s", "redirect_to": "cat/nowhere"})
    )
    monkeypatch.setattr(mod, "PROTOCOLS_DIR", tmp_path)
    ok, msg = mod.check_redirect_targets()
    assert not ok
    assert "nowhere" in msg


# ── phase-14a (v2.0.0): v1.6.1 aliases hard-removed ──────────────


# The 21 names introduced as consolidation aliases in v1.6.1 should now
# return a _REMOVED_TOOLS error envelope naming the canonical entry point.
_V14A_REMOVED_TO_NEW = {
    "tool_search_semantic_scholar": "tool_search",
    "tool_search_pubmed": "tool_search",
    "tool_search_crossref": "tool_search",
    "tool_search_arxiv": "tool_search",
    "tool_search_web": "tool_search",
    "tool_plan_turn": "tool_plan",
    "tool_plan_advance": "tool_plan",
    "tool_plan_clear": "tool_plan",
    "tool_grounding_register": "tool_ground",
    "tool_ground_from_context": "tool_ground",
    "tool_claim_verify": "tool_verify",
    "tool_grounding_verify": "tool_verify",
    "tool_lessons_record": "tool_lessons",
    "tool_lessons_consult": "tool_lessons",
    "sys_path_create": "sys_path",
    "sys_path_abandon": "sys_path",
    "sys_path_list": "sys_path",
    "mem_methods_append": "mem_log",
    "mem_decision_log": "mem_log",
    "mem_hypothesis_update": "mem_log",
    "mem_analysis_log": "mem_log",
}


@pytest.mark.parametrize("removed_name,new_name", sorted(_V14A_REMOVED_TO_NEW.items()))
def test_v14a_removed_alias_returns_friendly_error(
    project_root, removed_name, new_name
):
    """Every first-wave alias hard-removed in phase-14a now returns an
    error envelope whose message names the canonical v2 entry point."""
    r = _handle_tool_call(removed_name, {}, project_root)
    env = _parse_envelope(r)
    assert env["status"] == "error", removed_name
    msg = env.get("error", "")
    assert removed_name in msg, f"{removed_name}: error should name the removed tool"
    assert new_name in msg, f"{removed_name}: error should name the replacement {new_name}"
    assert "v1.6.1" in msg, f"{removed_name}: error should cite when alias was introduced"
    assert "v2.0.0" in msg, f"{removed_name}: error should cite the v2.0.0 removal"


def test_v14a_removed_aliases_dropped_from_tool_definitions():
    """Hard-removed aliases must not advertise themselves in TOOL_DEFINITIONS."""
    from research_os.server import TOOL_DEFINITIONS
    for removed in _V14A_REMOVED_TO_NEW:
        assert removed not in TOOL_DEFINITIONS, (
            f"{removed} is in _REMOVED_TOOLS but still has a TOOL_DEFINITIONS "
            f"entry — that triggers the _annotate_core_tool_metadata warning."
        )


def test_v14a_removed_aliases_dropped_from_alias_table():
    """Hard-removed aliases must not survive in _ALIASES / _DEPRECATED_ALIASES /
    _ALIAS_PARAM_INJECTION."""
    from research_os.server import (
        _ALIAS_PARAM_INJECTION,
        _ALIASES,
        _DEPRECATED_ALIASES,
    )
    for removed in _V14A_REMOVED_TO_NEW:
        assert removed not in _ALIASES, f"{removed} still in _ALIASES"
        assert removed not in _DEPRECATED_ALIASES, (
            f"{removed} still in _DEPRECATED_ALIASES"
        )
        assert removed not in _ALIAS_PARAM_INJECTION, (
            f"{removed} still in _ALIAS_PARAM_INJECTION"
        )


def test_v14a_tool_log_decision_chains_to_mem_log():
    """tool_log_decision is a silent nickname pre-dating v1.6.1; it used to
    chain through mem_decision_log → mem_log. With mem_decision_log removed,
    it now resolves directly to mem_log with kind=decision injected."""
    from research_os.server import _resolve_tool_name
    assert _resolve_tool_name("tool_log_decision") == "mem_log"
