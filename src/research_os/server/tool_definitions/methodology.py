"""Tool definitions for the methodology domain."""
from __future__ import annotations

from typing import Any


METHODOLOGY_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "tool_step": {
        "short": "Unified step lifecycle tool. operation=iterate|iterations_list|revision_options|env_lock.",
        "description": "Unified step-lifecycle dispatcher. operation='iterate' bumps an analysis step into a new named iteration — copies selected scripts/figures/tables + their sidecars (.caption.md / .prov.json) + conclusions.md into workspace/<step>/.versions/v<n>/, appends a row to workspace/<step>/iterations.yaml with the REQUIRED rationale, and returns the recommended _v<n+1> rename for each script. operation='iterations_list' returns the iterations.yaml ledger for a step (rationale, snapshot dir, script/figure/table names per version). operation='revision_options' (call AFTER tool_path_finalize) surfaces the anti-one-shot pause-and-revise heuristic: would_benefit_from_revision, suggested_revisions, alternative_paths, handoff_recommended (true at 5+ finalized steps), risk_signals — AI MUST present VERBATIM and WAIT for researcher choice. operation='env_lock' pins the step's environment/ for years-later reproduction (requirements + python_version + optional conda.yaml / Dockerfile / Apptainer step.def / entrypoint.sh). Prefer over sys_env_snapshot for any step you intend to publish. Use tool_step_complete for the end-of-step bundle (finalize + completeness audit + literature gate + revision options).",
        "category": "state",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["iterate", "iterations_list", "revision_options", "env_lock"],
                    "description": "Which step sub-operation to invoke.",
                },
                "step_id": {
                    "type": "string",
                    "description": "Numbered step folder, e.g. '03_fit_baseline'. Required for iterate / iterations_list / revision_options; optional for env_lock (defaults to most-recent active step with a warning).",
                },
                # operation='iterate' kwargs
                "rationale": {
                    "type": "string",
                    "description": "operation='iterate' — REQUIRED. Why this iteration is happening (design change, parameter sweep, reviewer ask, etc.). Recorded in iterations.yaml.",
                },
                "scripts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "operation='iterate' — optional names under scripts/ to include. Default: every script.",
                },
                "figures": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "operation='iterate' — optional names under outputs/figures/ to include. Default: every figure.",
                },
                "tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "operation='iterate' — optional names under outputs/tables/ to include. Default: every table.",
                },
                "bump_conclusion": {
                    "type": "boolean",
                    "description": "operation='iterate' — copy conclusions.md into the snapshot (default true).",
                },
                # operation='env_lock' kwargs
                "write_conda_yaml": {
                    "type": "boolean",
                    "description": "operation='env_lock' — also emit environment/conda.yaml.",
                },
                "write_dockerfile": {
                    "type": "boolean",
                    "description": "operation='env_lock' — also emit environment/Dockerfile.",
                },
                "write_apptainer": {
                    "type": "boolean",
                    "description": "operation='env_lock' — emit step.def for HPC Apptainer/Singularity.",
                },
                "write_entrypoint": {
                    "type": "boolean",
                    "description": "operation='env_lock' — emit environment/entrypoint.sh (default true).",
                },
            },
            "required": ["operation"],
        },
    },
    "tool_step_pipeline": {
        "short": "Unified step sub-task pipeline tool. operation=define|run|status|diagram.",
        "description": "Unified step-pipeline dispatcher for the per-step sub-task DAG (ingest→clean→validate→fit→diagnose→visualize→report). operation='define' (default when name/description/nodes/template imply authoring) seeds workspace/<step>/pipeline.yaml from a 7-node template; required for any step with >2 scripts (audit gate). operation='run' walks the pipeline.yaml DAG in topological order with content-hash caching — nodes whose script+inputs+params hash matches a previous successful run are SKIPPED; only the affected downstream chain re-runs after an edit; each output gets a .prov.json sidecar (PROV-O); pass `only` to restrict to nodes (upstream deps auto-included), `force=true` to bypass cache, `dry_run=true` to plan only. operation='status' reads pipeline.yaml + the most recent run log and per-node reports fresh / stale / never_run. operation='diagram' writes workspace/<step>/pipeline.mermaid which the dashboard's per-step appendix embeds. See guidance/analysis_plan for the workflow.",
        "category": "exec",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["define", "run", "status", "diagram"],
                    "description": "Which pipeline sub-operation to invoke.",
                },
                "step_id": {
                    "type": "string",
                    "description": "Numbered step folder (e.g. 03_logistic_baseline). Required for every operation.",
                },
                # operation='define' kwargs
                "name": {
                    "type": "string",
                    "description": "operation='define' — display name for the pipeline.",
                },
                "description": {
                    "type": "string",
                    "description": "operation='define' — free-text description of the pipeline.",
                },
                "nodes": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "operation='define' — optional custom node list (see analysis_plan protocol for shape).",
                },
                "template": {
                    "type": "string",
                    "description": "operation='define' — default (7-node ingest→...→report).",
                },
                # operation='run' kwargs
                "only": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "operation='run' — node IDs to run (transitive deps auto-included).",
                },
                "force": {
                    "type": "boolean",
                    "description": "operation='run' — skip the cache and re-run every node.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "operation='run' — plan only; do not execute.",
                },
            },
            "required": ["operation", "step_id"],
        },
    },
    "tool_plan_step_grounded": {
        "short": "Plan a step with explicit Thought / Required-grounding / Action / Verification per sub-task.",
        "description": "Stronger than tool_plan_step. Auto-inventories the project's available evidence (inputs, context notes, literature, prior conclusions). Each sub-task has filled slots for thought, required grounding (which evidence will be consulted), action, expected outputs, verification question, and prior lessons consulted. Use for substantive analyses where every action should be traceable to evidence.",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "inputs_to_consult": {"type": "array", "items": {"type": "string"}},
                "context_to_consult": {"type": "array", "items": {"type": "string"}},
                "literature_queries": {"type": "array", "items": {"type": "string"}},
                "max_substeps": {"type": "number"},
            },
            "required": ["goal"],
        },
    },
    "tool_preregister": {
        "short": "Unified preregistration tool. operation=freeze|diff.",
        "description": "Unified preregistration dispatcher for the SAP freeze/diff cycle. operation='freeze' (call BEFORE data analysis) snapshots methods.md + active hypotheses to workspace/.preregistration/prereg_<iso>.{md,yaml} — content-hashed, immutable. Accepts full SAP fields (primary_outcomes, secondary_outcomes, target_n, power_assumption, stopping_rule, subgroups, sensitivity, multiplicity, inclusion, exclusion, missing_data, additional_analyses, contingencies, anticipated_deviations, data_status). operation='diff' (call at synthesis time) loads the most recent .preregistration/prereg_*.yaml; compares hypotheses (added / removed / re-worded), methods.md (lines added / removed since freeze), and the paper's primary-outcome mention. Surfaces deviations the discussion section must acknowledge. Writes workspace/logs/preregistration_diff.md. See methodology/preregistration for the full SAP field list and the OSF submission flow.",
        "category": "audit",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["freeze", "diff"],
                    "description": "Which preregistration sub-operation to invoke.",
                },
                # operation='freeze' kwargs
                "primary_outcomes": {"type": "string", "description": "operation='freeze' — primary outcome measure(s)."},
                "secondary_outcomes": {"type": "string", "description": "operation='freeze' — secondary outcome measure(s)."},
                "target_n": {"type": "number", "description": "operation='freeze' — planned sample size."},
                "power_assumption": {"type": "string", "description": "operation='freeze' — effect-size + alpha + power assumption (e.g. 'd=0.5, alpha=0.05, power=0.80')."},
                "stopping_rule": {"type": "string", "description": "operation='freeze' — stopping rule for data collection."},
                "subgroups": {"type": "array", "items": {"type": "string"}, "description": "operation='freeze' — pre-specified subgroup analyses."},
                "sensitivity": {"type": "array", "items": {"type": "string"}, "description": "operation='freeze' — planned sensitivity analyses."},
                "multiplicity": {"type": "string", "description": "operation='freeze' — multiple-comparison correction (e.g. 'BH FDR @ q=0.05')."},
                "inclusion": {"type": "array", "items": {"type": "string"}, "description": "operation='freeze' — inclusion criteria."},
                "exclusion": {"type": "array", "items": {"type": "string"}, "description": "operation='freeze' — exclusion criteria."},
                "missing_data": {"type": "string", "description": "operation='freeze' — missing-data handling strategy."},
                "additional_analyses": {"type": "array", "items": {"type": "string"}, "description": "operation='freeze' — pre-specified additional analyses."},
                "contingencies": {"type": "array", "items": {"type": "string"}, "description": "operation='freeze' — planned contingencies if assumptions break."},
                "anticipated_deviations": {"type": "array", "items": {"type": "string"}, "description": "operation='freeze' — known deviations from registered plan."},
                "data_status": {"type": "string", "description": "operation='freeze' — 'not yet collected' (default) | 'collected, not analysed' | 'analysed'."},
            },
            "required": ["operation"],
        },
    },
    "tool_sensitivity": {
        "short": "Unified sensitivity tool. operation=define|run.",
        "description": "Unified sensitivity dispatcher for multiverse / specification-curve analyses. operation='define' creates workspace/<step>/sensitivity.yaml — base_script + a grid of analytic choices (covariate sets, exclusion rules, transformations, model families). The runner will fan out the Cartesian product; the base script reads each spec via env vars (RESEARCH_OS_SPEC_<KEY>) and writes a one-row {estimate, ci_lo, ci_hi, <spec_columns>} record per run. operation='run' executes base_script once per combination; collects {estimate, ci_lo, ci_hi, spec_columns} into the output CSV; renders a Steegen-style specification curve (ordered effect dots + CIs over a choice matrix) into outputs/figures/<NN>_specification_curve.png. Drops a provenance sidecar.",
        "category": "exec",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["define", "run"],
                    "description": "Which sensitivity sub-operation to invoke.",
                },
                "step_id": {
                    "type": "string",
                    "description": "Numbered step folder (e.g. '03_logistic_baseline'). Required for both define and run.",
                },
                # operation='define' kwargs
                "base_script": {"type": "string", "description": "operation='define' — REQUIRED. Path to the analysis script that reads RESEARCH_OS_SPEC_<KEY> env vars and emits a one-row CSV."},
                "estimate_column": {"type": "string", "description": "operation='define' — name of the estimate column emitted by base_script (default 'estimate')."},
                "ci_columns": {"type": "array", "items": {"type": "string"}, "description": "operation='define' — names of the two CI columns emitted by base_script (default ['ci_lo', 'ci_hi'])."},
                "grid": {"type": "object", "description": "operation='define' — dict mapping spec key → list of values; the runner fans out the Cartesian product."},
                "output_csv": {"type": "string", "description": "operation='define' — path for the collected one-row-per-spec CSV (default 'data/next_step_output/grid_results.csv')."},
                # operation='run' kwargs
                "max_specs": {"type": "number", "description": "operation='run' — cap for testing; default = all combos."},
                "render_figure": {"type": "boolean", "description": "operation='run' — render the specification-curve PNG (default true)."},
            },
            "required": ["operation", "step_id"],
        },
    },
    "tool_redteam_review": {
        "short": "Generate a hostile-reviewer report scaffold against the paper.",
        "description": "Writes workspace/reviews/redteam_<persona>_<ts>.md — the structure of a real journal reviewer report: summary, overall recommendation, major comments M1-M5, minor comments, threats-to-validity (internal/external/construct/statistical), devil's-advocate questions. Personas: methodological_skeptic | statistical_referee | sympathetic_peer. The model fills the scaffold using ONLY the listed workspace inventory.",
        "category": "audit",
        "inputSchema": {
            "type": "object",
            "properties": {
                "persona": {"type": "string", "description": "methodological_skeptic (default) | statistical_referee | sympathetic_peer"},
            },
        },
    },
    "tool_null_findings_report": {
        "short": "Companion document for refuted / inconclusive / underpowered / abandoned analyses.",
        "description": "Walks the hypothesis tracker (refuted + inconclusive), every step's power_report.md (computed power < 0.8), and every __DEAD_END path. Writes synthesis/null_findings.md — a publishable companion that fights the file-drawer problem.",
        "category": "audit",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "tool_plan_step": {
        "short": "Break a complex step into atomic sub-tasks. Use BEFORE coding non-trivial work.",
        "description": "Force a complex step to be broken into atomic sub-tasks BEFORE coding. Writes a plan markdown the AI executes piecewise. Required by analysis_plan when scope is non-trivial.",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "max_substeps": {"type": "number"},
            },
            "required": ["goal"],
        },
    },
    "mem_hypothesis_add": {
        "short": "Register a new hypothesis (state + analysis.md). Use when introducing a testable claim.",
        "description": "Register a new hypothesis (tracked in state.active_hypotheses + analysis.md).",
        "category": "memory",
        "inputSchema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string"},
                "hypothesis_id": {"type": "string", "description": "Optional; auto-assigned H1, H2, ..."},
                "direction": {"type": "string"},
                "status": {"type": "string", "description": "testing|supported|refuted|inconclusive"},
            },
            "required": ["statement"],
        },
    },
    "mem_hypothesis_list": {
        "short": "List every tracked hypothesis. Use when reviewing active claims.",
        "description": "List every tracked hypothesis.",
        "category": "memory",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "tool_plan_next_step": {
        "short": "Propose the BEST next step from state + fresh literature. Use when researcher asks 'what next?'.",
        "description": "Survey current state, pull fresh literature + tool candidates, propose the BEST next step. Use for iterative workflows where the researcher wants the AI to decide what's worth doing next.",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "search_literature": {"type": "boolean"},
                "search_tools": {"type": "boolean"},
            },
        },
    },
    "tool_branch_recommendation": {
        "short": "Decide: branch into a new parallel experiment or extend the current one. Use when unsure.",
        "description": "Decide whether to branch into a new parallel experiment or continue extending the current one.",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    "tool_session_resume": {
        "short": "Reconstruct intent + status from logs after a pause / new chat. Use when resuming a session.",
        "description": "Reconstruct intent + status from logs after a pause / handoff / new chat session. Returns a structured 'resume brief' (current stage, hypotheses, open paths, running tasks, recommended next protocol) plus the message the AI should hand back to the researcher.",
        "category": "interaction",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "tool_progress_digest": {
        "short": "One-page project summary (experiments, hypotheses, artifact counts). Use for status check-ins.",
        "description": "One-page summary of the project: experiments active/completed/dead-end, hypotheses by status, figures/tables/reports counts, citations counted. Writes workspace/logs/progress_digest.md AND returns the markdown.",
        "category": "interaction",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "tool_quick_review": {
        "short": "Stage a one-page paper-appraisal skeleton at workspace/reviews/. Use for 'what do you think of this paper?'.",
        "description": "Stage a one-page critical-appraisal skeleton for a paper at workspace/reviews/<slug>.md. AI then populates it per the `guidance/quick_paper_review` protocol. Use for fast peer-review or 'what do you think of this paper?' requests.",
        "category": "research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paper_path": {
                    "type": "string",
                    "description": "Path to a local PDF/MD/TXT in inputs/literature/ OR a URL.",
                },
                "lens": {
                    "type": "string",
                    "description": "claims_vs_evidence (default) | methodological_rigour | novelty | statistical_inference | replicability",
                },
            },
            "required": ["paper_path"],
        },
    },
    "tool_plan": {
        "short": "Unified plan dispatcher. operation='turn'|'advance'|'clear'. Replaces tool_plan_{turn,advance,clear}.",
        "description": "Consolidates the three plan-progression tools behind one entry. operation='turn' returns the this-turn/next-turn batch (replaces tool_plan_turn). operation='advance' marks the current step done + returns the next (replaces tool_plan_advance; honours override_gate). operation='clear' discards the active plan (replaces tool_plan_clear). tool_plan_step_grounded stays standalone — distinct purpose.",
        "category": "routing",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["turn", "advance", "clear"]},
                "override_gate": {"type": "boolean"},
                "override_rationale": {"type": "string"},
            },
            "required": ["operation"],
        },
    },
}
