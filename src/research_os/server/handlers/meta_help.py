"""Handler — sys_help.

Carved out of handlers/meta_sys.py because the inline help text alone
runs ~350 lines; isolating it keeps meta_sys under the 600-line ceiling.
"""
from __future__ import annotations

# ruff: noqa: F403, F405  # legacy handler runtime star-import compatibility
from .._handlers_runtime import *  # noqa: F401,F403


__all__ = ["_handle_sys_help"]


def _handle_sys_help(name, arguments, root):
    """Compact AI orientation block — how to use Research OS efficiently."""
    topic = (arguments or {}).get("topic", "").strip().lower()

    # Lean default: orientation only the AI needs on EVERY call lives
    # here; deep cuts (protocol categories, anti-patterns, docs index)
    # are one `topic=` request away when the AI actually needs them.
    core = {
        "namespaces": {
            "sys_*":  "workspace / state / files / paths / checkpoints",
            "tool_*": "research work (search / exec / audit / synthesis / plan)",
            "mem_*":  "append-only memory (methods / decisions / hypotheses / citations)",
        },
        "session_start": (
            "Every turn starts with a researcher message. On the FIRST "
            "turn of the session, sys_boot is your 1st MCP call and "
            "tool_route(prompt=their message) is your 2nd — fire them "
            "back-to-back. Then: tool_plan(operation='turn') if "
            "complexity=high; else shortcut_tool. On subsequent turns, "
            "skip sys_boot and go straight to tool_route."
        ),
        "when_uncertain": (
            "If tool_route returns ask_user, ask THAT question and re-route. "
            "Never guess. If nothing matches (resolved_level=0), follow the "
            "fallback's L1 menu prompt instead of loading a random protocol."
        ),
        "topics": [
            "synthesis", "methodology", "visualization", "audit",
            "literature", "writing", "routing", "iteration", "overrides",
            "recovery", "fields", "packs", "adapters", "depth", "categories",
            "anti_patterns", "docs", "gates", "modes",
        ],
        "hint": "Call sys_help again with topic=<one of topics> for detail.",
    }
    if topic in {"categories", "protocols"}:
        return _text(_success({"protocol_categories": {
            "guidance": "session/flow (boot/resume/handoff/autopilot/casual/mid_entry/disagree/revise)",
            "discover": "intake + question lock-in + mid-pipeline entry",
            "domain": "domain classification + study design",
            "methodology": "method picking + per-method protocols",
            "literature": "search + systematic review + GRADE + comparative review",
            "writing": "per-section drafting (methods/results/discussion/limitations/end-matter)",
            "visualization": "figures (rules/workflow/critique/multi-panel/arc/a11y)",
            "synthesis": "final deliverables (paper/poster/dashboard/slides/...)",
            "audit": "quality audit + pre-submission checklist + provenance completeness",
            "reproducibility": "snapshot + verify reruns",
        }}))
    if topic == "anti_patterns":
        return _text(_success({"anti_patterns": [
            "Don't call sys_state_get + sys_config_get + sys_protocol_history separately — sys_boot bundles them.",
            "Don't load full protocols when summary suffices (~300 tok vs 1.5-3K).",
            "Don't one-shot 400-line scripts — tool_step_pipeline_define + atomic sub-tasks.",
            "Don't invent citations — synthesis tools VERIFY every citation against Crossref/S2/PubMed/arXiv.",
            "Don't pick a method or library from training memory — tool_research_method / tool_research_tool first.",
            "Treat inputs/raw_data + inputs/literature as source-of-truth: editing needs force=true + researcher OK (soft guard). inputs/context is a free drop-zone — write there freely.",
            "Don't skip the ask_user from tool_route — asking once costs less than picking wrong.",
            "Don't re-route after the researcher already picked one — use tool_plan(operation='clear') if they pivoted.",
            "Don't bypass a quality gate without override_rationale — the pre-submission audit will surface every silent bypass.",
            "Don't reuse a stale _v<n> filename — bump or call tool_step_iterate before editing scripts.",
            "Don't submit without audit/pre_submission_checklist — it catches what reviewers will catch.",
            "Don't push back on every choice — load guidance/constructive_disagreement only when evidence is unambiguous and the choice affects claims.",
        ]}))
    if topic == "routing":
        return _text(_success({
            "decision_tree": [
                "0. Every turn is triggered by a researcher message — you don't act before one arrives.",
                "1. First turn of the session: sys_boot is your 1st MCP call. Returns pause + active_plan + next_protocol.",
                "2. active_plan in progress (from a previous turn) → tool_plan(operation='turn') → walk it.",
                "3. pause_classification = ctx_exhaustion / mid_step → guidance/session_resume.",
                "4. Otherwise: tool_route(prompt=their verbatim message) is your 2nd MCP call.",
                "5. resolved_level=3 + complexity=low → call shortcut_tool OR load protocol summary.",
                "6. resolved_level=3 + complexity=high → tool_plan(operation='turn') then operation='advance' per step.",
                "7. resolved_level<3 OR ask_user non-null → ASK the question, re-route.",
                "8. resolved_level=0 → use the fallback ask_user; never guess a protocol.",
                "9. Subsequent turns: skip sys_boot — its payload is still in context — go straight to tool_route or continue the active plan.",
            ],
            "ambiguity_handling": (
                "L1 ties → ask which work-type. L2 ties → ask which sub-intent within the class. "
                "L3 ties (top two within 2 points) → ask which protocol. ALL three asks are "
                "one-sentence — cheaper than loading the wrong YAML."
            ),
            "complexity_signals": [
                ">18 words OR multiple verbs OR conjunctions ('and then', 'also', 'plus')",
                "deliverable phrases: 'full project', 'end to end', 'from scratch', 'wake me when', 'ship it'",
                "→ persisted active_plan; walk via tool_plan(operation='turn') + tool_plan(operation='advance')",
            ],
            "after_routing": "sys_active_tools(protocol_name) → ~10-15 tool shortlist for that protocol.",
        }))
    if topic == "iteration":
        return _text(_success({
            "modes": {
                "bug_fix": (
                    "Script has a defect. Bump _v<n>, re-run via tool_step_pipeline_run. "
                    "Content-hash cache invalidates affected nodes automatically. "
                    "No tool_step_iterate call needed — the live filename history (v1→v2→v3) is the audit trail."
                ),
                "deliberate_iteration": (
                    "Coordinated change (recolour Fig 2, tighten cutoff, swap model spec). "
                    "FIRST call tool_step_iterate(step_id, rationale=…) — snapshots scripts + "
                    "outputs + caption / summary / prov sidecars + conclusion into .versions/v<n>/. "
                    "Live filenames stay stable so cross-step references in conclusions / "
                    "dashboards don't rot. Then rename via the returned next_script_paths and re-run."
                ),
            },
            "after_either": (
                "Run tool_audit_version_coherence to confirm every output traces to the "
                "highest-version script on disk. Drift (a v2 figure produced by a v1 script) "
                "lands in workspace/logs/version_coherence.md."
            ),
            "common_mistake": (
                "Editing scripts in place without bumping _v<n>. The previous output's .prov.json "
                "still points at the old script name — content-hash invalidation works but the "
                "audit trail loses the iteration's history."
            ),
        }))
    if topic == "overrides":
        return _text(_success({
            "policy_levels": {
                "enforce": "ACTIVE default — AI refuses to bypass without an explicit current-message ask + logged rationale.",
                "allow_override": "RESERVED (not yet enforced) — behaves like enforce today; per-tool override_* flags already work regardless.",
                "warn_only": "RESERVED (not yet enforced) — blockers still hard-block today; do not rely on it to soften gates.",
            },
            # Canonical list of every quality-gate bypass flag, the tool it
            # belongs to, and what it bypasses. (Floor/autopilot gates differ.)
            "how_to_bypass": [
                "tool_discussion_coverage_audit(override_discussion_coverage=true, override_rationale='<why>') — non-AGREES verdict missing from Discussion",
                "tool_step_complete(override_literature_gate=true, override_rationale='<why>') — per-step literature-loop check (same flag on tool_path_finalize)",
                "tool_audit(scope='synthesis', dimension='all', override_no_pdfs=true, override_rationale='<why>') — zero-PDF default-deny on literature-required steps",
                "tool_audit(scope='synthesis', dimension='dashboard_content', override_dashboard_content_gate=true, override_rationale='<why>') — dashboard-content BLOCKERs",
                "tool_audit(scope='project', dimension='cross_deliverable', override_cross_deliverable=true, override_rationale='<why>') — 5-dimension cross-deliverable audit",
                "tool_plan(operation='advance', override_gate=true, override_rationale='<why>') — deliverable-step quality gate (also bypasses the master completeness aggregator)",
                "tool_finalize_project(operation='finalize', override=true, override_rationale='<why>') — the ship gate; the ONLY soften path (it ignores quality_gate_policy)",
            ],
            "rules": [
                "Authorisation must be in the researcher's CURRENT message ('skip the audit', 'just draft it', 'preview only').",
                "override_rationale is mandatory — silent bypass is a hard rule violation.",
                "Each bypass appends to workspace/logs/override_log.md.",
                "audit/pre_submission_checklist surfaces every unresolved bypass; RED if unresolved + no rationale.",
                "Hard rules (no fabricated citations; .os_state is never hand-edited) are absolute. Editing original inputs (raw_data/literature) is a soft guard: force=true + researcher OK + log staleness.",
            ],
        }))
    if topic == "recovery":
        return _text(_success({
            "stuck_paths": {
                "broken_workspace": "tool_workspace_repair — heals manifest + state-ledger drift, lazy-dir leftovers.",
                "dead_end_in_step": "sys_path(operation='abandon') + tool_lessons(operation='dead_end') + tool_plan_next_step.",
                "context_full": "sys_session_handoff + 'pick up where we left off' in fresh chat → guidance/session_resume.",
                "lost_active_project": "sys_active_project — returns resolved root + how resolved.",
                "lost_protocol": "sys_protocol_next (pipeline) or sys_protocol_list (browse).",
                "mid_plan_pivot": "tool_plan(operation='clear') — discard plan; re-tool_route on the new ask.",
            },
            "checkpoint_safety": (
                "sys_checkpoint_create BEFORE risky moves; sys_checkpoint_rollback restores. "
                "Copied snapshot. Always rollback to a checkpoint instead of `git reset --hard`."
            ),
            "missing_dependencies": (
                "sys_dep_inventory reports what failed to import. Tools that need the missing dep raise "
                "RuntimeError with 'pip install research-os[all]' instructions."
            ),
        }))
    if topic in {"packs", "adapters", "domains"}:
        packs: list[dict] = []
        adapters: list[dict] = []
        try:
            from research_os.plugins import installed_packs
            packs = [
                {"name": p["name"], "summary": p.get("description", ""),
                 "tools": p.get("tool_count", 0)}
                for p in (installed_packs() or [])
            ]
        except Exception:
            pass
        try:
            from research_os.adapters import installed_adapters
            adapters = [
                {"name": a["name"], "summary": a.get("description", "")}
                for a in (installed_adapters() or [])
            ]
        except Exception:
            pass
        return _text(_success({
            "what_packs_are": (
                "Domain PACKS add field-specific tools + protocols on top of the "
                "field-agnostic core. They're bundled with the wheel + always "
                "loaded — no install needed (the pyproject extras are reserved "
                "no-ops). sys_boot.field_signals nudges you to the relevant pack "
                "from your inputs; routing a domain-specific prompt makes "
                "tool_route pick the pack protocol."
            ),
            "domain_packs": packs,
            "what_adapters_are": (
                "Infrastructure ADAPTERS auto-extract provenance from the tools a "
                "project uses AROUND its code (HPC schedulers, workflow engines, "
                "data platforms). They detect from the filesystem (no network at "
                "detect/extract); tool_adapters_list shows which fired; "
                "tool_adapters_run_all writes provenance YAMLs. Each degrades "
                "gracefully when its optional system dep is absent."
            ),
            "infra_adapters": adapters,
            "no_pack_for_my_field": (
                "Most fields need NO pack — the core is field-agnostic and already "
                "covers clinical / survey / survival / meta-analysis / causal "
                "inference / timeseries / ablation / simulation (see "
                "sys_help(topic='fields')). For an unfamiliar field at any depth, "
                "methodology/deep_domain_research surveys the field's canonical "
                "pipeline from the literature; guidance/scope_clarification scopes "
                "a vague ask. Method choices come from tool_research_method, never "
                "training memory."
            ),
            "diagnostics": [
                "sys_packs_installed — domain packs loaded + versions",
                "sys_adapters_installed — infra adapters loaded",
                "tool_adapters_list — which adapters this project triggers",
            ],
        }))
    if topic == "fields":
        return _text(_success({
            "principle": (
                "Research OS is FIELD-AGNOSTIC by design. Protocols name questions and "
                "grounding sources, not domain-specific methods. Every method choice "
                "comes from the literature via tool_research_method — never from training memory."
            ),
            "domain_packs": (
                "5 optional domain PACKS add field-specific TOOLS for non-standard "
                "deliverables (wet_lab, humanities, qualitative, theory_math, "
                "engineering); 8 infra ADAPTERS auto-extract provenance "
                "(slurm/snakemake/nextflow/cytoscape/redcap/synapse/mlflow/zenodo). "
                "For the full list + how to use them: sys_help(topic='packs')."
            ),
            "subfield_pipelines": (
                "For multi-stage canonical pipelines (snRNA-seq, metagenomics, protein "
                "embeddings, fMRI, MD), load methodology/deep_domain_research FIRST. It "
                "identifies the subfield from real signals (file names, columns, context), "
                "surveys ≥3 cited sources, proposes a stage × tool × runtime skeleton, "
                "and writes an assumption matrix per stage."
            ),
            "domain_specific_protocols": [
                "clinical_trials (CONSORT)",
                "qualitative_research (COREQ/SRQR)",
                "qualitative_quality_audit (saturation + intercoder + reflexivity)",
                "survey_psychometrics (EFA/CFA/IRT)",
                "cox_ph_diagnostics (survival)",
                "meta_analysis (random/fixed effects)",
                "bayesian_analysis (priors → posterior → checks)",
                "timeseries_analysis (forecasting / state-space)",
                "causal_inference_deep (DAG / IV / DiD / RDD)",
                "ablation_study (component-by-component)",
                "simulation_studies (ADEMP Monte Carlo)",
                "mixed_methods (concurrent / sequential)",
            ],
            "cross_disciplinary": (
                "When signals point to two subfields, deep_domain_research recommends running it "
                "once per subfield. Methodology decisions per stage cite the SUBFIELD's literature, "
                "not a generic table."
            ),
            "reporting_standards": (
                "domain_analysis classifies the field and picks the canonical reporting standard "
                "(CONSORT / PRISMA / STROBE / ARRIVE / TRIPOD-AI / SRQR / COREQ / SAGER / etc.). "
                "pre_submission_checklist verifies the right completed form is on file."
            ),
        }))
    if topic == "depth":
        return _text(_success({
            "depth_gradient": [
                "5-minute napkin     → guidance/casual_exploration",
                "30-minute appraisal → guidance/quick_paper_review",
                "Real EDA            → methodology/exploratory_data_analysis",
                "Per-step pipeline   → guidance/analysis_plan",
                "Method head-to-head → methodology/method_comparison",
                "Subfield-canonical  → methodology/deep_domain_research",
                "Systematic synthesis → literature/systematic_review",
                "Publication-grade   → synthesis/synthesis_paper",
            ],
            "expertise_levels": {
                "beginner":     "AI explains more; more confirmation gates; offers method consultation freely.",
                "intermediate": "default — concise; asks only on real ambiguity.",
                "advanced":     "fewer reminders; expects literature-grounded justifications without prompting.",
                "pi":           "AI defers to declared direction unless evidence contradicts (constructive_disagreement).",
            },
            "model_profile_effect": (
                "small  → 1 step/turn, terser protocols, lighter tool descriptions; "
                "medium → 3 steps/turn (default); "
                "large  → 6 steps/turn, full protocol detail, multi-step planning."
            ),
        }))
    if topic in {"literature"}:
        return _text(_success({
            "literature_protocols": {
                "literature_search": "multi-database search + dedup + PRISMA accounting + forward-citation walk + predatory-venue flag.",
                "systematic_review": "full PRISMA workflow.",
                "evidence_synthesis": "GRADE-style grading + contradiction detection.",
                "comparative_paper_review": "compare-and-contrast 2-N papers (journal club / related work / foundational).",
            },
            "search_tools": [
                "tool_search(query=..., source='semantic_scholar')",
                "tool_search(query=..., source='pubmed')",
                "tool_search(query=..., source='crossref')",
                "tool_search(query=..., source='arxiv')",
                "tool_search(query=..., source='web')",
                "tool_literature_search_and_save  (combined search + download)",
            ],
            "after_search": "mem_citations_generate → workspace/citations.md. tool_citations_verify → online resolve every cite.",
        }))
    if topic in {"writing"}:
        return _text(_success({
            "writing_protocols": {
                "writing_core": "universal rules — voice, tense, banned phrases, vague quantifiers, anti-bullshit signals, numbered claim grounding.",
                "writing_methods": "Methods section + workspace/methods.md format.",
                "writing_results": "Results — report numbers; defer interpretation; full statistical form.",
                "writing_discussion": "Discussion — principal findings, alternative explanations, scope-limited implications.",
                "writing_limitations": "Limitations — no boilerplate; each limitation paired with downstream implication.",
                "writing_conclusions": "Per-step conclusions.md format.",
                "writing_citations": "workspace/citations.md maintenance.",
                "writing_readme": "Project + per-step READMEs.",
                "writing_analysis_log": "Structured entries in workspace/analysis.md.",
                "writing_data_availability": "End matter — data / code / CRediT / funding / COI / acknowledgements.",
            },
            "audits_attached": [
                "tool_audit_prose (hedging / vague / passive / causal-language)",
                "tool_audit_claims (every number traces to an artefact or verified citation)",
            ],
        }))
    if topic == "docs":
        return _text(_success({"docs_for_humans": [
            "docs/START.md            — install + first project + cheatsheet",
            "docs/RESEARCHER_GUIDE.md — full workflow walkthrough",
            "docs/USE_CASES.md        — role × goal × output map",
            "docs/SETUP.md            — per-IDE wiring",
            "docs/PROTOCOLS.md        — every protocol + triggers + quality bars",
            "docs/TOOLS.md            — every MCP tool with example calls",
            "docs/AI_GUIDE.md         — operating manual for the AI",
            "docs/PROTOCOL_DOCTRINE.md — scaffold-not-script principle",
            "docs/FAQ.md              — common questions",
            "docs/SHARING.md          — share-safe zip + GitHub paths",
        ]}))

    if topic in {"synthesis", "deliverable", "deliverables"}:
        return _text(_success({
            "synthesis_protocols": {
                "synthesis_paper": "IMRAD paper, venue-tailored",
                "synthesis_abstract": "structured / unstructured / preprint",
                "synthesis_poster": "billboard / classic LaTeX poster + QR",
                "synthesis_dashboard": "offline HTML dashboard, Playwright-tested",
                "synthesis_slides": "talks (lab / conference / defense / invited / teaching)",
                "synthesis_grant": "grant narrative (R01 / NSF / Wellcome / ERC)",
                "synthesis_report": "internal / client / technical / policy report",
                "synthesis_lay_summary": "public / press / patient / funder / blog / social",
                "synthesis_progress_update": "PI / advisor / lab / stand-up update",
                "synthesis_handout": "single-page printable leave-behind + QR",
                "synthesis_from_inputs": "synthesis when prior analysis ran outside RO",
                "synthesis_null_findings": "publishable companion for refuted / abandoned",
                "synthesis_cover_letter": "journal cover letter",
                "synthesis_title_workshop": "title generation + iteration",
            },
            "support_protocols": {
                "writing/writing_discussion": "Discussion section",
                "writing/writing_limitations": "Limitations sub-section",
                "writing/writing_results": "Results section",
                "writing/writing_methods": "Methods section",
                "writing/writing_data_availability": "end matter — CRediT / data / code / etc.",
                "writing/writing_core": "universal writing rules",
                "audit/pre_submission_checklist": "final ready-to-submit gate",
            },
            "recurring_deliverables": (
                "A poster/deck/update tied to a RECURRING event (weekly lab "
                "meeting, a conference, a committee) should NOT overwrite the "
                "flat synthesis/<kind> file. Pass a label to tool_synthesis_"
                "scaffold (e.g. label='2026-06-lab-meeting' or 'neurips-poster') "
                "— it writes to synthesis/deliverables/<label-slug>/<kind> with a "
                "README documenting the occasion, so the chain of event "
                "artefacts stays browsable and nothing is clobbered. Omit label "
                "only for the project's single canonical paper."
            ),
        }))
    if topic in {"methodology", "methods"}:
        return _text(_success({
            "picker_protocols": ["methodology/methodology_selection", "methodology/deep_domain_research"],
            "per_method": [
                "causal_inference_deep", "machine_learning", "clinical_trials",
                "meta_analysis", "survey_psychometrics", "qualitative_research",
                "simulation_studies", "replication_study", "ablation_study",
                "pilot_study", "mixed_methods", "bayesian_analysis",
                "timeseries_analysis",
            ],
            "design_protocols": [
                "exploratory_data_analysis", "method_comparison",
                "data_quality_audit", "power_analysis", "evaluation_design",
                "hyperparameter_search_design", "data_ethics_review",
            ],
            "support": ["preregistration", "methodological_consultation",
                        "reproduction_attempt", "tool_discovery"],
        }))
    if topic in {"visualization", "viz", "figures"}:
        return _text(_success({
            "rules": "visualization/figure_guidelines",
            "workflow": "visualization/visualization_workflow",
            "critique": "visualization/figure_critique",
            "multi_panel": "visualization/multi_panel_composition",
            "arc": "visualization/figure_narrative_arc",
            "a11y": "visualization/color_accessibility_audit",
        }))
    if topic in {"modes", "mode", "workspace_mode"}:
        # Workspace MODE is the top-level axis that shapes the whole project:
        # the scaffold on disk, which protocols routing biases toward, and
        # which audit gates apply. Set once at init (the wizard asks) or via
        # the workspace.mode field in inputs/researcher_config.yaml. Sourcing
        # the enum from config keeps this list from drifting.
        from research_os.tools.actions.state.config import VALID_WORKSPACE_MODES
        return _text(_success({
            "what_mode_is": (
                "Workspace MODE is the single top-level axis that shapes a "
                "project end-to-end: (1) the directory scaffold init builds, "
                "(2) which protocols tool_route biases toward, (3) which "
                "audit gates apply. Picked at init, but a project can OUTGROW "
                "its shape — change it later with sys_workspace_mode "
                "(see how_to_set). analysis is the default and the universal "
                "fallback."
            ),
            "registered_modes": sorted(VALID_WORKSPACE_MODES),
            "modes": {
                "analysis": (
                    "DEFAULT. The classic linear numbered-step workspace "
                    "(inputs/ → workspace/NN_step/ → synthesis/). The full "
                    "audit + literature + synthesis surface. Pick this for a "
                    "study that produces a paper / poster / dashboard."
                ),
                "hybrid": (
                    "analysis surface + a tool-build half for projects that "
                    "BUILD a tool AND publish findings about it. Keeps the "
                    "analysis routing surface and ADDS a light bias toward "
                    "hybrid/* (hybrid_workflow home loop + tool_to_analysis_"
                    "handoff for crossing the boundary with the tool version "
                    "pinned). The scaffold is the analysis spine plus a lazy "
                    "tool/ home for the inner repo (also auto-detected)."
                ),
                "tool_build": (
                    "Research OS governs a software build from above: spec/ "
                    "(requirements + design), decisions/ (ADRs), eval/, "
                    "milestones.md, governance.md, CHANGELOG.md, and an INNER "
                    "git repo (workspace.inner_repo, default 'project/'). "
                    "Routing strongly biases toward build/* protocols "
                    "(spec → implement → test → benchmark → release → "
                    "package_and_publish); build vocabulary that collides "
                    "with analysis defers to the build router. Pick this when "
                    "the deliverable IS the code."
                ),
                "exploration": (
                    "Scratch-first quick probes with light gates. "
                    "workspace/scratch is the home base; synthesis stays lazy. "
                    "Routing biases toward exploration/* (loop / triage / "
                    "promote). Pick this for an open-ended 'let me poke at "
                    "this' session that may later promote into an analysis."
                ),
                "notebook": (
                    "Jupyter-first: notebooks/ + data/ + outputs/ are eager. "
                    "Routing biases toward notebook/* across the lifecycle "
                    "(notebook_run → notebook_reproduce → notebook_promote → "
                    "notebook_synthesize). Pick this for interactive iterative "
                    "work that lives in .ipynb rather than numbered step "
                    "scripts."
                ),
                "multi_study": (
                    "A research PROGRAM spanning several studies: studies/ + "
                    "shared/ (codebook, preregistration, governance) + "
                    "roll_up/. Routing biases toward program/* across the "
                    "lifecycle (program_setup → study_register → "
                    "codebook_governance → cross_study_synthesis). Pick this "
                    "for a portfolio of related studies that share methods and "
                    "roll up into one synthesis."
                ),
            },
            "how_to_set": (
                "init: the wizard asks (or --workspace-mode). CHANGE LATER "
                "(4.0.0): modes are first-class TRANSITIONS — call "
                "sys_workspace_mode(operation='transition', to=<mode>, "
                "confirm=true). That ADDITIVELY creates the new mode's surface, "
                "syncs config + .os_state, and records the move to "
                "mode_history.jsonl. Do NOT hand-edit workspace.mode in "
                "inputs/researcher_config.yaml — that leaves the scaffold "
                "missing and the structure audit flags it as mode_drift."
            ),
            "routing_effect": (
                "tool_build / exploration / notebook / multi_study / hybrid "
                "each boost their native sub-intents in tool_route. Only "
                "analysis adds NO bias — it uses the baseline routing surface "
                "(and is the universal fallback). So the same prompt can "
                "resolve to different protocols depending on the active mode."
            ),
            "inspect": (
                "sys_boot returns the active workspace_mode; "
                "sys_workspace_mode(operation='status') reports config vs state "
                "mode, any drift, and the supported transitions from here."
            ),
        }))
    if topic == "gates":
        # Full gate vocabulary — every (scope, dimension) the
        # _AUDIT_DISPATCH table can route to + the 8-gate autopilot
        # floor list + bypass shapes + override_log location. Closes the
        # discoverability gap where researchers learn gate names only
        # from BLOCKED errors.
        return _text(_success({
            "all_audit_gates": {
                "step": {
                    "completeness":         "focal figure + caption + summary + non-stub conclusions + provenance coverage per step.",
                    "literature":           "per-step literature gate — claims_grounded, citations resolved.",
                    "code_quality":         "ruff + AST-based complexity / docstring / smell checks per script.",
                    "evalue":               "E-value sensitivity (VanderWeele & Ding) for observational designs.",
                    "figure":               "PNG DPI + basic visual hygiene per step figure.",
                    "figure_full":          "full figure quality audit (axis, ticks, legend, colour, font).",
                    "figure_interactivity": "dashboard / interactive plot interactivity coverage.",
                    "power":                "power justification gate — verifies you RECORDED test family, effect size + its source, alpha, n, target power (tool does not solve for power).",
                    "assumptions":          "assumptions gate — verifies you RAN + recorded each named diagnostic (statistic + interpretation + response to violations); the tool does not run the tests.",
                    "reproducibility":      "step rerun + bit-stability check (slow + expensive; autopilot floor gate).",
                    "script_naming":        "scripts/ follow <NN>[a-z]_<snake_name>_v<k>.<ext> with <NN> = this step's number (the daemon also watches this).",
                    "provenance_integrity": "re-hashes each output's recorded inputs/outputs; flags STALE results whose inputs changed since they were built (the daemon also watches this).",
                },
                "project": {
                    "citations":          "every workspace/citations.md entry verified against Crossref / S2.",
                    "claims":             "every number in synthesis/paper.md traces to a workspace output.",
                    "cliches":            "anti-bullshit / hedging / vague-quantifier audit on paper prose.",
                    "coherence":          "section-to-section thread + figure-call-order coherence.",
                    "cross_deliverable": "5-dim consistency across paper / poster / dashboard / slides / abstract.",
                    "prose":              "hedging / passive / vague / causal-language gating across all prose.",
                    "version_coherence":  "every output traces to the highest-version script (no v1-fig from v2-script).",
                },
                "synthesis": {
                    "all":                "structural synthesis audit (sections, citations, figures, bibliography).",
                    "dashboard_content":  "dashboard content gate — non-stub story, figure provenance, captions.",
                    "figure_coverage":    "% of workspace figures referenced from synthesis/.",
                    "reviewer_responses": "reviewer-response file coverage (every reviewer point answered).",
                },
            },
            "autopilot_floor_gates": {
                "count": 8,
                "intro": (
                    "In autopilot mode, the dispatcher refuses these calls "
                    "without confirmed=true (or the equivalent gated kwarg). "
                    "Server-enforced — protocol prose alone can't bypass them."
                ),
                "list": [
                    {"tool": "tool_typst_compile",                           "bypass": "tool_typst_compile(confirmed=true, ...)"},
                    {"tool": "tool_audit(scope='step', dimension='reproducibility')", "bypass": "tool_audit(scope='step', dimension='reproducibility', confirmed=true, ...)"},
                    {"tool": "tool_research_tool (paid candidates)",         "bypass": "tool_research_tool(confirmed=true, source='paid', ...)"},
                    {"tool": "sys_path(operation='abandon')",                "bypass": "sys_path(operation='abandon', confirmed=true, path_name='...', rationale='...')"},
                    {"tool": "sys_file_write (synthesis/ + force=true)",     "bypass": "sys_file_write(filepath='synthesis/...', force=true, confirmed=true, content='...')"},
                    {"tool": "tool_package_install",                         "bypass": "tool_package_install(confirmed=true, ...)"},
                    {"tool": "sys_checkpoint_rollback",                      "bypass": "sys_checkpoint_rollback(checkpoint_id='...', confirmed=true)"},
                    {"tool": "tool_task(operation='run')",                   "bypass": "tool_task(operation='run', confirmed=true, ...)"},
                ],
                "note": (
                    "The compile gate (tool_typst_compile) is the moment "
                    "the artefact becomes shareable; confirming it is the "
                    "researcher's final go/no-go on the deliverable."
                ),
            },
            "quality_gate_overrides": {
                "intro": (
                    "Quality gates (not autopilot floor gates) bypass via "
                    "override_<gate>=true + override_rationale='...'. The "
                    "rationale is mandatory under quality_gate_policy=enforce."
                ),
                "examples": [
                    "tool_discussion_coverage_audit(override_discussion_coverage=true, override_rationale='discussion is being rewritten')",
                    "tool_audit(scope='synthesis', dimension='all', override_no_pdfs=true, override_rationale='novel measurement, no literature exists')",
                    "tool_audit(scope='project', dimension='cross_deliverable', override_cross_deliverable=true, override_rationale='...')",
                    "tool_step_complete(step_id='02_eda', override_literature_gate=true, override_rationale='pure data engineering, no claims')",
                ],
            },
            "bypass_log_location": "workspace/logs/override_log.md",
            "discoverability_tools": {
                "tool_audit(scope='active_gates')":       "introspect live armed-gate state on THIS project (which gates have actually fired).",
                "tool_audit_findings(operation='timeline')": "full append-only ledger — every emission, no dedup — for recurrence-pattern + override-loop analysis.",
                "tool_audit_findings(operation='query')":  "latest snapshot per finding id, filtered by severity / dimension / step / since.",
                "tool_audit_findings(operation='explain', id=...)": "full chronological history of one finding id with untruncated suggested_fix.",
            },
            "gate_count_total": 21,
        }))
    if topic in {"audit", "quality"}:
        return _text(_success({
            "master_audit": "audit/audit_and_validation",
            "pre_submission": "audit/pre_submission_checklist",
            "reproducibility": "reproducibility/reproducibility",
            "specific_audits": [
                "tool_audit_step_completeness",
                "tool_audit_version_coherence",
                "tool_audit_code_quality",
                "tool_audit_prose",
                "tool_audit_claims",
                "tool_audit_figure_full",
                "tool_audit_citations",
                "tool_audit_assumptions",
                "tool_audit_reproducibility",
                "tool_preregister_diff",
            ],
            "iteration_versioning": {
                "snapshot": "tool_step_iterate",
                "list": "tool_step_iterations_list",
                "drift_check": "tool_audit_version_coherence",
            },
        }))

    return _text(_success(core))




HANDLERS: dict[str, object] = {}
