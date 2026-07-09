"""Tool aliases, deprecated-alias telemetry, alias-param injection, removed tools.

Two flavours of alias:
* non-deprecated nickname aliases (old typos / colloquial names) — silent.
* this-release consolidation aliases — flagged in _DEPRECATED_ALIASES;
  hits log to .os_state/deprecations.log so projects can audit usage
  before the next major (when aliases hard-remove).
"""
from __future__ import annotations

from typing import Any


# ── Resolving aliases (target MUST be one of the 46 live tools) ──────────────
# Kept deliberately small (currently 17 — every entry is tested or param-
# injected). Everything not listed here is either a live tool name (callable
# directly) or a _REMOVED_TOOLS entry (friendly error message).
_ALIASES: dict[str, str] = {
    # ── orientation / boot ritual aliases ──────────────────────────────────
    "sys_where":                    "sys_boot",
    "sys_config":                   "sys_boot",

    # ── state aliases ──────────────────────────────────────────────────────
    "sys_path":                     "sys_state_get",
    "sys_step":                     "sys_state_get",
    "sys_state_summary":            "sys_state_get",

    # ── routing aliases ────────────────────────────────────────────────────
    "sys_semantic_tool_search":     "tool_route",

    # ── search aliases ─────────────────────────────────────────────────────
    "tool_web_scrape":              "tool_search",
    "tool_literature_search_and_save": "tool_search",

    # ── plan / step aliases ────────────────────────────────────────────────
    "tool_step":                    "tool_plan",
    "tool_step_pipeline":           "tool_plan",
    "tool_plan_step_grounded":      "tool_plan",

    # ── audit sub-operation aliases ────────────────────────────────────────
    "tool_audit_figure_quality":    "tool_audit",
    "tool_audit_statistical_power": "tool_audit",

    # ── memory aliases ─────────────────────────────────────────────────────
    "mem_hypothesis_add":           "mem_hypothesis",
    "mem_hypothesis_list":          "mem_hypothesis",

    # ── workspace / log aliases ────────────────────────────────────────────
    "view_workspace_tree":          "sys_workspace_tree",
    "tool_log_decision":            "mem_log",
}

# Aliases that should fire deprecation telemetry when invoked. Every name
# here MUST resolve through _ALIASES to a real handler — preflight enforces.
_DEPRECATED_ALIASES: set[str] = {
    "sys_where",
    "sys_config",
    "sys_path",
    "sys_step",
    "sys_semantic_tool_search",
    "tool_web_scrape",
    "tool_literature_search_and_save",
    "tool_step",
    "tool_step_pipeline",
    "tool_plan_step_grounded",
    "mem_hypothesis_add",
    "mem_hypothesis_list",
    "tool_log_decision",
}



# Maps legacy alias → kwarg(s) to inject. Lets the consolidated handler
# infer operation/kind/source/mode/scope from the caller's name so an
# old-style call keeps working without the caller supplying the param.
#
# Two value shapes are accepted:
#   * (key, value) tuple — single-kwarg injection (most clusters).
#   * tuple of (key, value) tuples — multi-kwarg injection.
_ALIAS_PARAM_INJECTION: dict[str, Any] = {
    # boot cluster
    "sys_where":                    ("operation", "where"),
    "sys_config":                   ("operation", "config_get"),
    # state cluster
    "sys_path":                     ("operation", "list"),
    "sys_step":                     ("operation", "list"),
    # routing cluster
    "sys_semantic_tool_search":     ("mode", "tool_search"),
    # search cluster
    "tool_web_scrape":              ("mode", "scrape"),
    "tool_literature_search_and_save": ("mode", "literature"),
    # plan cluster
    "tool_step":                    ("operation", "iterate"),
    "tool_step_pipeline":           ("operation", "define"),
    "tool_plan_step_grounded":      ("operation", "grounded_step"),
    # memory cluster
    "mem_hypothesis_add":           ("operation", "add"),
    "mem_hypothesis_list":          ("operation", "list"),
    # log cluster
    "tool_log_decision":            ("kind", "decision"),
}


