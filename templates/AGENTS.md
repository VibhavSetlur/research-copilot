# Research OS — AI Operating Rules

You are connected to the **Research OS MCP server**. This file is loaded
into context every session — it is deliberately short. Step-by-step "how
to do X" lives in **protocols** (load on demand) and **`sys_help`** (deep
topics on demand). Full human guide:
<https://github.com/VibhavSetlur/Research-OS/blob/main/docs/AI_GUIDE.md>.

---

## Mental model

* **You** plan and reason. **Research OS** executes, records, enforces —
  every research action goes through a `sys_*` / `tool_*` / `mem_*` tool. RO
  is a **passive tool provider**: it calls no LLM and has no gateway; all
  reasoning is yours. **The researcher** drops files in `inputs/`, talks in
  natural language, approves checkpoints.
* If `sys_*` tools aren't visible the MCP server isn't connected — tell the
  researcher to restart their IDE. The server is global (one `research-os
  start` serves every project); `sys_active_project` reports the resolved one.

## Every session — two MCP calls on the first turn

1. **`sys_boot`** → state + config + history + next protocol + pause + any
   `active_plan` (+ `config_directives`, `new_context`, `software_components`).
   One call, replaces 4-5.
2. **`tool_route(prompt=<verbatim message>)`** → semantic+trigger router.
   Returns `primary_protocol`, `shortcut_tool`, `decomposition`,
   `complexity`, `ask_user`, `recommended_skills`. If `ask_user` is non-null,
   ASK it then re-route — never guess. PULL the `recommended_skills` for THIS
   task (`skill_view` → load → use), then keep working inside RO.
   - `complexity="high"` → `tool_plan(operation="turn")` (batches by
     `model_profile`: small=1/medium=3/large=6 step/turn), then
     `tool_plan(operation="advance")` after each; if
     `chat_split_recommended`, run `sys_session_handoff`.
   - `complexity="low"` → call `shortcut_tool` directly, OR
     `sys_protocol_get format='summary'` then `format='step' step_id=<id>`.

Subsequent turns: skip `sys_boot` (still in context); go straight to `tool_route` or continue the `active_plan`. **Commit every finalized step** for provenance: `tool_git(operation='commit', scope='project', message='<NN_slug>: …', step_id='<NN_slug>')` (scope='tool' in tool_build) — never leave finalized work untracked; daemon flags `steps_uncommitted`.

## Token economy (read once, apply always)

Spend context on reasoning, not re-reading.
* **Summary-first** protocol loads (`format='summary'` ~300 tok; `'step'`
  for the step you're running; `'full'`/`'lean'` only when needed —
  `'lean'` is the small-model default).
* **Don't re-read** `sys_boot`/`tool_route` payloads, files you just wrote,
  or protocols already in context.
* **Search to find:** `tool_route` / `tool_semantic_route` for protocols,
  `sys_semantic_tool_search` for tools. Rely on `sys_boot`, `tool_route`, and
  the daemon gate state to understand what is currently available; any other
  tool is still callable by name once a search surfaces it.
* **Read the slice you need** of big files, not the whole thing.

## Your operating contract — keep `researcher_config.yaml` in sync

It is your secondary AGENTS.md. `sys_boot` surfaces it as
`config_directives` (+ `config_reconcile_hint`). FOLLOW autonomy /
`quality_gate_policy` / `ambiguity_posture` / `agent_notes` every session,
and MAINTAIN it via `sys_config(operation='set', …)`: name a deliverable →
set `research_goal.output_types`; "be autonomous" → `autonomy_level`; "we're
submitting to Nature" → `venue_template` + `citation_style`;
project rules → `agent_notes`; record the env in `runtime.compute_environment`.
Never silently overwrite a value the researcher set by hand. When
`autonomy_level='coaching'`, don't auto-execute — surface the protocol's
`pedagogical_prelude`, explain WHY a gate fires before fixing it.

**New project?** Don't run init blind — interview first (question/domain,
research vs software vs **hybrid**, desired output, autonomy, compute), fold
into the config, THEN scaffold, THEN tell them to restart the IDE.

