# Tool Catalog

**Live MCP tools** across three namespaces (`sys_*` / `tool_*` / `mem_*`).
Exactly 46 tools are active. Legacy names dispatch via `_ALIASES` +
`_ALIAS_PARAM_INJECTION`; fully removed names return a friendly
`_REMOVED_TOOLS` error. See `CHANGELOG.md` for the old → new table.

For *when* to use a tool, see [PROTOCOLS.md](PROTOCOLS.md) — protocols
string tools together to do real work. For *which* protocol to load,
call `tool_route` and the router picks one.

---

## Discovery + routing (call these first)

| Tool | Purpose |
|---|---|
| `sys_boot` | **Always your first call.** Bootstrap, locate, or read/note config in one entry point. |
| `tool_route` | Route prompts to protocols or search the tool catalog semantically. |
| `sys_protocol_get` | Load one protocol as ref, summary, step, lean, dryrun, or full. |
| `sys_active_tools` | Return the active tool shortlist for one protocol. |
| `tool_protocols_list` | List protocols with category, pack, and intent metadata. |
| `tool_dry_run` | Preview a protocol tool-call sequence without executing it. |

---

## Full catalog, alphabetical by canonical name

### `mem_*` — memory ledgers

| Tool | Purpose |
|---|---|
| `mem_hypothesis` | Add, list, update, or get tracked hypotheses. |
| `mem_log` | Append decisions, hypotheses, analyses, methods, or lessons to memory. |
| `mem_retrieve` | Retrieve memory by pointer or semantic query. |
| `mem_search` | Semantic search across recorded memory. |

### `sys_*` — system, workspace, state, files

| Tool | Purpose |
|---|---|
| `sys_active_project` | Return the project root resolved for this request. |
| `sys_active_tools` | Return the active tool shortlist for one protocol. |
| `sys_boot` | Bootstrap, locate, or read/note config in one entry point. |
| `sys_env` | Snapshot environments or generate Docker files. |
| `sys_file_list` | List files in a workspace directory recursively. |
| `sys_file_read` | Read a workspace file up to 50MB. |
| `sys_file_write` | Write a workspace file with immutable-input safeguards. |
| `sys_notify` | Notify the researcher and log the message. |
| `sys_protocol_get` | Load one protocol as ref, summary, step, lean, dryrun, or full. |
| `sys_mode` | Query or switch the active persona (scruffy/neat/critique/delegation). |
| `sys_state_get` | Read workspace state or manage analysis paths. |
| `sys_workspace_tree` | Return a structured tree of workspace files. |

### `tool_*` — research, analysis, synthesis, execution

| Tool | Purpose |
|---|---|
| `tool_audit` | Unified audit across step, project, synthesis, tool, and active gates. |
| `tool_bash_exec` | Execute Bash scripts, with optional background-task fields. |
| `tool_build` | Run configured build, test, or lint commands. |
| `tool_data` | Sample, profile, or convert tabular data. |
| `tool_dry_run` | Preview a protocol tool-call sequence without executing it. |
| `tool_finalize_project` | Check or enforce the final project ship gate. |
| `tool_git` | Run contained git operations for project or inner tool repos. |
| `tool_ground` | Register a grounded claim from explicit sources or project context. |
| `tool_lessons` | Record, consult, or replay lessons and failure memory. |
| `tool_migrate_audit` | Audit a messy project directory and map it into RO layout. |
| `tool_notebook_exec` | Execute a Jupyter notebook with optional papermill parameters. |
| `tool_package_install` | Install Python packages and record them in requirements. |
| `tool_plan` | Plan turns, step iterations, pipelines, or grounded substeps. |
| `tool_preregister` | Freeze or diff a preregistration plan. |
| `tool_protocols_list` | List protocols with category, pack, and intent metadata. |
| `tool_python_exec` | Execute Python scripts, with optional data-operation passthroughs. |
| `tool_reliability` | Log reliability events or generate a reliability report. |
| `tool_reviewer` | Scaffold, write, or compile reviewer responses. |
| `tool_route` | Route prompts to protocols or search the tool catalog semantically. |
| `tool_scratch` | Write, run, list, or clear scratch sandbox files. |
| `tool_search` | Search literature/web, scrape pages, or save literature hits. |
| `tool_sensitivity` | Define or run multiverse sensitivity analyses. |
| `tool_session_handoff` | Generate a markdown handoff for a future session. |
| `tool_slurm_submit` | Submit a SLURM job using project cluster defaults. |
| `tool_synthesis_scaffold` | Scaffold a synthesis deliverable from archetypes and palettes. |
| `tool_task` | Run, inspect, list, or kill background tasks. |
| `tool_thought` | Log or read ReAct-style thought traces. |
| `tool_typst_compile` | Compile a Typst source to PDF. |
| `tool_verify` | Verify claims, project grounding, outputs, or step evidence. |
| `tool_workflow_dag` | Build the numbered-step workflow DAG. |

---

## Aliases (still callable, resolve to canonical)

Common aliases that still dispatch:

| Alias | Resolves to |
|---|---|
| `sys_where`, `sys_config` | `sys_boot` |
| `sys_path`, `sys_step`, `sys_state_summary` | `sys_state_get` |
| `sys_semantic_tool_search` | `tool_route` |
| `tool_web_scrape`, `tool_literature_search_and_save` | `tool_search` |
| `tool_step`, `tool_step_pipeline`, `tool_plan_step_grounded` | `tool_plan` |
| `mem_hypothesis_add`, `mem_hypothesis_list` | `mem_hypothesis` |
| `view_workspace_tree` | `sys_workspace_tree` |
| `tool_log_decision` | `mem_log` |
| `tool_audit_figure_quality` | `tool_audit` |
| `tool_audit_statistical_power` | `tool_audit` |

Hard-removed names (return a friendly error) are listed in `CHANGELOG.md`.

## Per-step audit overrides

Audit gates can be overridden per call by passing an `override_<gate>` kwarg
to `tool_audit`, always paired with a mandatory `override_rationale` explaining
why. Every override is appended to `workspace/logs/override_log.md`.

| Override kwarg | Effect |
| --- | --- |
| `override_gate` | Generic per-gate override (name the gate in `override_rationale`). |
| `override_rationale` | **Required** with any override — the recorded justification. |
| `override_completeness_gate` | Bypass the step-completeness gate. |
| `override_cross_deliverable` | Bypass the cross-deliverable consistency gate. |
| `override_dashboard_content_gate` | Bypass the dashboard-content gate. |
| `override_discussion_coverage` | Bypass the discussion-coverage gate. |
| `override_grounding` | Bypass the grounding requirement. |
| `override_grounding_gate` | Bypass the grounding gate. |
| `override_literature_gate` | Bypass the literature-loop gate. |
| `override_no_pdfs` | Proceed when no source PDFs are present. |

Every override requires `override_rationale` and is logged to
`workspace/logs/override_log.md`.