# Tools removed in earlier releases — friendly error pointing the AI at the new path.
# Old plans, scripts, or third-party callers that still name these get a
# clear message instead of a generic "unknown tool" dead end.
_REMOVED_TOOLS: dict[str, str] = {
    # ── reasoning / explanation (removed — AI does inline) ──────────────────
    "tool_explain": (
        "Removed — the model explains inline; no tool needed."
    ),
    "tool_deliverable_chooser": (
        "Removed — choose the deliverable in-prose per protocol."
    ),
    "tool_figure_palette": (
        "Removed — pick CVD-safe hex inline; no tool needed."
    ),

    # ── audit family (consolidated into tool_audit) ──────────────────────────
    "tool_citations_verify": (
        "Removed — use tool_audit."
    ),
    "tool_structure_audit": (
        "Removed — use tool_audit."
    ),
    "tool_judge_score": (
        "Removed — use tool_audit."
    ),
    "tool_audit_quality_full": (
        "Removed — use tool_audit."
    ),
    "tool_audit_findings": (
        "Removed — use tool_audit."
    ),
    "tool_rigor_signals_scan": (
        "Removed — use tool_audit."
    ),
    "tool_state_freshness_check": (
        "Removed — use tool_audit."
    ),
    "tool_intake_freshness": (
        "Removed — use tool_audit."
    ),
    "tool_resolve_gate_strictness": (
        "Removed — use tool_audit."
    ),
    "tool_project_tier_strictness": (
        "Removed — use tool_audit."
    ),
    "tool_self_certify": (
        "Removed — use tool_audit."
    ),
    "tool_list_certifications": (
        "Removed — use tool_audit."
    ),
    "tool_redteam_review": (
        "Removed — use tool_audit."
    ),
    "tool_null_findings_report": (
        "Removed — use tool_audit."
    ),
    "tool_discussion_coverage_audit": (
        "Removed — use tool_audit."
    ),
    "sys_file_validate_md": (
        "Removed — use tool_audit."
    ),

    # ── execution (consolidated) ─────────────────────────────────────────────
    "tool_r_exec": (
        "Removed — use tool_bash_exec or tool_python_exec."
    ),
    "tool_julia_exec": (
        "Removed — use tool_bash_exec or tool_python_exec."
    ),
    "tool_rmarkdown_render": (
        "Removed — use tool_bash_exec or tool_python_exec."
    ),
    "tool_latex_compile": (
        "Removed — use tool_typst_compile."
    ),

    # ── git / checkpoints ────────────────────────────────────────────────────
    "sys_checkpoint_create": (
        "Removed — use tool_git for checkpoints."
    ),
    "sys_checkpoint_list": (
        "Removed — use tool_git for checkpoints."
    ),
    "sys_checkpoint_rollback": (
        "Removed — use tool_git for checkpoints."
    ),

    # ── protocol navigation (consolidated) ───────────────────────────────────
    "sys_protocol_list": (
        "Removed — use sys_protocol_get / tool_protocols_list."
    ),
    "sys_protocol_history": (
        "Removed — use sys_protocol_get / tool_protocols_list."
    ),
    "sys_protocol_log": (
        "Removed — use sys_protocol_get / tool_protocols_list."
    ),
    "sys_protocol_next": (
        "Removed — use sys_protocol_get / tool_protocols_list."
    ),
    "sys_protocol_validate": (
        "Removed — use sys_protocol_get / tool_protocols_list."
    ),

    # ── tool discovery ───────────────────────────────────────────────────────
    "tool_tools_list": (
        "Removed — use sys_active_tools."
    ),
    "sys_help": (
        "Removed — use sys_active_tools / sys_boot."
    ),
    "sys_tool_describe": (
        "Removed — use sys_active_tools / sys_boot."
    ),

    # ── packs / adapters (archived) ──────────────────────────────────────────
    "sys_packs_installed": (
        "Removed — packs/adapters are archived; use core tools or self-pulled skills."
    ),
    "sys_adapters_installed": (
        "Removed — packs/adapters are archived; use core tools or self-pulled skills."
    ),
    "tool_adapter_extract": (
        "Removed — packs/adapters are archived; use core tools or self-pulled skills."
    ),
    "tool_adapters_list": (
        "Removed — packs/adapters are archived; use core tools or self-pulled skills."
    ),
    "tool_adapters_run_all": (
        "Removed — packs/adapters are archived; use core tools or self-pulled skills."
    ),

    # ── routing ──────────────────────────────────────────────────────────────
    "tool_quick_route": (
        "Removed — use tool_route."
    ),
    "tool_semantic_route": (
        "Removed — use tool_route(mode=tool_search)."
    ),

    # ── session handoff ───────────────────────────────────────────────────────
    "tool_session_resume": (
        "Removed — use tool_session_handoff."
    ),
    "sys_session_handoff": (
        "Removed — use tool_session_handoff."
    ),

    # ── SLURM (consolidated) ─────────────────────────────────────────────────
    "tool_slurm_status": (
        "Removed — use tool_slurm_submit or tool_bash_exec."
    ),
    "tool_slurm_list": (
        "Removed — use tool_slurm_submit or tool_bash_exec."
    ),
    "tool_slurm_fetch": (
        "Removed — use tool_slurm_submit or tool_bash_exec."
    ),

    # ── synthesis cluster ────────────────────────────────────────────────────
    "tool_synthesize_plan": (
        "Removed — use tool_synthesis_scaffold."
    ),
    "tool_synthesis_preview": (
        "Removed — use tool_synthesis_scaffold."
    ),
    "tool_synthesis_check": (
        "Removed — use tool_synthesis_scaffold."
    ),
    "tool_synthesis_curate_figures": (
        "Removed — use tool_synthesis_scaffold."
    ),
    "tool_writing_discussion_from_verdicts": (
        "Removed — use tool_reviewer."
    ),

    # ── plan / step cluster ──────────────────────────────────────────────────
    "tool_step_complete": (
        "Removed — use tool_plan."
    ),
    "tool_promote_to_step": (
        "Removed — use tool_plan."
    ),
    "tool_plan_step": (
        "Removed — use tool_plan."
    ),
    "tool_plan_next_step": (
        "Removed — use tool_plan."
    ),
    "tool_progress_digest": (
        "Removed — use tool_plan."
    ),
    "tool_branch_recommendation": (
        "Removed — use tool_plan."
    ),
    "tool_quick_review": (
        "Removed — use tool_plan."
    ),
    "tool_alternative_path_propose": (
        "Removed — use tool_plan."
    ),
    "tool_path_finalize": (
        "Removed — use tool_plan."
    ),

    # ── memory / intake cluster ──────────────────────────────────────────────
    "mem_citations_generate": (
        "Removed — use mem_log or the relevant protocol step."
    ),
    "mem_intake_regenerate": (
        "Removed — use mem_log or the relevant protocol step."
    ),
    "tool_context_intake": (
        "Removed — use mem_log or the relevant protocol step."
    ),
    "tool_intake_autofill": (
        "Removed — use mem_log or the relevant protocol step."
    ),

    # ── research / skills / literature ──────────────────────────────────────
    "tool_research_method": (
        "Removed — use tool_search or self-pulled skills."
    ),
    "tool_research_tool": (
        "Removed — use tool_search or self-pulled skills."
    ),
    "tool_external_tool_instructions": (
        "Removed — use tool_search or self-pulled skills."
    ),
    "tool_skills": (
        "Removed — use tool_search or self-pulled skills."
    ),
    "tool_literature_download": (
        "Removed — use tool_search(mode=literature)."
    ),
    "tool_step_literature_list": (
        "Removed — use tool_search(mode=literature)."
    ),

    # ── file operations ───────────────────────────────────────────────────────
    "sys_file_delete": (
        "Removed — delete via tool_bash_exec."
    ),

    # ── export / sharing ─────────────────────────────────────────────────────
    "sys_export_ro_crate": (
        "Removed — use tool_finalize_project."
    ),
    "sys_export_share_archive": (
        "Removed — use tool_finalize_project."
    ),

    # ── workspace / misc ─────────────────────────────────────────────────────
    "sys_consent": (
        "Removed — no longer needed; use the relevant core tool or protocol."
    ),
    "sys_daemon": (
        "Removed — no longer needed; use the relevant core tool or protocol."
    ),
    "sys_dep_inventory": (
        "Removed — no longer needed; use the relevant core tool or protocol."
    ),
    "tool_cache_clear": (
        "Removed — no longer needed; use the relevant core tool or protocol."
    ),
    "tool_deprecations_summary": (
        "Removed — no longer needed; use the relevant core tool or protocol."
    ),
    "tool_workspace_repair": (
        "Removed — no longer needed; use the relevant core tool or protocol."
    ),
    "sys_workspace_scaffold": (
        "Removed — no longer needed; use the relevant core tool or protocol."
    ),
    "tool_migrate_apply": (
        "Removed — no longer needed; use the relevant core tool or protocol."
    ),

    # ── first-wave consolidation aliases hard-removed ────────────────────────
    # Search cluster (5 → 1).
    "tool_search_semantic_scholar": (
        "tool_search_semantic_scholar: renamed to tool_search in v1.6.1, removed in v2.0.0; "
        "call tool_search(query='...', source='semantic_scholar') instead."
    ),
    "tool_search_pubmed": (
        "tool_search_pubmed: renamed to tool_search in v1.6.1, removed in v2.0.0; "
        "call tool_search(query='...', source='pubmed') instead."
    ),
    "tool_search_crossref": (
        "tool_search_crossref: renamed to tool_search in v1.6.1, removed in v2.0.0; "
        "call tool_search(query='...', source='crossref') instead."
    ),
    "tool_search_arxiv": (
        "tool_search_arxiv: renamed to tool_search in v1.6.1, removed in v2.0.0; "
        "call tool_search(query='...', source='arxiv') instead."
    ),
    "tool_search_web": (
        "tool_search_web: renamed to tool_search in v1.6.1, removed in v2.0.0; "
        "call tool_search(query='...', source='web') instead."
    ),
    # Plan cluster (3 → 1).
    "tool_plan_turn": (
        "tool_plan_turn: renamed to tool_plan in v1.6.1, removed in v2.0.0; "
        "call tool_plan(operation='turn') instead."
    ),
    "tool_plan_advance": (
        "tool_plan_advance: renamed to tool_plan in v1.6.1, removed in v2.0.0; "
        "call tool_plan(operation='advance') instead."
    ),
    "tool_plan_clear": (
        "tool_plan_clear: renamed to tool_plan in v1.6.1, removed in v2.0.0; "
        "call tool_plan(operation='clear') instead."
    ),
    # Grounding cluster (4 → 2).
    "tool_grounding_register": (
        "tool_grounding_register: renamed to tool_ground in v1.6.1, removed in v2.0.0; "
        "call tool_ground(mode='explicit', ...) instead."
    ),
    "tool_ground_from_context": (
        "tool_ground_from_context: renamed to tool_ground in v1.6.1, removed in v2.0.0; "
        "call tool_ground(mode='from_context', ...) instead."
    ),
    "tool_claim_verify": (
        "tool_claim_verify: renamed to tool_verify in v1.6.1, removed in v2.0.0; "
        "call tool_verify(scope='claim', ...) instead."
    ),
    "tool_grounding_verify": (
        "tool_grounding_verify: renamed to tool_verify in v1.6.1, removed in v2.0.0; "
        "call tool_verify(scope='project', ...) instead."
    ),
    # Lessons cluster (record/consult slice).
    "tool_lessons_record": (
        "tool_lessons_record: renamed to tool_lessons in v1.6.1, removed in v2.0.0; "
        "call tool_lessons(operation='record', ...) instead."
    ),
    "tool_lessons_consult": (
        "tool_lessons_consult: renamed to tool_lessons in v1.6.1, removed in v2.0.0; "
        "call tool_lessons(operation='consult', ...) instead."
    ),
    # Path cluster (3 → 1).
    "sys_path_create": (
        "sys_path_create: renamed to sys_path in v1.6.1, removed in v2.0.0; "
        "call sys_path(operation='create', ...) instead."
    ),
    "sys_path_abandon": (
        "sys_path_abandon: renamed to sys_path in v1.6.1, removed in v2.0.0; "
        "call sys_path(operation='abandon', ...) instead."
    ),
    "sys_path_list": (
        "sys_path_list: renamed to sys_path in v1.6.1, removed in v2.0.0; "
        "call sys_path(operation='list') instead."
    ),
    # Memory cluster (4 → 1).
    "mem_methods_append": (
        "mem_methods_append: renamed to mem_log in v1.6.1, removed in v2.0.0; "
        "call mem_log(kind='methods', method='...') instead."
    ),
    "mem_decision_log": (
        "mem_decision_log: renamed to mem_log in v1.6.1, removed in v2.0.0; "
        "call mem_log(kind='decision', context='...', selected='...', rationale='...') instead."
    ),
    "mem_hypothesis_update": (
        "mem_hypothesis_update: renamed to mem_log in v1.6.1, removed in v2.0.0; "
        "call mem_log(kind='hypothesis', hypothesis_id='...', status='...') instead."
    ),
    "mem_analysis_log": (
        "mem_analysis_log: renamed to mem_log in v1.6.1, removed in v2.0.0; "
        "call mem_log(kind='analysis', entry='...') instead."
    ),
    # ── v2.3.0 removals: synthesis generators replaced by AI-direct authoring ──
    "tool_figure_create": (
        "tool_figure_create was removed. Research-OS no longer ships "
        "premade chart code — write your own matplotlib / ggplot2 / Altair / "
        "plotnine / Vega-Lite / d3 script tailored to the data. Load the "
        "guidance with sys_protocol_get(protocol_name='visualization/figure_guidelines', "
        "format='summary'); call tool_search first if you're unsure which plotting "
        "library is canonical for this data type. "
        "tool_audit(scope='step', dimension='figure_full') is unchanged."
    ),
    "tool_synthesize": (
        "tool_synthesize was removed in v2.3.0. Auto-generated papers were "
        "low quality. Author synthesis/paper.typ directly, section by "
        "section, following synthesis/synthesis_paper (sys_protocol_get "
        "protocol_name='synthesis/synthesis_paper'). Use "
        "tool_synthesis_scaffold(kind='paper') for a skeleton, "
        "tool_typst_compile to validate + render."
    ),
    "tool_dashboard": (
        "tool_dashboard was removed in v2.3.0. Author synthesis/dashboard.html "
        "directly (single-file, offline, accessible) following "
        "synthesis/synthesis_dashboard. Use tool_synthesis_scaffold(kind="
        "'dashboard') for a starter."
    ),
    "tool_dashboard_create": (
        "tool_dashboard_create was removed in v2.3.0. Author "
        "synthesis/dashboard.html directly (single-file, offline, "
        "accessible) following synthesis/synthesis_dashboard."
    ),
    "tool_dashboard_story_generate": (
        "tool_dashboard_story_generate was removed in v2.3.0. Story-mode "
        "dashboards are authored directly inside synthesis/dashboard.html "
        "as a narrative-led layout. See synthesis/synthesis_dashboard for "
        "design guidance."
    ),
    "tool_dashboard_story_edit": (
        "tool_dashboard_story_edit was removed in v2.3.0. Edit "
        "synthesis/dashboard.html directly with the Edit tool."
    ),
    "tool_dashboard_story_quality_bar": (
        "tool_dashboard_story_quality_bar was removed in v2.3.0. Use "
        "tool_synthesis_scaffold to audit engineering invariants."
    ),
    "tool_dashboard_reviewer_sim": (
        "tool_dashboard_reviewer_sim was removed in v2.3.0. Skim the "
        "dashboard yourself or have an external reviewer do it."
    ),
    "tool_dashboard_test_generate": (
        "tool_dashboard_test_generate was removed in v2.3.0. For AI-authored "
        "dashboards, write targeted tests by hand if needed."
    ),
    "tool_dashboard_test_run": (
        "tool_dashboard_test_run was removed in v2.3.0. Run Playwright "
        "or any browser test runner directly."
    ),
    "tool_slides_create": (
        "tool_slides_create was removed in v2.3.0. Author synthesis/slides.typ "
        "(Touying) directly following synthesis/synthesis_slides. Use "
        "tool_synthesis_scaffold(kind='slides') for a skeleton, then "
        "tool_typst_compile to validate + render."
    ),
    "tool_poster_create": (
        "tool_poster_create was removed in v2.3.0. Author synthesis/poster.typ "
        "directly following synthesis/synthesis_poster. Use "
        "tool_synthesis_scaffold(kind='poster') for a skeleton, then "
        "tool_typst_compile to validate + render."
    ),
    "tool_humanities_essay_scaffold": (
        "tool_humanities_essay_scaffold was removed in v2.3.0. Author "
        "synthesis/essay.typ directly following "
        "synthesis/humanities_essay_structure. Use "
        "tool_synthesis_scaffold(kind='essay') for a skeleton."
    ),
    "tool_paper_compile_typst": (
        "tool_paper_compile_typst was removed in v2.3.0. Compile via "
        "tool_typst_compile (no markdown step)."
    ),
    "tool_section_substantiveness": (
        "tool_section_substantiveness was folded into tool_synthesis_scaffold "
        "in v2.3.0. Use tool_synthesis_scaffold with mode='substantiveness' instead."
    ),
    "tool_figure": (
        "tool_figure was removed in v2.3.0. The caption_synthesise, "
        "interactive_autogen, and paper_autoembed operations were dropped: "
        "the AI authors plain-English figure summaries and Typst #figure(...) "
        "blocks directly when writing the plotting script or paper.typ."
    ),
    "tool_figure_caption_synthesise": (
        "tool_figure_caption_synthesise was removed in v2.3.0. Author "
        "the <stem>.summary.md plain-English sidecar directly when the "
        "figure is created — see visualization/figure_guidelines."
    ),
    "tool_figure_interactive_autogen": (
        "tool_figure_interactive_autogen was removed in v2.3.0. If a "
        "figure benefits from interactivity, the plotting script should emit "
        "a Vega-Lite or vis-network HTML companion next to the PNG."
    ),
    "tool_paper_figures_autoembed": (
        "tool_paper_figures_autoembed was removed in v2.3.0. The AI now "
        "embeds figures directly when authoring paper.typ via "
        "`#figure(image(\"figures/figXX.png\"), caption: [...]) <fig:slug>`."
    ),
    "tool_reviewer_simulate": (
        "tool_reviewer_simulate was removed in v2.3.0. To pre-review your "
        "paper, ask the AI to walk through it with the personas listed in "
        "synthesis/reviewer_response — direct reasoning beats canned "
        "questionnaires."
    ),
    "tool_poster_create_latex": (
        "tool_poster_create_latex was never a real tool name. The legacy "
        "tikzposter LaTeX poster path was removed in v2.0.0. Call "
        "tool_synthesis_scaffold(kind='poster') — Typst is the only supported renderer."
    ),
    "tool_poster_compile_latex": (
        "tool_poster_compile_latex was never a real tool name. The legacy "
        "tikzposter LaTeX poster path was removed in v2.0.0. "
        "Call tool_synthesis_scaffold(kind='poster') — Typst is the only supported renderer."
    ),
    # ── lessons + failure + reliability cluster ──────────────────────────────
    # (These were deprecated aliases in the old file but their targets
    # tool_lessons and tool_reliability are live tools — they remain
    # callable directly. The sub-operation aliases below are removed so
    # the AI uses the canonical tool with the operation param.)
    "tool_failure_record": (
        "Removed — use tool_lessons(operation='failure_record') instead."
    ),
    "tool_failure_check": (
        "Removed — use tool_lessons(operation='failure_check') instead."
    ),
    "tool_failure_list": (
        "Removed — use tool_lessons(operation='failure_list') instead."
    ),
    "tool_dead_end_lessons": (
        "Removed — use tool_lessons(operation='dead_end') instead."
    ),
    "tool_mistake_replay": (
        "Removed — use tool_lessons(operation='mistake_replay') instead."
    ),
    "tool_reliability_log_event": (
        "Removed — use tool_reliability(operation='log_event') instead."
    ),
    "tool_reliability_report": (
        "Removed — use tool_reliability(operation='report') instead."
    ),
    # ── audit cluster sub-operations (moved to _REMOVED_TOOLS) ──────────────
    "tool_audit_assumptions": (
        "Removed — use tool_audit with scope='step', dimension='assumptions'."
    ),
    "tool_audit_code_quality": (
        "Removed — use tool_audit with scope='step', dimension='code_quality'."
    ),
    "tool_audit_evalue": (
        "Removed — use tool_audit with scope='step', dimension='evalue'."
    ),
    "tool_audit_figure": (
        "Removed — use tool_audit with scope='step', dimension='figure'."
    ),
    "tool_audit_figure_full": (
        "Removed — use tool_audit with scope='step', dimension='figure_full'."
    ),
    "tool_audit_figure_interactivity": (
        "Removed — use tool_audit with scope='step', dimension='figure_interactivity'."
    ),
    "tool_audit_power": (
        "Removed — use tool_audit with scope='step', dimension='power'."
    ),
    "tool_audit_reproducibility": (
        "Removed — use tool_audit with scope='step', dimension='reproducibility'."
    ),
    "tool_audit_step_completeness": (
        "Removed — use tool_audit with scope='step', dimension='completeness'."
    ),
    "tool_audit_step_literature": (
        "Removed — use tool_audit with scope='step', dimension='literature'."
    ),
    "tool_audit_citations": (
        "Removed — use tool_audit with scope='project', dimension='citations'."
    ),
    "tool_audit_claims": (
        "Removed — use tool_audit with scope='project', dimension='claims'."
    ),
    "tool_audit_cliches": (
        "Removed — use tool_audit with scope='project', dimension='cliches'."
    ),
    "tool_audit_coherence": (
        "Removed — use tool_audit with scope='project', dimension='coherence'."
    ),
    "tool_audit_cross_deliverable_consistency": (
        "Removed — use tool_audit with scope='project', dimension='cross_deliverable'."
    ),
    "tool_audit_prose": (
        "Removed — use tool_audit with scope='project', dimension='prose'."
    ),
    "tool_audit_version_coherence": (
        "Removed — use tool_audit with scope='project', dimension='version_coherence'."
    ),
    "tool_audit_synthesis": (
        "Removed — use tool_audit with scope='synthesis', dimension='all'."
    ),
    "tool_audit_dashboard_content": (
        "Removed — use tool_audit with scope='synthesis', dimension='dashboard_content'."
    ),
    "tool_audit_figure_coverage": (
        "Removed — use tool_audit with scope='synthesis', dimension='figure_coverage'."
    ),
    "tool_audit_reviewer_responses": (
        "Removed — use tool_audit with scope='synthesis', dimension='reviewer_responses'."
    ),
    "tool_audit_findings_query": (
        "Removed — use tool_audit with scope/dimension."
    ),
    "tool_audit_findings_diff": (
        "Removed — use tool_audit with scope/dimension."
    ),
    # tool_audit_figure_quality and tool_audit_statistical_power are live
    # aliases in _ALIASES (→ tool_audit); they are NOT removed tools.
    # ── step sub-operations (moved to _REMOVED_TOOLS) ────────────────────────
    "tool_step_iterate": (
        "Removed — use tool_plan(operation='iterate')."
    ),
    "tool_step_iterations_list": (
        "Removed — use tool_plan(operation='iterations_list')."
    ),
    "tool_step_revision_options": (
        "Removed — use tool_plan(operation='revision_options')."
    ),
    "tool_step_env_lock": (
        "Removed — use tool_plan(operation='env_lock')."
    ),
    "tool_step_pipeline_define": (
        "Removed — use tool_plan(operation='define')."
    ),
    "tool_step_pipeline_run": (
        "Removed — use tool_plan(operation='run')."
    ),
    "tool_step_pipeline_status": (
        "Removed — use tool_plan(operation='status')."
    ),
    "tool_step_pipeline_diagram": (
        "Removed — use tool_plan(operation='diagram')."
    ),
    # ── sensitivity / preregister / reviewer / data / thought / scratch / task
    # sub-operations (were deprecated aliases; targets still live, but the
    # sub-operation aliases themselves are removed to keep _ALIASES lean) ────
    "tool_sensitivity_define": (
        "Removed — use tool_sensitivity(operation='define')."
    ),
    "tool_sensitivity_run": (
        "Removed — use tool_sensitivity(operation='run')."
    ),
    "tool_preregister_freeze": (
        "Removed — use tool_preregister(operation='freeze')."
    ),
    "tool_preregister_diff": (
        "Removed — use tool_preregister(operation='diff')."
    ),
    "tool_response_to_reviewers": (
        "Removed — use tool_reviewer(operation='response')."
    ),
    "tool_rebuttal_draft": (
        "Removed — use tool_reviewer(operation='rebuttal')."
    ),
    "tool_reviewer_response_compile": (
        "Removed — use tool_reviewer(operation='compile')."
    ),
    "tool_data_sample": (
        "Removed — use tool_data(operation='sample')."
    ),
    "tool_data_profile": (
        "Removed — use tool_data(operation='profile')."
    ),
    "tool_data_convert": (
        "Removed — use tool_data(operation='convert')."
    ),
    "tool_thought_log": (
        "Removed — use tool_thought(operation='log')."
    ),
    "tool_thought_trace": (
        "Removed — use tool_thought(operation='trace')."
    ),
    "tool_scratch_write": (
        "Removed — use tool_scratch(operation='write')."
    ),
    "tool_scratch_run": (
        "Removed — use tool_scratch(operation='run')."
    ),
    "tool_scratch_list": (
        "Removed — use tool_scratch(operation='list')."
    ),
    "tool_scratch_clear": (
        "Removed — use tool_scratch(operation='clear')."
    ),
    "tool_task_run": (
        "Removed — use tool_task(operation='run')."
    ),
    "tool_task_status": (
        "Removed — use tool_task(operation='status')."
    ),
    "tool_task_list": (
        "Removed — use tool_task(operation='list')."
    ),
    "tool_task_kill": (
        "Removed — use tool_task(operation='kill')."
    ),
    "sys_config_get": (
        "Removed — use sys_boot(operation='config_get')."
    ),
    "sys_config_set": (
        "Removed — use sys_boot for config; set config values via the relevant protocol."
    ),
    "sys_config_validate": (
        "Removed — use sys_boot for config; validate via the relevant protocol."
    ),
    "sys_env_snapshot": (
        "Removed — use sys_env(operation='snapshot')."
    ),
    "sys_env_docker_generate": (
        "Removed — use sys_env(operation='docker_generate')."
    ),
}