**Context drop-zone.** The researcher may drop a paper / note / screenshot
into `inputs/context/` (or a step's `context/`) anytime. `sys_boot.new_context`
+ `tool_route.new_context` surface new files — `sys_file_read` them and fold
in before continuing.

**Glossary.** Introduce a domain term → add a row to `docs/glossary.md`
(`term | definition | source`). `sys_boot.glossary_unfilled` nudges.

## Workspace modes (`sys_boot.workspace_mode`)

Shapes what "a unit of work" and "done" mean — `tool_route` steers you there.
* **analysis** (default) — numbered `workspace/NN_*` steps; done = figures +
  tables + grounded conclusions.
* **hybrid** — research + software; analysis steps PLUS inner code components
  (`sys_boot.software_components`); govern both (steps + inner repo via
  `tool_git`/`tool_build`/`tool_audit(scope="tool")`).
* **tool_build** — RO governs a software build from above (`spec/`,
  `decisions/`, `eval/`); route to `build/*`; done = tests/build/eval pass.
* **exploration** — scratch-first, light gates; promote a probe when it earns it.
* **notebook** — Jupyter-first; promote a trusted notebook to a step.
* **multi_study** — a program of sibling studies under a shared commons.
**Modes are first-class transitions** — a project can outgrow its shape. Don't
hand-edit `workspace.mode` (leaves the scaffold missing → drift). Use
`sys_workspace_mode(operation='transition', to=…, confirm=true)` (additive;
syncs config+state; records the move); `…(operation='status')` shows moves. See
`sys_help(topic='modes')`.

## Domain packs & infra adapters

Bundled **domain packs** add field-specific tools + protocols; infra
**adapters** auto-extract provenance from HPC / workflow / data tooling.
`sys_boot` surfaces field signals and `pack_nudge`; `adapters_detected` lists
fired adapters. A field with no pack still routes fine
(`methodology/deep_domain_research`). Detail: `sys_help(topic='packs')`;
diagnostics `sys_packs_installed`, `tool_adapters_list`.

## Daemon (optional — present on some projects)

A project may run a **daemon**: a separate persistent process that executes
long jobs, tracks provenance/freshness, enforces hard gates, and notifies the
researcher. OPTIONAL — when none runs, everything below
degrades to the stdio behaviour and you act exactly as today.

* **Check it when continuity matters.** `sys_daemon` reports background runs,
  the recommended next action, the resource budget, and undelivered
  notifications — call it at session start or before a heavy run.
  `running:false` = no daemon; proceed normally.
* **A gate may return `what='consent_required'`.** With a daemon present, your
  own `confirmed=true` is NOT enough for a floor gate — only a human-authorised,
  one-shot token clears it (error carries `gate_key` + `arg_fingerprint`). Tell
  the researcher what needs approval → `sys_consent(action='request', …)` → they
  approve (`research-os daemon consent approve <id>`) → `sys_consent(action='token',
  …)` → retry with `consent_token=…`. NEVER request consent they didn't authorise.
* **Read `sys_boot.daemon_notes` AND act on `daemon_flagged_issue`
  (watchdog).** A running daemon re-checks the project in the background. Read
  `daemon_notes` at boot; every turn, a `daemon_flagged_issue` in an envelope's
  `audit_findings` means it just caught a problem — fix BLOCK items before
  building further (persistent ones get escalated to the researcher).

## Hard rules (NEVER violate)

1. **`.os_state/` is never hand-edited.** `inputs/` is editable, but
   `inputs/raw_data/` + `inputs/literature/` are the original record —
   change only with `force=true` + researcher OK (warns, marks intake
   stale). `inputs/context/` is a free drop-zone.
2. **Never invent citations** — `tool_citations_verify` + `tool_synthesis_check`
   verify every key before `tool_typst_compile`.
3. **No causal language on observational data** — "associated with", not "causes".
4. **Never pick a method/library from memory** — `tool_research_method` /
   `tool_research_tool` first; register the citation as the decision's grounding.
5. **Never delete in `workspace/`** — `sys_path(operation="abandon")` (renames
   to `__DEAD_END`, preserves files).
6. **Never block on a long job** — `tool_task(operation="run")` /
   `tool_slurm_submit`, then poll.
7. **Never invent step slugs** — derive from the goal (`guidance/analysis_plan`).
8. **No judgemental or first-person language in deliverables** — supportive
   professional voice; refer to prior work as "the initial analysis".
9. **Never one-shot complex prompts** — walk the `active_plan`; author the
   synthesis file → `tool_synthesis_check` until clean → compile.
10. **Figures = `<slug>.png` + an authored `<slug>.caption.md`** (you write
    the plot script per `visualization/figure_guidelines`; RO ships no
    chart-builder). `sys_file_read` every figure before declaring done.
    Every number in a deliverable must trace to a workspace output
    (`tool_audit(scope="project", dimension="claims")`).
11. **Multi-script steps need a `pipeline.yaml`** (`tool_step_pipeline`); a
    monolith spanning figures+tables+reports is BLOCKED by the step
    completeness audit — split into atomic sub-tasks.
12. **Edit = new version, never overwrite** a produced `*_v<n>` artifact —
    write `_v<n+1>` (the write gate refuses in-place); a deliberate iteration
    calls `tool_step(operation="iterate", …)` so the step snapshots together.

When the researcher EXPLICITLY authorises a bypass in their current message,
pass the per-audit override flag + an `override_rationale` (logged to
`workspace/logs/override_log.md`; resurfaced at pre-submission). Mechanics:
`sys_help(topic='overrides')`.

## Quick lookup

| Need | Use |
|---|---|
| Find a tool by what it does | `sys_semantic_tool_search(query=…)` |
| Ranked protocol candidates | `tool_semantic_route(prompt=…)` |
| Tight tool shortlist for a protocol | `sys_active_tools(protocol_name)` |
| What does a tool do? | `sys_tool_describe(name)` |
| Preview a protocol's calls before running | `tool_dry_run(protocol_name)` |
| Finish a step (1 call, not 4) | `tool_step_complete(step_id=…)` |
| Vague / cross-disciplinary ask | `guidance/scope_clarification` |
| Researcher pivoted mid-plan | `tool_plan(operation="clear")` → re-route |
| New file mid-flow | `tool_context_intake` |
| Broken workspace | `tool_workspace_repair` |
| Recovery | `sys_checkpoint_list` → `sys_checkpoint_rollback` |
| End of session | `sys_session_handoff` |
| Deeper guidance | `sys_help(topic=…)` — see below |

**`sys_help` topics (load on demand):** `routing`, `iteration`, `overrides`,
`modes`, `gates`, `recovery`, `fields`, `packs`, `depth`, `anti_patterns`,
`docs`, and category orientation (`synthesis`, `methodology`, `visualization`,
`audit`, `literature`, `writing`). Cold start with no context: `sys_help` then
`sys_help(topic='routing')`.

**Append-only logs** (`methods.md`, `analysis.md`, `citations.md`) only via
`mem_*`; numbers via `mem_log(kind="decision"|"methods"|"hypothesis")`. Every
decision cites grounding via `tool_ground(mode="explicit")` or
`tool_verify(scope="project")` flags it before synthesis.

**Small models** (Haiku / Flash / GPT-4o-mini / local): once, set
`sys_config(operation='set', key='ai.model_profile', value='small')` — loads
go `lean`, `shortcut_tool` is preferred over full decomposition.
