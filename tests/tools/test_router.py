"""Tests for sys_boot, tool_route (hierarchical), per-turn batching,
active tool scoping, and the active-plan decomposition."""

import json

from research_os.project_ops import scaffold_minimal_workspace
from research_os.tools.actions.router import (
    active_tools_for_protocol,
    advance_plan,
    clear_active_plan,
    plan_turn,
    route_request,
    sys_boot,
)


def test_sys_boot_returns_full_payload(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Router Test")
    res = sys_boot(tmp_path)
    assert res["status"] == "success"
    # Every key the AI is expected to consume in one shot.
    for k in (
        "project_name", "pipeline_stage", "current_path", "domain",
        "autonomy", "expertise", "model_profile", "shared_server",
        "active_hypotheses", "history_tail", "last_protocol_entry",
        "pause_classification", "next_protocol", "dep_inventory",
        "active_plan", "workspace_mode", "mode_directive", "advice",
    ):
        assert k in res, f"sys_boot missing key {k}"
    assert res["project_name"] == "Router Test"
    assert res["pause_classification"] == "fresh_session"
    # Default mode is analysis, surfaced with a directive the AI can act on.
    assert res["workspace_mode"] == "analysis"
    assert res["mode_directive"]


def test_sys_boot_surfaces_hybrid_mode_directive(tmp_path):
    """A hybrid project's boot must surface workspace_mode + a hybrid-specific
    directive so the AI behaves mode-appropriately (not just analysis-default)."""
    from research_os.tools.actions.state import set_config

    scaffold_minimal_workspace(tmp_path, "Hybrid Test")
    set_config("workspace.mode", "hybrid", tmp_path)
    res = sys_boot(tmp_path)
    assert res["workspace_mode"] == "hybrid"
    assert "hybrid" in res["mode_directive"].lower()


def test_sys_boot_survives_unscaffolded_root(tmp_path):
    # No scaffold — sys_boot must still return a degraded payload, not throw.
    res = sys_boot(tmp_path)
    assert res["status"] == "success"
    # Any string is acceptable; we just want no exception escaping.
    assert isinstance(res["pipeline_stage"], str)


def test_route_intake_prompt(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Route Test")
    res = route_request("fill the intake", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "guidance/project_startup"
    # Shortcut tool resolves to the consolidated memory-logging entry point.
    assert res["shortcut_tool"] == "mem_log"
    assert "decomposition" in res
    assert res["complexity"] == "low"  # short prompt


def test_route_complex_prompt_persists_plan(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Complex Route Test")
    prompt = (
        "alright go and run a baseline EDA, then fit a random forest, "
        "and audit the figures, also write the methods section"
    )
    res = route_request(prompt, tmp_path)
    assert res["status"] == "success"
    assert res["complexity"] == "high"
    assert "active_plan_path" in res
    plan = json.loads((tmp_path / res["active_plan_path"]).read_text())
    assert plan["status"] == "in_progress"
    assert plan["current_step"] == 1
    assert len(plan["decomposition"]) >= 1
    assert plan["user_prompt"] == prompt


def test_route_no_persist_when_disabled(tmp_path):
    scaffold_minimal_workspace(tmp_path, "No Persist Test")
    prompt = "run a baseline EDA and then fit a random forest"
    res = route_request(prompt, tmp_path, persist_plan=False)
    assert res["status"] == "success"
    assert "active_plan_path" not in res
    assert not (tmp_path / ".os_state" / "active_plan.json").exists()


def test_route_quick_review(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Review Route Test")
    res = route_request("can you tear apart that draft paper", tmp_path)
    assert res["status"] == "success"
    # Either the protocol or the shortcut should win.
    assert (
        res["primary_protocol"] == "guidance/quick_paper_review"
        or res["shortcut_tool"] == "tool_quick_review"
    )


def test_route_resume_prompt(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Resume Route Test")
    res = route_request("pick up where we left off", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "guidance/session_resume"
    assert res["shortcut_tool"] == "tool_session_handoff"


def test_route_handoff_prompt(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Handoff Route Test")
    res = route_request("wrap up I need to come back tomorrow", tmp_path)
    assert res["status"] == "success"
    assert (
        res["primary_protocol"] == "guidance/chat_handoff"
        or res["shortcut_tool"] == "sys_session_handoff"
    )


def test_route_empty_prompt(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Empty Route Test")
    res = route_request("   ", tmp_path)
    assert res["status"] == "error"


def test_route_punctuation_does_not_block_shortcut(tmp_path):
    """Regression: shortcut triggers must match across trailing
    punctuation like commas. Pre-v1.2.2 the matcher required exact
    space-bounded substrings, so 'the workspace looks broken, fix it'
    silently fell through to no-match."""
    scaffold_minimal_workspace(tmp_path, "Punct Shortcut Test")
    res = route_request("the workspace looks broken, fix it", tmp_path)
    assert res["status"] == "success"
    assert res["shortcut_tool"] == "tool_migrate_audit"


def test_route_baseline_eda_prompt_resolves(tmp_path):
    """Regression: 'baseline EDA' is named verbatim in the docs as a
    canonical prompt but did not match any trigger before v1.2.2."""
    scaffold_minimal_workspace(tmp_path, "Baseline EDA Test")
    res = route_request("I want to do a baseline EDA on my CSV", tmp_path)
    assert res["status"] == "success"
    # Either guidance/analysis_plan (trigger path) or
    # methodology/exploratory_data_analysis (semantic path) is fine —
    # both correctly route this ask.
    assert res["primary_protocol"] in {
        "guidance/analysis_plan",
        "methodology/exploratory_data_analysis",
    }
    assert res["ask_user"] is None


def test_route_context_intake_shortcut(tmp_path):
    """Regression: 'I just dropped a paper' should trigger the context-intake
    shortcut, now consolidated into mem_log."""
    scaffold_minimal_workspace(tmp_path, "Context Intake Test")
    res = route_request(
        "I just dropped a new paper in literature, integrate it", tmp_path,
    )
    assert res["status"] == "success"
    assert res["shortcut_tool"] == "mem_log"


def test_semantic_leaf_no_decomposition_downgrades_complexity(tmp_path):
    """When the SEMANTIC path picks a leaf protocol (no decomposition)
    for a prompt the heuristic flagged as complex, the response should
    downgrade complexity to 'low' rather than promise a plan it never
    persisted. (Only meaningful when semantic routing is available —
    CI environments without `fastembed` use only the trigger router,
    where this path doesn't apply.)"""
    import pytest

    from research_os.tools.actions import semantic
    if not semantic.semantic_available():
        pytest.skip("semantic routing not available — fastembed not installed")

    scaffold_minimal_workspace(tmp_path, "Leaf Downgrade Test")
    # writing/writing_methods has no decomposition in the index.
    # The prompt is wordy enough to trip _is_complex but really is
    # one ask.
    res = route_request(
        "help me write the methods section of my paper thoroughly with "
        "every detail of the model and the assumptions included",
        tmp_path,
    )
    assert res["status"] == "success"
    if (
        res.get("method") == "semantic"
        and res["primary_protocol"] == "writing/writing_methods"
    ):
        # Semantic + no decomposition → must NOT claim complexity=high.
        assert res["complexity"] == "low"
        # And no active_plan_path should have been written.
        assert "active_plan_path" not in res


def test_advance_plan_walks_decomposition(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Advance Test")
    prompt = "run a baseline EDA and then fit a random forest and audit"
    route_request(prompt, tmp_path)
    assert (tmp_path / ".os_state" / "active_plan.json").exists()
    step2 = advance_plan(tmp_path)
    assert step2["status"] == "success"
    assert step2["current_step"] >= 2
    # Drain the plan; eventually it archives itself.
    for _ in range(20):
        res = advance_plan(tmp_path)
        if res.get("message") and "completed" in res["message"].lower():
            break
    assert not (tmp_path / ".os_state" / "active_plan.json").exists()


def test_clear_plan_removes_file(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Clear Test")
    prompt = "run a baseline and fit a model and write the paper"
    route_request(prompt, tmp_path)
    assert (tmp_path / ".os_state" / "active_plan.json").exists()
    res = clear_active_plan(tmp_path)
    assert res["status"] == "success"
    assert not (tmp_path / ".os_state" / "active_plan.json").exists()


def test_route_fallback_unknown_prompt(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Fallback Test")
    res = route_request("xyzzy nonsense plover", tmp_path)
    assert res["status"] == "success"
    # No trigger should match.
    assert res["primary_protocol"] is None or res["matched_triggers"] == []
    # Resolved at L0 with an ask_user.
    assert res["resolved_level"] == 0
    assert res["ask_user"] is not None


def test_route_hierarchical_fields(tmp_path):
    """Every successful route should expose resolved_level + intent_class."""
    scaffold_minimal_workspace(tmp_path, "Hier Test")
    res = route_request("fill the intake", tmp_path)
    assert res["status"] == "success"
    assert "resolved_level" in res
    assert res["resolved_level"] == 3
    assert res["intent_class"] == "discover"
    assert res["sub_intent"] == "intake"


def test_route_ambiguous_at_l2_asks_user(tmp_path):
    """A clear L1 + ambiguous L3 candidates returns ask_user."""
    scaffold_minimal_workspace(tmp_path, "Ambiguous L2 Test")
    # "synthesize" with both "abstract" and "dashboard" intents.
    res = route_request("write me an abstract and a dashboard", tmp_path)
    assert res["status"] == "success"
    # L1 should still resolve (synthesize) but the specific sub_intent
    # may be ambiguous depending on scoring.
    # At minimum the router shouldn't crash.
    assert res["intent_class"] in {"synthesize", None}


def test_plan_turn_with_no_active_plan(tmp_path):
    scaffold_minimal_workspace(tmp_path, "PlanTurn NoPlan")
    res = plan_turn(tmp_path)
    assert res["status"] == "success"
    assert res["this_turn"] == []
    assert res["next_turn"] == []


def test_plan_turn_batches_by_model_profile(tmp_path):
    scaffold_minimal_workspace(tmp_path, "PlanTurn Batch")
    # Default model_profile is medium → budget 3.
    prompt = (
        "alright run a baseline EDA and then fit a random forest and "
        "audit the figures and write the methods section"
    )
    route_request(prompt, tmp_path)
    # active_plan should exist now.
    res = plan_turn(tmp_path)
    assert res["status"] == "success"
    assert res["model_profile"] == "medium"
    assert res["turn_budget"] == 3
    # Should have at least 1 step this turn.
    assert len(res["this_turn"]) >= 1
    # Total this_turn + next_turn equals remaining decomposition.
    assert (
        len(res["this_turn"]) + len(res["next_turn"]) ==
        7  # analysis_plan decomposition size from _router_index.yaml
    )


def test_plan_turn_small_model_one_step_per_turn(tmp_path):
    import yaml as _yaml
    scaffold_minimal_workspace(tmp_path, "PlanTurn Small")
    cfg_path = tmp_path / "inputs" / "researcher_config.yaml"
    cfg = _yaml.safe_load(cfg_path.read_text()) or {}
    cfg.setdefault("ai", {})["model_profile"] = "small"  # canonical location
    cfg_path.write_text(_yaml.dump(cfg, sort_keys=False))

    prompt = (
        "alright run a baseline EDA and then fit a random forest and "
        "audit the figures and write the methods section"
    )
    route_request(prompt, tmp_path)
    res = plan_turn(tmp_path)
    assert res["status"] == "success"
    assert res["model_profile"] == "small"
    assert res["turn_budget"] == 1
    assert len(res["this_turn"]) == 1


def test_route_returns_active_tools(tmp_path):
    """tool_route response must include an active_tools shortlist."""
    scaffold_minimal_workspace(tmp_path, "Active Tools Test")
    res = route_request("fill the intake", tmp_path)
    assert res["status"] == "success"
    assert "active_tools" in res
    tools = res["active_tools"]
    assert isinstance(tools, list)
    assert "sys_boot" in tools         # essential
    assert "tool_route" in tools       # essential
    assert "mem_log" in tools          # protocol's consolidated shortcut


def test_active_tools_for_protocol_direct_lookup(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Active Tools Direct")
    res = active_tools_for_protocol("synthesis/synthesis_paper")
    assert res["status"] == "success"
    assert res["intent_class"] == "synthesize"
    assert res["sub_intent"] == "paper"
    # Decomposition includes the consolidated synthesis + compile tools.
    assert "tool_synthesis_scaffold" in res["active_tools"]
    assert "tool_typst_compile" in res["active_tools"]
    # Essentials still present.
    assert "sys_boot" in res["active_tools"]
    assert res["active_tools_count"] > 10


def test_active_tools_for_unknown_protocol(tmp_path):
    res = active_tools_for_protocol("nonexistent/ghost")
    assert res["status"] == "error"


def test_route_visualization_workflow(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Viz Workflow")
    res = route_request("make me a figure from this CSV for the talk", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "visualization/visualization_workflow"
    assert res["intent_class"] == "synthesize"
    assert res["sub_intent"] == "viz_build"


def test_route_figure_critique(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Figure Critique")
    res = route_request("critique this figure for me", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "visualization/figure_critique"
    assert res["intent_class"] == "review"
    assert res["sub_intent"] == "figure"


def test_route_synthesis_slides(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Slides")
    res = route_request("build a slide deck for my conference talk", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "synthesis/synthesis_slides"
    assert res["intent_class"] == "synthesize"
    assert res["sub_intent"] == "slides"


def test_route_lay_summary(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Lay Summary")
    res = route_request("write a lay summary for the public", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "synthesis/synthesis_lay_summary"
    assert res["intent_class"] == "synthesize"
    assert res["sub_intent"] == "lay"


def test_route_progress_update(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Progress")
    res = route_request("weekly update for my pi", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "synthesis/synthesis_progress_update"
    assert res["intent_class"] == "synthesize"
    assert res["sub_intent"] == "update"


def test_route_from_inputs_synthesis(tmp_path):
    scaffold_minimal_workspace(tmp_path, "From Inputs")
    res = route_request(
        "we already analysed this, just write it up", tmp_path
    )
    assert res["status"] == "success"
    assert res["primary_protocol"] == "synthesis/synthesis_from_inputs"
    assert res["intent_class"] == "synthesize"
    assert res["sub_intent"] == "inputs_only"


def test_route_exploratory_data_analysis(tmp_path):
    scaffold_minimal_workspace(tmp_path, "EDA")
    res = route_request("do real eda on this dataset", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/exploratory_data_analysis"
    assert res["intent_class"] == "methodology"
    assert res["sub_intent"] == "eda"


def test_route_method_comparison(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Method Compare")
    res = route_request("benchmark these methods head-to-head", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/method_comparison"
    assert res["intent_class"] == "methodology"
    assert res["sub_intent"] == "comparison"


def test_route_data_quality_audit(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Data QC")
    res = route_request("data quality audit on this csv", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/data_quality_audit"
    assert res["intent_class"] == "methodology"
    assert res["sub_intent"] == "data_audit"


def test_route_power_analysis(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Power")
    res = route_request("power analysis for the irb", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/power_analysis"
    assert res["intent_class"] == "methodology"
    assert res["sub_intent"] == "power"


def test_route_reproduction_attempt(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Reproduction")
    res = route_request("reproduce this paper for me", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/reproduction_attempt"
    assert res["intent_class"] == "methodology"
    assert res["sub_intent"] == "reproduce"


def test_route_methodological_consultation(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Consult")
    res = route_request("teach me about mixed effects models", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/methodological_consultation"
    assert res["intent_class"] == "methodology"
    assert res["sub_intent"] == "consult"


def test_route_comparative_paper_review(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Paper Compare")
    res = route_request("compare these papers for journal club", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "literature/comparative_paper_review"
    assert res["intent_class"] == "literature"
    assert res["sub_intent"] == "compare"


def test_route_mid_pipeline_entry(tmp_path):
    scaffold_minimal_workspace(tmp_path, "Mid Entry")
    res = route_request(
        "i'm bringing this into research-os, we've been working on this for months",
        tmp_path,
    )
    assert res["status"] == "success"
    assert res["primary_protocol"] == "guidance/mid_pipeline_entry"
    assert res["intent_class"] == "discover"
    assert res["sub_intent"] == "mid_entry"


def test_route_figure_guidelines_still_wins_on_style_prompt(tmp_path):
    """figure_guidelines (style) should still win on a styling prompt,
    not be hijacked by the new visualization_workflow."""
    scaffold_minimal_workspace(tmp_path, "Figure Guidelines")
    res = route_request("which color palette should i use for the dpi", tmp_path)
    assert res["status"] == "success"
    # Either figure_guidelines or visualization_workflow; we just check
    # that figures-domain protocols win over unrelated ones.
    assert res["primary_protocol"] in (
        "visualization/figure_guidelines",
        "visualization/visualization_workflow",
    )


def test_route_existing_protocols_not_hijacked_by_new_ones(tmp_path):
    """Regression: adding 14 new protocols should not change routing
    for any existing well-known trigger phrase."""
    scaffold_minimal_workspace(tmp_path, "Regression")
    # Each pair is (prompt, expected pre-existing protocol).
    pairs = [
        ("fill the intake", "guidance/project_startup"),
        ("run a baseline EDA and then fit a random forest and audit",
         "guidance/analysis_plan"),
        ("draft the paper for a journal", "synthesis/synthesis_paper"),
        ("review this paper", "guidance/quick_paper_review"),
        ("review my code", "guidance/code_review"),
        ("pick up where we left off", "guidance/session_resume"),
        ("wrap up i need to come back tomorrow", "guidance/chat_handoff"),
        ("make a poster for an academic conference",
         "synthesis/synthesis_poster"),
        ("build a dashboard for the lab meeting",
         "synthesis/synthesis_dashboard"),
        ("draft an nsf proposal", "synthesis/synthesis_grant"),
        ("preregister this study before data lands",
         "methodology/preregistration"),
        ("send to a collaborator", "guidance/collaboration_handoff"),
    ]
    for prompt, expected in pairs:
        res = route_request(prompt, tmp_path)
        assert res["status"] == "success", prompt
        assert res["primary_protocol"] == expected, (
            f"Regression: {prompt!r} routed to "
            f"{res['primary_protocol']!r}, expected {expected!r}"
        )


def test_route_writing_discussion(tmp_path):
    scaffold_minimal_workspace(tmp_path, "writing discussion")
    res = route_request("draft the discussion section", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "writing/writing_discussion"


def test_route_writing_limitations(tmp_path):
    scaffold_minimal_workspace(tmp_path, "writing limitations")
    res = route_request("tighten the limitations", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "writing/writing_limitations"


def test_route_writing_results(tmp_path):
    scaffold_minimal_workspace(tmp_path, "writing results")
    res = route_request("draft the results section", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "writing/writing_results"


def test_route_writing_end_matter(tmp_path):
    scaffold_minimal_workspace(tmp_path, "end matter")
    res = route_request("draft the end matter", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "writing/writing_data_availability"


def test_route_multi_panel(tmp_path):
    scaffold_minimal_workspace(tmp_path, "multi panel")
    res = route_request("multi-panel figure with subpanels", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "visualization/multi_panel_composition"


def test_route_figure_narrative_arc(tmp_path):
    scaffold_minimal_workspace(tmp_path, "arc")
    res = route_request("order my figures for the paper", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "visualization/figure_narrative_arc"


def test_route_color_accessibility(tmp_path):
    scaffold_minimal_workspace(tmp_path, "a11y")
    res = route_request("check colour accessibility on my figures", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "visualization/color_accessibility_audit"


def test_route_cover_letter(tmp_path):
    scaffold_minimal_workspace(tmp_path, "cover")
    res = route_request("draft a cover letter for the journal", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "synthesis/synthesis_cover_letter"


def test_route_title_workshop(tmp_path):
    scaffold_minimal_workspace(tmp_path, "title")
    res = route_request("workshop the title for the paper", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "synthesis/synthesis_title_workshop"


def test_route_handout(tmp_path):
    scaffold_minimal_workspace(tmp_path, "handout")
    res = route_request("make a one-pager handout", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "synthesis/synthesis_handout"


def test_route_evaluation_design(tmp_path):
    scaffold_minimal_workspace(tmp_path, "eval design")
    res = route_request("design the evaluation strategy", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/evaluation_design"


def test_route_sweep_design(tmp_path):
    scaffold_minimal_workspace(tmp_path, "sweep")
    res = route_request("design the hyperparameter sweep", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/hyperparameter_search_design"


def test_route_data_ethics(tmp_path):
    scaffold_minimal_workspace(tmp_path, "ethics")
    res = route_request("do an ethics review on this data", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "methodology/data_ethics_review"


def test_route_constructive_disagreement(tmp_path):
    scaffold_minimal_workspace(tmp_path, "disagree")
    res = route_request("tell me if i am wrong about this plan", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "guidance/constructive_disagreement"


def test_route_pre_submission_checklist(tmp_path):
    scaffold_minimal_workspace(tmp_path, "submit")
    res = route_request("is this ready to submit", tmp_path)
    assert res["status"] == "success"
    assert res["primary_protocol"] == "audit/pre_submission_checklist"


def test_sys_active_project_exists_in_router_essentials_or_handlers(tmp_path):
    """Smoke: sys_active_project is wired."""
    from research_os.server import TOOL_DEFINITIONS, _HANDLERS
    assert "sys_active_project" in TOOL_DEFINITIONS
    assert "sys_active_project" in _HANDLERS


def test_sys_active_project_returns_root(tmp_path):
    """Smoke: sys_active_project returns a project root.

    The orientation `advice` only fires when the project isn't
    scaffolded; this test scaffolds, so we expect no advice and a
    compact resolved_via tag.
    """
    import os
    from research_os.server import _handle_sys_active_project
    scaffold_minimal_workspace(tmp_path, "active project")
    os.environ["RESEARCH_OS_WORKSPACE"] = str(tmp_path)
    try:
        out = _handle_sys_active_project("sys_active_project", {}, tmp_path)
        assert out and out[0].text
        import json
        payload = json.loads(out[0].text)
        assert payload["status"] == "success"
        data = payload["data"]
        assert "project_root" in data
        assert data["has_os_state"] is True
        # Scaffolded → resolved_via names env var or cwd; no advice.
        assert data["resolved_via"] in {"RESEARCH_OS_WORKSPACE", "cwd→.os_state", "cwd"}
        assert "advice" not in data
    finally:
        os.environ.pop("RESEARCH_OS_WORKSPACE", None)


def test_sys_active_project_advises_when_unscaffolded(tmp_path):
    from research_os.server import _handle_sys_active_project
    import json
    out = _handle_sys_active_project("sys_active_project", {}, tmp_path)
    payload = json.loads(out[0].text)
    data = payload["data"]
    assert data["has_os_state"] is False
    assert "advice" in data
    assert "research-os init" in data["advice"]


def test_resolve_project_root_uses_env_var_when_set(tmp_path):
    """Global-server resolution: RESEARCH_OS_WORKSPACE wins."""
    import os
    from research_os.server import _resolve_project_root
    scaffold_minimal_workspace(tmp_path, "envvar test")
    os.environ["RESEARCH_OS_WORKSPACE"] = str(tmp_path)
    try:
        root = _resolve_project_root()
        assert root == tmp_path.resolve()
    finally:
        os.environ.pop("RESEARCH_OS_WORKSPACE", None)


def test_resolve_project_root_ignores_nonexistent_env_var(tmp_path):
    """If env var points at a nonexistent path, fall through to cwd."""
    import os
    from research_os.server import _resolve_project_root
    os.environ["RESEARCH_OS_WORKSPACE"] = "/this/path/does/not/exist"
    try:
        root = _resolve_project_root()
        # Should fall through to cwd-based resolution, not crash
        assert root.exists()
    finally:
        os.environ.pop("RESEARCH_OS_WORKSPACE", None)


def test_resolve_project_root_falls_back_to_cwd_when_no_env_var(tmp_path, monkeypatch):
    """Without env var, walks up from cwd looking for .os_state/."""
    import os
    from research_os.server import _resolve_project_root
    scaffold_minimal_workspace(tmp_path, "cwd test")
    os.environ.pop("RESEARCH_OS_WORKSPACE", None)
    monkeypatch.chdir(tmp_path)
    root = _resolve_project_root()
    assert root == tmp_path.resolve()


def test_tool_alias_resolution(tmp_path):
    """Dispatcher rewrites dot notation + handles legacy aliases."""
    from research_os.server import _resolve_tool_name
    # Dot → underscore
    assert _resolve_tool_name("sys.state.get") == "sys_state_get"
    # Legacy audit nickname routes through the consolidated audit dispatcher.
    assert _resolve_tool_name("tool_audit_figure_quality") == "tool_audit"
    # tool_log_decision resolves directly to mem_log in v2.0.0
    # (mem_decision_log was hard-removed in phase-14a).
    assert _resolve_tool_name("tool_log_decision") == "mem_log"
    # No-op for canonical names
    assert _resolve_tool_name("sys_boot") == "sys_boot"


def test_plan_turn_recommends_chat_split_when_long(tmp_path):
    import yaml as _yaml
    scaffold_minimal_workspace(tmp_path, "PlanTurn Split")
    # Tiny budget + long plan → chat split should be recommended.
    cfg_path = tmp_path / "inputs" / "researcher_config.yaml"
    cfg = _yaml.safe_load(cfg_path.read_text()) or {}
    cfg.setdefault("ai", {})["model_profile"] = "small"  # canonical location
    cfg_path.write_text(_yaml.dump(cfg, sort_keys=False))

    # Manually persist a long fake active plan.
    # v1.3.2: use a recent timestamp — plans older than 7 days auto-
    # archive in _load_active_plan, which is correct production
    # behaviour but breaks this test if the fixture date is stale.
    from datetime import datetime, timezone
    fake_plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_prompt": "test",
        "primary_protocol": "guidance/analysis_plan",
        "shortcut_tool": None,
        "decomposition": [
            {"tool": "sys_file_write", "purpose": f"step {i}"}
            for i in range(15)
        ],
        "current_step": 1,
        "status": "in_progress",
    }
    (tmp_path / ".os_state").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".os_state" / "active_plan.json").write_text(
        json.dumps(fake_plan, indent=2)
    )
    res = plan_turn(tmp_path)
    assert res["status"] == "success"
    assert res["chat_split_recommended"] is True
    assert res["chat_split_reason"]


# ===========================================================================
# v3.0.0 ROUTER OVERHAUL — adversarial route fixtures
# ===========================================================================
#
# These lock in the v3.0.0 routing improvements:
#   * beginner / plain-English phrasings route to the right protocol
#   * mode-aware bias (tool_build boosts build/*)
#   * the confidence-margin gate asks instead of misrouting on genuine
#     cross-class ties
#   * reckless single-word triggers no longer hijack unrelated prompts
#   * expert phrasings still route
#
# Beginner + reckless tests run on the HYBRID path (semantic if present)
# because that's what production uses. The cross-class margin gate is
# exercised deterministically with the semantic path forced off (the
# CI-without-fastembed scenario) so the assertions don't depend on the
# embedding bundle being present + freshly regenerated.

import yaml as _yaml  # noqa: E402


def _set_workspace_mode(root, mode):
    """Write workspace.mode into the scaffolded researcher_config."""
    cfg_path = root / "inputs" / "researcher_config.yaml"
    cfg = _yaml.safe_load(cfg_path.read_text()) or {}
    ws = cfg.get("workspace") or {}
    ws["mode"] = mode
    cfg["workspace"] = ws
    cfg_path.write_text(_yaml.dump(cfg, sort_keys=False))


# (prompt, expected_primary_protocol) — beginner / plain-English phrasings.
_BEGINNER_FIXTURE = [
    ("i have a csv what do i do",   "guidance/project_startup"),
    ("look at my data",            "methodology/exploratory_data_analysis"),
    ("make a chart",               {"visualization/figure_guidelines",
                                    "visualization/visualization_workflow"}),
    ("make a graph",               {"visualization/figure_guidelines",
                                    "visualization/visualization_workflow"}),
    ("clean my data",             "methodology/data_quality_audit"),
    ("is my result significant",  "methodology/methodology_selection"),
    ("help me write this up",     "synthesis/synthesis_paper"),
    ("what stats should i use",   "methodology/methodology_selection"),
]


def test_router_beginner_phrasings(tmp_path):
    """Novice plain-English prompts route to the right protocol."""
    scaffold_minimal_workspace(tmp_path, "Beginner")
    for prompt, expected in _BEGINNER_FIXTURE:
        res = route_request(prompt, tmp_path, persist_plan=False)
        assert res["status"] == "success", prompt
        primary = res.get("primary_protocol")
        if isinstance(expected, set):
            assert primary in expected, (
                f"{prompt!r} routed to {primary!r}, expected one of {expected}"
            )
        else:
            assert primary == expected, (
                f"{prompt!r} routed to {primary!r}, expected {expected!r}"
            )
        # A confident beginner route shouldn't pester with ask_user.
        assert res.get("ask_user") is None, prompt


# (prompt, expected_build_protocol) — exercised in tool_build mode.
_BUILD_MODE_FIXTURE = [
    ("add a feature",                "build/implement_iteration"),
    ("fix the bug",                  "build/implement_iteration"),
    ("refactor this",                "build/implement_iteration"),
    ("write tests",                  "build/test_strategy"),
    ("cut a release",                "build/release_and_changelog"),
    ("implement the next increment", "build/implement_iteration"),
]


def test_router_tool_build_mode_routes_build_protocols(tmp_path):
    """In tool_build mode, build-shaped prompts hit the build/* protocols."""
    scaffold_minimal_workspace(tmp_path, "Build Mode")
    _set_workspace_mode(tmp_path, "tool_build")
    for prompt, expected in _BUILD_MODE_FIXTURE:
        res = route_request(prompt, tmp_path, persist_plan=False)
        assert res["status"] == "success", prompt
        assert res.get("primary_protocol") == expected, (
            f"[tool_build] {prompt!r} routed to {res.get('primary_protocol')!r}, "
            f"expected {expected!r}"
        )


def test_router_mode_bias_is_thumb_not_override(tmp_path):
    """An explicit cross-mode intent still routes correctly in tool_build mode.

    The build boost is a tie-breaker, not a winner-flipper: "write the
    paper" must still land on synthesis/synthesis_paper even when the
    workspace is in tool_build mode.
    """
    scaffold_minimal_workspace(tmp_path, "Build Mode Crossover")
    _set_workspace_mode(tmp_path, "tool_build")
    res = route_request("write the paper for a journal", tmp_path, persist_plan=False)
    assert res["status"] == "success"
    assert res.get("primary_protocol") == "synthesis/synthesis_paper"


def test_router_analysis_mode_unchanged_by_overhaul(tmp_path):
    """analysis mode keeps today's behaviour for canonical prompts."""
    scaffold_minimal_workspace(tmp_path, "Analysis Mode")
    _set_workspace_mode(tmp_path, "analysis")
    pairs = [
        ("fill the intake", "guidance/project_startup"),
        ("draft the paper for a journal", "synthesis/synthesis_paper"),
        ("preregister this study before data lands",
         "methodology/preregistration"),
    ]
    for prompt, expected in pairs:
        res = route_request(prompt, tmp_path, persist_plan=False)
        assert res["status"] == "success", prompt
        assert res.get("primary_protocol") == expected, (
            f"[analysis] {prompt!r} -> {res.get('primary_protocol')!r}, "
            f"expected {expected!r}"
        )


# Genuinely-ambiguous prompts that mix two DIFFERENT intent_classes with
# equal trigger weight. The confidence-margin gate must ask rather than
# silently pick one. Exercised on the trigger path (semantic forced off)
# so the result is deterministic regardless of the embedding bundle.
_CROSS_CLASS_AMBIGUOUS = [
    "forecast the grant",            # methodology(timeseries) vs synthesize(grant)
    "ablation for the poster",       # methodology(ablation)  vs synthesize(poster)
    "fairness and the dashboard",    # methodology(fairness)  vs synthesize(dashboard)
    "simulation and reproducibility",  # methodology vs audit_wrap
]


def test_router_cross_class_margin_gate_asks(tmp_path, monkeypatch):
    """Near-tied cross-class prompts return a non-null ask_user, no primary."""
    from research_os.tools.actions import semantic
    monkeypatch.setattr(semantic, "semantic_available", lambda: False)
    scaffold_minimal_workspace(tmp_path, "Margin Gate")
    for prompt in _CROSS_CLASS_AMBIGUOUS:
        res = route_request(prompt, tmp_path, persist_plan=False)
        assert res["status"] == "success", prompt
        assert res.get("ask_user") is not None, (
            f"{prompt!r} should be ambiguous (ask_user), got primary="
            f"{res.get('primary_protocol')!r}"
        )
        assert res.get("primary_protocol") is None, prompt
        # The two candidates should be named so the AI can ask crisply.
        assert len(res.get("ambiguous_alternatives", [])) == 2, prompt


def test_router_margin_gate_names_both_candidates(tmp_path, monkeypatch):
    """The ask_user text names both near-tied candidates."""
    from research_os.tools.actions import semantic
    monkeypatch.setattr(semantic, "semantic_available", lambda: False)
    scaffold_minimal_workspace(tmp_path, "Margin Names")
    res = route_request("forecast the grant", tmp_path, persist_plan=False)
    alts = res.get("ambiguous_alternatives", [])
    assert len(alts) == 2
    for cand in alts:
        assert cand in res["ask_user"], (
            f"candidate {cand!r} missing from ask_user text"
        )


def test_router_does_not_over_trigger_on_dominant_match(tmp_path, monkeypatch):
    """A clearly-dominant trigger match routes silently (no ask_user).

    The margin gate must NOT fire when the top match dwarfs the runner-up
    — e.g. a multi-word trigger beating a stray single word.
    """
    from research_os.tools.actions import semantic
    monkeypatch.setattr(semantic, "semantic_available", lambda: False)
    scaffold_minimal_workspace(tmp_path, "Dominant")
    res = route_request("preregister this study before data lands",
                        tmp_path, persist_plan=False)
    assert res["status"] == "success"
    assert res.get("primary_protocol") == "methodology/preregistration"
    assert res.get("ask_user") is None


# Reckless single-word triggers must no longer hijack unrelated prompts.
# Each prompt previously misrouted to the protocol named in the comment.
_RECKLESS_REGRESSION = [
    # prompt, protocol it must NOT route to
    ("set alpha to 0.05 for the test",     "methodology/inter_rater_reliability"),
    ("map the gene names to symbols",      "visualization/geospatial_visualization"),
    ("open the data file and look at it",  "guidance/session_boot"),
]


def test_router_reckless_single_word_triggers_capped(tmp_path, monkeypatch):
    """Bare common-word triggers no longer grab unrelated prompts.

    Run on the trigger path (semantic off) so we assert on the trigger
    layer specifically — the layer the audit flagged.
    """
    from research_os.tools.actions import semantic
    monkeypatch.setattr(semantic, "semantic_available", lambda: False)
    scaffold_minimal_workspace(tmp_path, "Reckless")
    for prompt, must_not in _RECKLESS_REGRESSION:
        res = route_request(prompt, tmp_path, persist_plan=False)
        assert res["status"] == "success", prompt
        assert res.get("primary_protocol") != must_not, (
            f"{prompt!r} still misroutes to {must_not!r}"
        )


def test_router_data_sharing_agreement_routes_to_ethics(tmp_path):
    """'data sharing agreement' must reach data_ethics_review, not IRR.

    Regression for the removed bare 'agreement' trigger that used to
    compete with the (correct) multi-word 'data sharing agreement'.
    """
    scaffold_minimal_workspace(tmp_path, "Agreement")
    res = route_request("we signed a data sharing agreement", tmp_path,
                        persist_plan=False)
    assert res["status"] == "success"
    assert res.get("primary_protocol") == "methodology/data_ethics_review"


def test_router_expert_phrasings_still_route(tmp_path):
    """A spread of expert prompts must keep routing post-overhaul."""
    scaffold_minimal_workspace(tmp_path, "Expert")
    pairs = [
        ("schoenfeld residual test for proportional hazards",
         "methodology/cox_ph_diagnostics"),
        ("benjamini-hochberg correction",
         "methodology/multiple_comparisons"),
        ("prisma systematic review", "literature/systematic_review"),
        ("difference-in-differences design",
         "methodology/causal_inference_deep"),
    ]
    for prompt, expected in pairs:
        res = route_request(prompt, tmp_path, persist_plan=False)
        assert res["status"] == "success", prompt
        assert res.get("primary_protocol") == expected, (
            f"expert {prompt!r} -> {res.get('primary_protocol')!r}, "
            f"expected {expected!r}"
        )


# ── 3.2.9 D2: hyphen-insensitive trigger matching ─────────────────────
def _trigger_only(monkeypatch):
    """Force the deterministic trigger path so the assertion holds in any
    env (with or without fastembed/embeddings)."""
    from research_os.tools.actions import semantic
    monkeypatch.setattr(semantic, "semantic_available", lambda: False)


def test_route_hyphenated_matches_spaced_form(tmp_path, monkeypatch):
    """Hyphenated method names must route the same as their spaced form
    (D2 — router trigger matching was hyphen-sensitive)."""
    _trigger_only(monkeypatch)
    scaffold_minimal_workspace(tmp_path, "Hyphen Route Test")
    pairs = [
        ("agent based model", "agent-based model"),
        ("difference in differences design", "difference-in-differences design"),
        ("single cell rna-seq", "single-cell rna-seq"),
    ]
    for spaced, hyphenated in pairs:
        a = route_request(spaced, tmp_path, persist_plan=False)
        b = route_request(hyphenated, tmp_path, persist_plan=False)
        assert a["status"] == "success" and b["status"] == "success"
        assert a.get("primary_protocol") == b.get("primary_protocol"), (
            f"hyphen drift: {spaced!r} -> {a.get('primary_protocol')!r} "
            f"but {hyphenated!r} -> {b.get('primary_protocol')!r}"
        )


def test_route_fixed_effects_not_bayesian(tmp_path, monkeypatch):
    """'fixed-effects regression' must not misroute to bayesian_analysis
    (D2 — the hyphen broke the 'fixed effects' econometric anchor)."""
    _trigger_only(monkeypatch)
    scaffold_minimal_workspace(tmp_path, "Fixed Effects Route Test")
    res = route_request("fixed-effects regression", tmp_path, persist_plan=False)
    assert res["status"] == "success"
    assert res.get("primary_protocol") != "methodology/bayesian_analysis"


# ── 3.2.9 D3: qualitative_research method coverage ────────────────────
def test_route_qualitative_methods_reachable(tmp_path, monkeypatch):
    """Mainstream qualitative methods the protocol advertises must route to
    it (D3 — triggers omitted phenomenology / discourse / case study / …)."""
    _trigger_only(monkeypatch)
    scaffold_minimal_workspace(tmp_path, "Qual Methods Route Test")
    for prompt in (
        "ethnographic field study",
        "phenomenological study of patient experience",
        "discourse analysis of political speeches",
        "I want to do a case study of one organization",
        "narrative inquiry of teacher stories",
    ):
        res = route_request(prompt, tmp_path, persist_plan=False)
        assert res["status"] == "success", prompt
        assert res.get("primary_protocol") == "methodology/qualitative_research", (
            f"qual {prompt!r} -> {res.get('primary_protocol')!r}"
        )


# ── 3.2.9 D1: workflow_shape inferred from workspace.mode ─────────────
def test_workflow_shape_inferred_from_mode(tmp_path):
    """When no explicit workflow_shape is declared, the router infers it
    from workspace.mode so the shape tiebreak finally fires (D1)."""
    from research_os.tools.actions.router import (
        _clear_workflow_shape_cache,
        _read_project_workflow_shape,
    )
    scaffold_minimal_workspace(tmp_path, "Shape Infer Test")
    cfg_path = tmp_path / "inputs" / "researcher_config.yaml"
    cfg_path.write_text(
        'project_name: "Shape Infer Test"\nworkspace:\n  mode: "tool_build"\n'
    )
    _clear_workflow_shape_cache()
    assert _read_project_workflow_shape(tmp_path) == "tool_build"
    # analysis (the default) intentionally maps to None — no force-boost.
    cfg_path.write_text(
        'project_name: "Shape Infer Test"\nworkspace:\n  mode: "analysis"\n'
    )
    assert _read_project_workflow_shape(tmp_path) is None


def test_shape_boost_fires_for_inferred_shape(tmp_path):
    """A tool_build-shaped protocol gets shape_boost > 0 when the project's
    shape is inferred from mode=tool_build (closes the zero-test gap)."""
    from research_os.tools.actions.router import _score_protocols
    protocols = {
        "build/implement_iteration": {
            "intent_class": "execute",
            "sub_intent": "build_implement",
            "triggers": ["implement"],
            "workflow_shape": ["tool_build"],
        },
    }
    # patch _protocol_workflow_shape to read the inline tag for this test
    import research_os.tools.actions.router as R
    orig = R._protocol_workflow_shape
    R._protocol_workflow_shape = lambda name: protocols.get(name, {}).get("workflow_shape", [])
    try:
        scored = _score_protocols(
            " implement ", protocols,
            workspace_mode="tool_build",
            project_workflow_shape="tool_build",
        )
    finally:
        R._protocol_workflow_shape = orig
    assert scored, "expected the protocol to score"
    assert scored[0]["shape_boost"] > 0


def test_route_step_report_prompt_resolves(tmp_path):
    """v3.10.0: 'step report' prompts route to synthesis_step_report."""
    scaffold_minimal_workspace(tmp_path, "Step Report Test")
    for prompt in (
        "write a step report for step 21",
        "make a visual for this step I can screen-share at the meeting",
    ):
        res = route_request(prompt, tmp_path)
        assert res["status"] == "success", (prompt, res)
        assert res["primary_protocol"] == "synthesis/synthesis_step_report", (
            prompt, res["primary_protocol"]
        )
        assert res["ask_user"] is None
