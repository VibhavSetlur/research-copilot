# Changelog

All notable changes to Research OS are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) ·
Versioning: [SemVer](https://semver.org).

---

## [4.4.6] — array-items schema fix for Gemini API compatibility (2026-07-01)

A PATCH release: fixes six `INVALID_ARGUMENT (400)` errors from the Gemini
API, which requires `items` on every `type: "array"` parameter in tool
function-calling schemas. The MCP server omitted `items` on six parameters
across four tools.

### Fixed
- **`tool_ground`** — `sources`, `context_paths`, `cited_excerpts` each
  lacked `items` in their JSON schema. Added `items: {type: "object|string"}`
  as appropriate.
- **`tool_verify`** — `verifications` array lacked `items` (complex object).
- **`mem_log`** — `assumptions` array lacked `items` (string items).
- **`tool_step_pipeline`** — `nodes` array lacked `items` (object items).

## [4.4.5] — large-data symlinks · canonical scratch · paper-ready captions (2026-06-30)

A PATCH release bundling three researcher-reported bugs.

### Fixed
- **Large raw data is symlinked, not copied.** `tool_context_intake` copied
  every ingested file into `inputs/raw_data/` regardless of size — wasteful
  when researchers work with tens-to-hundreds of GB. Files ≥ 1 GB are now
  SYMLINKED to the source's absolute path (same `inputs/raw_data/<name>`
  access path; bytes stay put), small files still copied so the project stays
  self-contained. Symlink failure (unsupported FS) falls back to copy; the
  staging method is recorded in the intake log.
- **One canonical throwaway dir: `workspace/scratch/`.** The doctor check +
  generated `.gitignore` + docs previously also legitimised `workspace/cache/`,
  which is why the AI sometimes used `cache`, sometimes `scratch`. `cache/` is
  dropped from the generated gitignore (legacy projects still accepted);
  `scratch/` is the single home. `scratch` now supports organized subfolders
  (`probes/`, `plans/`, `context/`, `data/`) with a provenance `NOTES.md`
  convention, and `scratch_write`/`scratch_run`/`scratch_list` handle nested
  paths (traversal still blocked).
- **Figure captions carry a paper-ready prose block.** The caption sidecar
  was finding-rich but had no single copy-pasteable caption. `caption.md` now
  must lead with a `## Caption` section of continuous journal-language prose
  (the text a reader pastes under the figure in a manuscript); the figure
  audit warns when it's missing or is only bullets/metadata. Panel breakdowns
  + scope/caveats stay below as supporting material.

### Added
- `caption_template()` helper (paper-ready `## Caption` + supporting sections).
- Symlink threshold constant `_SYMLINK_THRESHOLD_BYTES` (1 GB).

---

## [4.4.4] — versioned-artifact immutability (bump, don't overwrite) (2026-06-30)

A PATCH release: fixes the bug where the AI ignored the `_v<k>` versioning
convention and overwrote an existing version of a produced artifact in place,
destroying that version's provenance.

### Fixed
- **`sys_file_write` now refuses to overwrite an existing versioned artifact**
  (`*_v<n>.<ext>`) under `workspace/` or `synthesis/`. The error names the
  bumped filename (`_v<n+1>`, computed above the highest existing sibling
  version) so the AI writes the edit as a NEW version instead of clobbering
  the old one. `force=true` remains the deliberate escape hatch for a genuine
  same-version fix (e.g. a typo before the file was used downstream).
- The rule is enforced at WRITE time (live, mid-prompt), so a model that
  forgets the convention is corrected immediately rather than caught later.

### Added
- Versioned-name helpers in `audit/script_naming.py` (the single source of
  truth for the `_v<k>` convention): `parse_versioned_name`,
  `is_versioned_name`, `next_version_name`, `highest_existing_version`,
  `suggest_version_bump`.
- Guidance: `sys_file_write` description + `templates/AGENTS.md` rule 12
  ("edit = new version, never overwrite") teach the rule.

---

## [4.4.3] — lean MCP tool surface (progressive disclosure) (2026-06-30)

A PATCH release: fixes the context-bloat bug where the MCP `list_tools()`
handshake advertised the full ~160-tool catalog every session, flooding the
client's context before any work began.

### Fixed
- **MCP handshake now advertises a lean CORE surface (~25 tools) by default**,
  not all ~160. The boot ritual + routing/discovery tools + file/state
  plumbing are exposed; every other tool stays fully callable by name. This
  is safe because `call_tool` dispatches against the full handler registry,
  not the advertised list — hiding a tool defers its description, it does not
  remove the tool. Cuts the per-session tool-list context cost dramatically.

### Added
- **`RESEARCH_OS_TOOL_SURFACE` env var** (`server/tool_surface.py`) to control
  the handshake surface: `core` (default, lean bootstrap), `mode` (CORE + the
  active workspace mode's working tools), or `full` (the old all-tools
  behaviour). Set it in your MCP config `env` block. Unknown/empty ⇒ `core`;
  any error resolving a narrowed surface degrades open to `full`.
- Updated MCP `instructions` + `templates/AGENTS.md` + `docs/SETUP.md` to teach
  progressive disclosure: find a tool via `sys_active_tools` /
  `tool_tools_list` / `sys_semantic_tool_search` / `sys_tool_describe`, then
  call it directly even though it was not in the handshake list.

---

## [4.4.2] — synthesis scratch + meetings; dashboards/slides never use a step (2026-06-29)

A PATCH release: organization + git-hygiene fixes, no new tools or protocols.

### Fixed / Improved
- **Dashboards + slide decks never consume a numbered workspace step.** They
  are synthesis deliverables — `tool_synthesis_scaffold` gained `scratch=true`
  to iterate a deliverable in `synthesis/scratch/` (a **gitignored** draft
  area) until it's done, then land the finished file in its proper home. The
  `synthesis_dashboard` + `synthesis_slides` protocols now say this explicitly.
- **Meeting content is organized under `synthesis/meetings/<date>/`.**
  `tool_synthesis_scaffold(meeting='<date-or-slug>')` routes a deck / dashboard
  / handout into one dated folder with a README, so everything a single meeting
  needs (plus its figures + tables) lives together and is committed.
- **`synthesis/scratch/` is gitignored; finished synthesis is committed.** The
  unanchored `scratch/` ignore pattern already covers it; the gitignore comment
  now documents the synthesis draft area, and the daemon's `steps_uncommitted`
  watch now also covers `synthesis/` (excluding the gitignored scratch) so
  finished deliverables sitting outside git get flagged.
- **PROJECT_LAYOUT.md** documents the `synthesis/` structure: flat canonical
  deliverable, `scratch/` draft area, `meetings/<date>/`, `deliverables/<event>/`.

---

## [4.4.1] — planning-doc fix + per-step env auto-lock + git provenance (2026-06-28)

A PATCH release: bug fixes, no new tools or protocols. Three reported bugs.

### Fixed
- **Planning docs were inconsistent with the protocol.** HOW_IT_WORKS.md and
  SCENARIOS.md described deep/iterative planning as writing
  `workspace/scratch/plan_v1.md` / `plan_v2.md`, but the actual protocol writes
  the durable, branchable `inputs/research_plan.md` with an append-only
  iteration log. The docs now match the protocol. Added a HOW_IT_WORKS section
  explaining the THREE distinct plan artifacts and how they relate:
  `inputs/research_plan.md` (project arc) → `workspace/<NN>/plan.md` (per-step
  iterative plan you go back and forth on before a step runs, e.g. on step 06)
  → finalize record.
- **Per-step environment + run recipe is now created automatically.** Every
  step that ran scripts now gets its own pinned environment AND a clean rerun
  recipe at `tool_path_finalize` — `workspace/<NN>/environment/` with
  requirements.txt + python_version + session.yaml + conda.yaml + Dockerfile +
  entrypoint.sh (the single command that reproduces every output). Previously
  the per-step lock only ran when explicitly requested, so steps were left
  un-shareable / un-rerunnable. Also fixed `step_env_lock` over-broadening the
  step's requirements with the whole project's imports (now step-scoped).
- **The AI could not commit analysis work to git.** `tool_git` was hard-scoped
  to the tool_build inner repo, so in an analysis project it had no way to
  commit the workspace — work piled up as untracked changes with no provenance
  trail. Added `scope='project'` (the research workspace root) vs `scope='tool'`
  (the inner repo), auto-picked by workspace mode. The analysis protocol now
  has a `commit_step` after finalize, AGENTS.md mandates committing each
  finalized step, and the daemon flags `steps_uncommitted` when finalized work
  sits outside git.

---

## [4.4.0] — prompt cookbook + step-scoped Docker + sample-data protocol (2026-06-28)

A MINOR release (bug-fix-flavored, but it adds a new protocol + a new tool
capability, so it is correctly a MINOR). Focus: make it obvious how to ask
Research OS for what you want, and close the gaps behind a few common asks.

### Added
- **docs/PROMPTING.md** — the prompt phrasebook: how to word a request to get a
  specific outcome (dockerize a step, pull papers into inputs, build a
  no-leak shareable dashboard, make sample data to test a tool, run long jobs in
  the background) and what Research OS does behind the scenes, with a verify
  step for each. Linked from the README + docs index + USE_CASES + FAQ.
- **Step-scoped Docker.** `sys_env(operation='docker_generate', step_id='NN_slug')`
  now writes `workspace/<step>/environment/Dockerfile` (+ `.dockerignore`) built
  from THAT step's own pinned requirements, with the build context set to the
  step directory — so one analysis step is independently containerizable and
  reproducible, not just the whole project. "Dockerize this step" now actually
  creates the step's Docker artifacts and uses the step's own environment.
- **build/sample_data_and_validation** protocol (tool_build + hybrid) — get data
  to run a tool on: pull a representative real sample OR generate seeded
  synthetic/sample data (with edge cases) when none exists, run the tool
  end-to-end, and validate the output is correct + sensible, feeding failures
  into the evaluate→improve loop. Wired into the router (`build_sample_data`
  sub-intent), boosted in tool_build + hybrid modes, mapped into the per-task
  skill recommendations.

### Improved
- **reproducibility** protocol teaches per-step container generation (snapshot
  then docker_generate with step_id) alongside the project image.
- **deliverable_design** Principle 6 now explicitly covers DIAGRAMS / workflow
  visuals: an audience-facing diagram shows the scientific/conceptual flow, never
  the workspace folder structure (`01_canon → 02_eda`) or filenames. The
  auto-generated workspace DAG is an internal aid, not an audience artefact.
- **USE_CASES / FAQ / TOOL_BUILDER** gained prompt-framing entries + cross-links
  to PROMPTING.md (dockerize a step, test a tool on data / generate sample data,
  "how do I get the AI to do exactly what I want").

---

## [4.3.0] — the daemon watches everything + universal per-task skill-pull (2026-06-28)

A MINOR release. Two themes: the daemon now watches the WHOLE project surface
(not just the numbered-step spine), and skill-pulling became a universal
per-task reflex (not visualization-only). Research-OS stays a guidance system —
the new watches are non-blocking signals the AI self-corrects on mid-prompt.

### Added
- **Whole-project hygiene watch** (`tools/actions/state/project_hygiene.py`),
  wired into `structure_audit` so it reaches the daemon self-check, `sys_boot`,
  and `tool_structure_audit` at once. New by-shape, fail-open findings:
  `step_no_env_snapshot` (a step ran scripts + produced outputs but has no
  per-step environment capture — not independently reproducible/containerizable),
  `step_ungrounded_no_literature` + `literature_corpus_behind` (pull literature
  mid-step; keep the root `literature/` corpus-of-record current),
  `step_context_dir_missing`, `decisions_not_logged`, `state_md_stale`,
  `getting_started_unfilled`, `communication_log_empty`, `glossary_unfilled`.
- **Universal per-task skill-pull.** `recommend_skills()` now takes
  `task_intent` + `protocol` and leads with the capability THIS task needs
  (`viz_build` → scientific-visualization, `paper` → scientific-writing,
  `per_step_grounding` → literature-review + citation-management). `tool_route`
  attaches `recommended_skills` to EVERY successful route (keyed off the
  resolved sub-intent + protocol + project domain + mode), not just a
  fresh-project boot. `science_pack.science_skills_for()` gains a protocol arg;
  `SCIENCE_PACK_BY_PROTOCOL` expanded; new `SUB_INTENT_SKILL_TAGS` keyed to real
  router sub-intents.

### Improved
- **`literature/literature_per_step`** protocol teaches mid-step pulling +
  the root corpus-of-record (references the new daemon codes).
- **`visualization/figure_guidelines`** protocol gains a
  `pull_visualization_skills` block (pull viz skills/best-practice;
  structure-not-design).
- **AGENTS.md / AI_GUIDE / templates/hermes SKILL.md** teach the universal
  reflex (route → read `recommended_skills` → `skill_view` + load → use → keep
  working inside RO) and the whole-project hygiene codes.
- **.gitignore** generator: `scratch/` `logs/` `cache/` are now UNANCHORED so
  the per-step copies (`workspace/<NN>/scratch|logs/`) are ignored too, not just
  the top-level dirs; the doctor's `.gitignore` check accepts both forms.

### Fixed
- De-deprecated `sys_env_snapshot` → `sys_env(operation='snapshot', ...)` across
  user-facing warnings and the env seed READMEs; added per-step
  reproducibility/containerization framing to the environment seed.

---

## [4.2.1] — documentation overhaul (2026-06-27)

A PATCH release: documentation only, no code or behavior changes. The docs were
rewritten with fresh context to be user-first, realistic, and accurate to the
real tools, protocols, and CLI.

### Improved
- **SETUP_PROMPT.md** rewritten as a fill-in template (`[project name]`,
  `[goal]`, `[context]`, `[hypotheses]`, `[mode]`, `[autonomy]`, `[editor]`, …)
  whose ordered steps drive the real onboarding process (install → scaffold →
  MCP path fix → daemon → restart → self-test → onboard with literature
  grounding → Hermes skill pull) before any analysis.
- **SCENARIOS.md** rewritten as two end-to-end worked projects: a basic one and
  a deep PI-level program that exercises nearly every capability — onboarding,
  literature grounding, iterative phased planning, branching + deleting steps,
  synthesis meetings, a live public dashboard, Docker/SLURM runs, provenance,
  image + folder sharing, and a cross-actor handoff (no premature paper).
- **README.md** restructured to lead with the Hermes/skills layer and autonomous
  3-source skill retrieval; fixed `init .` (non-nesting) and structure-not-design
  framing for deliverables.
- **HOW_IT_WORKS.md** gained a section on long/Docker/SLURM runs and sharing.
- **START, USE_CASES, FAQ, TOOL_BUILDER, DAEMON, SHARING** rewritten with fresh
  context — clearer, realistic, and verified against the live tool/protocol/CLI
  registry. FAQ gains a Trust & provenance section; TOOL_BUILDER brought to
  analysis-mode depth (architecture diagram, implement loop, pipelines, eval
  provenance); DAEMON and SHARING document container runs and stage handoff.

---

## [4.2.0] — containerized jobs, pipelines, supervision & mode parity (2026-06-27)

A MINOR release driven by user reports from Argonne-style HPC researchers:
run long reproducible jobs (including Docker) through the daemon, organize
pipeline-shaped tools properly, supervise many projects at once, and bring
tool_build / hybrid modes up toward analysis-mode depth — all while keeping
the protocol layer a reasoning scaffold (STRUCTURE, not design or content).

### Added
- **Docker/Podman jobs through the daemon.** `DockerRunner` + `Daemon.run_container()`
  + `research-os daemon docker IMAGE -- CMD` (`--gpus`/`--network`/`--input`): run a
  long, reproducible job inside a container image as a tracked job — journaled,
  artifact-captured, stall-watched, and pinned to the image's content digest so it
  is recreatable bit-for-bit. Works for Docker, Podman, and (via wrapper/SLURM)
  Kubernetes/HPC. Native conda runs and SLURM submit are unchanged.
- **Shared-server daemon setup.** `research-os daemon setup [--start]` + `daemon start
  --background`: auto-pick a free port, detect the conda env + absolute executable,
  print/launch a no-Docker/systemd-free detached run — for multi-user HPC login nodes.
- **Multi-root PI supervision.** The periodic self-check tick now refreshes every
  registered project; `run_self_check_all()` + `GET /v1/supervision` give a roll-up of
  health across all of a PI's projects.
- **Background-job reproducibility.** Tracked SLURM/container jobs capture a full
  environment snapshot (complete installed-package manifest, not just the env name);
  a stall watcher flags a RUNNING job whose log stopped advancing.
- **Constant daemon→AI feedback loop.** `server/daemon_alert.py` surfaces a
  `daemon_flagged_issue` on every tool call when the daemon's self-check finds a new
  problem; persistent BLOCK findings escalate to the researcher.
- **Mode-aware daemon watch.** `mode_health.py` adds per-mode health signals (tool_build
  eval/spec/decisions, notebook freshness, multi_study codebook + roll-up staleness,
  exploration unpromoted probes, hybrid tool tests) wired into the shared structure-audit
  engine so daemon self-check, sys_boot, and tool_structure_audit agree.
- **New protocols (reasoning scaffolds):** `build/pipeline_construction` (organize a
  multi-stage pipeline tool by stages + I/O contracts; running it is a tracked run, not
  a numbered step), `program/pipeline_stage_handoff` (hand a stage's output + a consumer
  contract to the next actor).
- **Tool architecture diagrams + provenance diagrams.** `spec_and_design` gains an
  `architecture_map` step + `spec/architecture.md`; the run-lineage DAG renders as a
  mermaid provenance diagram (`lineage_to_mermaid()` + `GET /v1/lineage.mermaid`).
- **3-source skill layer + self-improvement loop.** Active skill-pulling from Nous Hermes
  + K-Dense scientific-agent-skills + native Agent Skills; `research-os skills
  add-science-pack | list-science`; `promote_skills` writes loadable Hermes skill cards.
- **Universal setup prompt** (`docs/SETUP_PROMPT.md`) and `docs/HOW_IT_WORKS.md`.

### Improved
- Provenance integrity verifier (re-hash recorded inputs/outputs) wired into the daemon
  watch, `tool_audit`, and step-complete; eval results now require a recorded conditions
  sidecar; the tool README must carry the architecture diagram and is reconciled on release.
- Protocols point the AI at the new daemon/skill/supervision surfaces (autopilot,
  session_boot, program_setup, reproducibility) without becoming prescriptive.
- Per-turn quality watchers (ungrounded synthesis, conclusions-without-audit, stuck loop)
  and a proactive next-action hint at the dispatch backstop.

### Fixed
- Setup UX: `--ide none` no longer wires IDEs; `ide add` prints a restart notice; a second
  project's daemon auto-probes a free port instead of failing silently; `init --name`
  warns on silent nesting; several stale doc counts.

---

## [4.1.0] — self-correction, easier setup, per-project daemon control (2026-06-26)

A MINOR release driven by user reports: make the AI follow Research OS reliably
(and recover when it doesn't), make first-time setup robust, and tighten what
gets committed. Backward-compatible — no tools or protocols removed.

### Added
- **Mid-prompt off-protocol self-correction.** If the AI writes step content
  (`workspace/NN_*/…`, a `conclusions.md`, `synthesis/…`) without routing the
  ask or opening a step, the very next tool envelope now carries a
  **non-blocking** `off_protocol_freelancing` finding + a `tool_route(...)`
  `next_recommended_call`. The AI sees it the same turn and corrects without
  being hard-stopped. New `server/drift_detect.py` reads `.os_state` by shape,
  so it works **with or without a daemon** (stdio users included), is debounced
  so it never nags, and never triggers on scratch/inputs/logs writes. The
  per-IDE rules + AI_GUIDE now tell the AI to act on it.
- **Per-project `research-os daemon stop`.** Gracefully stops *this* project's
  daemon (via its `.os_state/daemon.json` descriptor) and preserves
  `.os_state/runs/`, so per-project start/stop round-trips and resumes where it
  left off.

### Fixed
- **`.gitignore` now excludes the whole `.os_state/` tree and `workspace/logs/`.**
  The generator previously ignored only `.os_state/` *subdirs* and
  `workspace/cache/scratch`, so machine-local run history and per-run audit /
  override logs were being committed into user repos. The `doctor` check is
  hardened to require both as standalone lines.

### Improved
- **Onboarding-first, realistic docs.** README adds a "most robust setup" path
  (onboarding + the setup prompt + the Hermes layer) and tones down the
  "honest enough to publish" overclaim to a realistic traceable/grounded/
  reproducible framing. START.md's setup prompt now (a) demands a session
  RESTART after `init` and waits for confirmation, (b) adds an "onboard before
  producing work" step (scan inputs → frame question → pick mode → config →
  then first step), (c) recommends the Hermes layer and tells Hermes to read
  the intake + pull relevant skills on the first setup turn, and (d) lists the
  actual CLI subcommands (was a stale "seven subcommands").

---

## [4.0.3] — script-naming enforcement, setup UX, gate hardening (2026-06-26)

A PATCH release driven by user reports + a third audit pass. Focus: make the
analysis-step script-naming convention impossible to silently drift, fix a
setup-UX footgun, and close four security/integrity bugs. No tools or protocols
removed; existing projects upgrade transparently.

### Added
- **Script-naming convention is now enforced AND watched.** Analysis scripts
  must be named `<NN>[a-z]_<snake_name>_v<k>.<ext>` (with `<NN>` = the step's own
  number). A new validator powers three enforcement points: the daemon's
  structure watch (`run_self_check` / `sys_boot` flag a `script_naming` finding
  with the exact rename), `tool_step_complete` (completeness warning), and a new
  explicit gate `tool_audit(scope='step', dimension='script_naming')`. Helper
  modules (`utils.py`, `__init__.py`, `lib_*`, `_*`) are exempt. So a mis-named
  `scripts/` folder gets caught early instead of leaving a step un-navigable.

### Fixed
- **Setup no longer wires every IDE.** `research-os init` defaulted to `--ide
  all`, so an AI told to "set up this project" littered it with config for
  editors the user doesn't have. The default is now `--ide auto`: it detects the
  user's single IDE from the environment, and if unsure wires **nothing** and
  says how to pick one + that a restart is required. The README gained a
  fill-in-the-blank AI setup prompt (one IDE, MCP + daemon, restart), and the
  `agent_setup` protocol now forbids `--ide all` and tells the AI to wait for the
  session restart.
- **Paid-tool consent gate bypass (money/safety).** The declared-gate path
  matched `source` case-sensitively, so `source="PAID"` skipped the paid-tool
  consent gate while `"paid"` fired it. Matching is now case-insensitive.
- **Floor gates fail-safe on a corrupt config.** A corrupt
  `researcher_config.yaml` made the autonomy level read as `supervised`, silently
  stripping every floor gate. A present-but-unreadable config now fails to
  `adaptive` (gates still apply); only a truly absent config opts out.
- **Iteration history no longer silently wiped.** A corrupt `iterations.yaml` was
  treated as empty, so the next iteration overwrote it and lost prior history.
  The corrupt file is now backed up (`.corrupt-<ts>`) before a fresh ledger.
- **Recurring-deliverable label collisions.** Non-ASCII labels (e.g. `研究`,
  `🎉`) all slugged to one `deliverable/` folder, silently colliding distinct
  events. Empty slugs now get a stable hash suffix.

---

## [4.0.2] — daemon crash-recovery hardening + robustness pass (2026-06-26)

A PATCH release: a second deep audit (daemon, runtime, and protocol/router
investigators) closed four daemon crash-recovery BLOCK/MAJOR bugs, a
wide str-root crash class, and several routing/robustness gaps. No tools,
protocols, or input schemas changed — existing projects upgrade transparently.

### Fixed
- **Paused runs survive restart (BLOCK).** A `paused` run was treated as a crash
  orphan and silently rewritten to `interrupted` on daemon restart, losing the
  user's pause. `detect_orphans` now treats paused as terminal-for-recovery.
- **Terminal-event idempotency (MAJOR).** A duplicate/replayed terminal event
  double-appended a transition and double-fired the autonomous-continuation hook
  (spending compute/tokens twice). Added a terminal-once guard.
- **Scheduler runs resume on the scheduler (BLOCK).** A SLURM/HPC run was
  resumed as a local subprocess on the daemon/login node. `resume_run` now
  branches on kind/scheduler and re-dispatches via `submit_job` (sbatch).
- **No duplicate of a live run (BLOCK).** The run manifest now records the child
  PID + host; `resume_run` refuses to re-spawn while the original process is
  still alive (was previously able to launch a concurrent duplicate).
- **Journal pump no longer head-of-line blocks (MAJOR).** The `on_terminal` hook
  (which may run a continuation for up to `continue_timeout` seconds) ran inline
  on the single journal pump thread, stalling journaling of every other run. It
  now runs on a separate thread; the fast staleness refresh stays inline.
- **str-root crash class (wide).** ~45 action functions did `root / "..."`
  without coercing; the daemon gateway passed `daemon.root` un-coerced, so a str
  root crashed them. `_handle_tool_call` (and `Daemon.__init__`) now coerce root
  to `Path` at the boundary — protects all tools regardless of caller.
- **Phantom decomposition tools (HIGH).** `build/integration_spike` named two
  tools that don't exist (`sys_env_snapshot`, `tool_scratch_run`) → `sys_env`,
  `tool_scratch`. Added a preflight guard so a phantom decomposition/shortcut
  tool name now fails preflight.
- **Cleaner malformed-input errors.** `tool_route` (non-str prompt) and
  `tool_audit` (non-str scope/dimension) return typed envelopes instead of
  leaking internal exception text.
- **`?root=` reads work (F-7).** `GET /v1/lineage|staleness|rebuild?root=<X>` now
  constructs a RunStore for the override root instead of always returning
  `available:false`.

### Improved
- **Routing.** "directed acyclic graph" now reaches causal inference (not
  network-viz); added trigger variants for autonomous-roadmap, fork-alternative,
  and probe-promotion prompts that previously dead-ended.

---

## [4.0.1] — post-release consistency & accuracy pass (2026-06-26)

A PATCH release: a deep post-4.0.0 audit (multi-persona stress test +
reviewer pass) closed one real data-integrity bug, several silent
fail-opens, and a layer of stale guidance. No tools, protocols, or input
schemas changed — existing projects upgrade transparently.

### Fixed
- **Audit-ledger swallow (data integrity).** `claim_grounding` kept the same
  silent `except: pass` around its structured-findings write that the 4.0.0
  F2.1 sweep fixed in its two siblings — it was missed. A failed write silently
  emptied the ledger that `findings_query` / `active_gates` depend on. Now
  logged.
- **Fail-open gates now log instead of vanishing.** The protocol completeness
  gate (a silently fail-open gate hides a real missing output) and the
  citation-key reader (a swallowed read FALSELY flags a real citation as
  undefined) now warn so the wrong verdict is diagnosable.
- **Cross-deliverable audit sees recurring artifacts.** The consistency audit
  now discovers `synthesis/deliverables/<event>/` deliverables (keyed
  `<kind>@<event>`), not just flat single-file ones — closes a fail-quiet where
  a poster + paper weren't cross-checked.
- **Override accountability.** `tool_step_complete`'s literature/grounding
  overrides now journal to `override_log.md` (they were applied but never
  logged, so the bypass was invisible to the pre-submission audit). Extracted a
  single `enforce_override()` helper (the sequence was copy-pasted across gate
  handlers and had drifted). `audit_step_literature` tolerates a str root.

### Improved
- **AI/user guidance caught up to the 4.0.0 way.** The modes help topic,
  RESEARCHER_GUIDE, TOOL_BUILDER, AGENTS.md, and AI_GUIDE now teach
  `sys_workspace_mode` transitions (not the superseded config edit that the
  structure audit flags as drift), recurring deliverables
  (`synthesis/deliverables/<event>/`), the daemon compliance watchdog, and
  external-data copy/symlink intake. AGENTS.md lists all six modes.
- **Accurate self-description.** Dropped the stale "skeleton / Phase N / does
  NOT serve anything yet / OPEN decision" framing from the daemon docstrings and
  the CLI `daemon` help (which had told users `daemon start` "is not serving
  yet" — it fully serves).

---

## [4.0.0] — the resilient, autonomous, self-organizing daemon (2026-06-25)

A MAJOR release. The daemon graduates from an execution helper into a
true enforcement + execution + notification **kernel**, and the whole
system gains the machinery for long, hard, unattended, autonomous
research on shared infrastructure — while staying fully functional with
**no daemon and no Hermes** (stdio users and bare clients are unaffected).
Additive: no tools or protocols were removed and no input schemas changed,
so existing projects keep working untouched.

The throughline is unchanged — turn soft, trusted prose into hard,
verified structure — extended now to *time* (long jobs), *scale*
(multi-gig compute), *autonomy* (goal loops), and *chaos* (existing
messy projects).

### Added — safe large-scale + long-running execution
- **Dynamic resource budgets** (`daemon/dynamic_limits.py`): a run's memory
  ceiling is now the minimum of (declared cap, requested size, live free-RAM
  headroom). A multi-gig batch runs big on an idle node and automatically
  backs off on a busy shared one — never starving other users, never
  exceeding the researcher's declared cap. psutil fast-path, `/proc`
  fallback, fail-open. Tunable via `runtime.dynamic_resources`.
- **Resumable runs** (`Daemon.resume_run`, `POST /v1/runs/{id}/resume`): a
  long job stopped part-way (reboot, disconnect) resumes from its recorded
  spec; checkpoint-aware programs continue via `RO_RESUME` /
  `RO_CHECKPOINT_DIR`, others restart cleanly. Always safe, seamless for
  opt-in jobs.
- **Failed background runs are now reported as failed** (were silently
  reported as succeeded when the command exited nonzero).

### Added — autonomy + judgement
- **Autonomous continuation** (opt-in, `daemon/continuation.py`): after a
  long result lands, the daemon can re-prompt the researcher's agent
  (Hermes / any) to continue toward a goal — hop-limited so a goal can never
  loop forever, never bypassing consent/staleness gates. Off unless
  `daemon.continue_command` is set.
- **Audit-judge scoring** (`tool_judge_score`): a durable, structured
  scorecard the AI authors (dimensions 0-5 + justifications + limitations +
  improvements + verdict ship/iterate/redo); the loop reads the verdict to
  decide continue-vs-stop. The tool validates the shape; the brain judges.

### Added — order the chaos (migration + integrity)
- **Chaos → Research-OS migration** (`tool_migrate_audit`,
  `tool_migrate_apply`, protocol `guidance/organize_existing_project`):
  audit an existing messy folder, see how each file maps into RO format,
  then COPY it in safely — the original is never moved or deleted, every
  copy is verified, collisions are skipped, an auditable manifest is written.
- **Structure-integrity audit** (`tool_structure_audit`): verify an RO
  project is sound — steps well-formed, state ledger ⇆ disk aligned, no
  orphaned outputs — with severity-tagged findings.
- **Daemon startup self-check** (`daemon/health_notes.py`): on boot the
  daemon inspects the project and writes AI-facing notes
  (`.os_state/daemon_notes.md`) that `sys_boot` surfaces by-shape, so
  structure problems / interrupted runs / unframed intake get addressed
  before work builds on them — and nothing is lost across sessions.

### Added — planning, tool-building, polyglot research
- **Deep iterative planning**: `methodology/deep_planning` (build a
  rigorous, branchable roadmap), `guidance/roadmap_execution` (the
  autonomous build loop that re-plans from evidence), `guidance/analysis_paths`
  (keep multi-path exploration legible). Docs: `DEEP_PLANNING.md`.
- **Tool-build power features**: `build/tool_from_description` (describe →
  plan → build → improve-from-results loop), `build/optimal_approach`
  (brain out the approach before committing), `build/versioning_and_rollback`
  (version + roll back by eval verdict). `tool_git` gained a `restore`
  operation for safe, non-destructive rollback to a blessed version.
- **Polyglot + notebook research**: `methodology/polyglot_analysis` (choose
  the right language — R / Julia / bash / SQL / Python — by reasoning, not
  reflex), and strengthened notebook protocols (cell-as-unit discipline,
  restart-and-run-all reproducibility, every number traced to code).

### Added — best-setup guidance
- **`docs/BEST_SETUP.md`** + an `agent_setup` step on stacking complementary
  MCP servers (e.g. context7 for live docs) alongside RO. Hermes SKILL.md
  gained a disciplined autonomous-loop section and a project-based
  self-improvement loop.

### Improved
- **Walk-away safety**: interrupted runs are surfaced in `orient` and paged
  to the away researcher; daemon-enforced gate blocks page the away user
  (deduped); the shared-server resource floor is now genuinely enforced on
  the primary run path.

### Notes
- `tool_sql_exec` is documented as a future enhancement
  (`docs/TOOL_BACKLOG.md`); SQL runs via the Python/R path today.

### Hardened — consistency pass (stress-test + reviewer-driven)
A deep multi-persona stress test and a reviewer consistency pass closed the
gaps that separate "builds" from "robust":
- **Shared-server safety hole closed**: the agent's direct code-execution tools
  (R/Julia/bash scripts, notebooks, sensitivity sweeps, step pipelines) now
  apply the resource budget as real rlimits (sized to live free headroom),
  matching the daemon path — a runaway script can no longer OOM other users.
- **Completion is enforced**: logging a protocol `completed` verifies its
  declared outputs exist (override-able with a logged rationale).
- **First-class mode transitions** (`sys_workspace_mode`): exploration→analysis,
  analysis→hybrid/multi_study, etc. are now additive, recorded operations that
  create the target surface and sync config+state — no more silent half-change.
  `structure_audit` + the daemon catch mode drift.
- **Autonomous loop**: continuation start/stop/status endpoints; the audit-judge
  is wired into roadmap execution; `deep_planning` hands off to the verified
  loop and offers Hermes orchestration.
- **Daemon as watchdog**: crash recovery is per-record fault-isolated; the daemon
  self-check flags repeated protocol failure / abandonment so a stuck AI
  self-corrects or the researcher is paged.
- **External-data intake**: `project_startup` reasons copy-vs-symlink and brings
  data into `inputs/raw_data/` with provenance.
- **Recurring deliverables**: posters/decks/updates for meetings route to
  documented `synthesis/deliverables/<event>/` folders instead of overwriting.
- **Findings ledger reliability**: silent audit-ledger write failures are now
  logged; a drift guard keeps protocol gate references in sync with the
  dispatcher.
- **Data-location + docs consistency**: purged legacy per-step `data/{input,
  output}` names across 13 protocols (canonical `next_step_output`/
  `past_step_input`); dropped internal planning framing from design docs;
  fill-in-the-blank start prompts per mode; deep daemon-inclusive scenarios.

---

## [3.12.0] — workspace mode parity + the borrow-it-or-build-it arc (2026-06-23)

A MINOR release. Additive and backwards-compatible — no tools or
protocols removed, no input schemas changed. Existing projects keep
working untouched; new structure simply appears.

The theme is **design depth for every workspace mode, not just
analysis.** Until now `analysis` mode carried a full reasoning
scaffold (plan → run → synthesize) while `notebook`, `multi_study`,
`hybrid`, and `tool_build` leaned on a single generic protocol each.
This release brings the non-analysis modes up to the same standard,
and adds a dedicated research-engineering arc for adopting external
methods, papers, and libraries the right way.

### Added

- **Notebook mode lifecycle (3 protocols)** — `notebook_reproduce`,
  `notebook_promote`, `notebook_synthesize`: reproduce a notebook
  cleanly, graduate a notebook cell into a real analysis step, and
  synthesize findings across notebooks.
- **Multi-study / program mode (3 protocols)** — `study_register`,
  `cross_study_synthesis`, `codebook_governance`: register a study
  into a program, synthesize across studies without double-counting,
  and govern the shared codebook.
- **Hybrid mode (2 protocols)** — `hybrid_workflow` (the home loop
  for projects that are BOTH a tool and the research done with it)
  and `tool_to_analysis_handoff` (the pivot between building and
  using).
- **The "borrow it or build it" arc (3 protocols)** —
  `method_scouting` → `integration_spike` → `dependency_integration`:
  scout external methods / papers / code for a capability gap, prove
  a candidate works in a throwaway spike (with the exact version
  pinned, the environment snapshotted, and the test input hashed
  before any decision), then promote only what cleared the bar into
  the real build behind a seam — with provenance carried forward, a
  version-change re-proof policy, and a rollback checkpoint at the
  integration boundary.
- **`package_and_publish`** — the distribution step that closes the
  build arc (decide registry → complete metadata + licence → verify a
  clean-environment install → gate the irreversible publish).
- **`hybrid` is now a first-class routing mode** with its own
  `MODE_ROUTING` entry, biasing its native sub-intents instead of
  falling through to the neutral analysis baseline.

### Improved

- Hybrid workspace layout now scaffolds a lazy inner `tool/` repo
  home so the tool half and the analysis half have clear places to
  live.
- `sys_help` modes topic + routing-effect copy rewritten so every
  mode's bias is described accurately (only `analysis` is the neutral
  baseline now).
- Build protocols are cross-linked into the integration arc:
  `spec_and_design`, `implement_iteration`, and `hybrid_workflow` all
  branch into `method_scouting` when a capability gap should be
  scouted rather than reinvented.

### Bumped

- Router index `version: 36 → 37`; embeddings + route sidecar rebuilt
  (178 protocols).

---

## [3.11.1] — documentation accuracy + worked-scenarios pass (2026-06-22)

A PATCH release. Docs-only — no code, tool, or protocol behaviour
changed. The whole `docs/` tree and the README were audited against the
live registry, protocol catalogue, and CLI, corrected wherever they had
drifted, and substantially enriched with realistic end-to-end examples.

### Added

- **`docs/SCENARIOS.md`** — a new doc with seven complete, realistic,
  end-to-end worked examples: a grad student turning a messy sensor CSV
  into a paper + poster; a postdoc reproducing a published bioinformatics
  result and finding it normalization-sensitive; a PI assembling an NIH
  R01 from finished work; an engineer benchmarking their own Rust tool in
  `tool_build` mode; a qualitative researcher taking 18 interview
  transcripts to a publishable paper + dashboard; bringing a
  half-finished project into Research OS mid-stream; and a quick
  one-figure job. Each names a researcher, shows the data on disk, the
  exact prompts typed, the protocols that fire, and what lands in
  `synthesis/`. Every protocol, tool, CLI flag, and protocol step
  referenced was verified against the live registry. Linked from the
  README, the docs index, USE_CASES, START, RESEARCHER_GUIDE, and FAQ.

### Improved

- **`docs/FAQ.md`** — replaced the stale v2.0.0-retrospective lead-in
  (which greeted every reader of a 3.11.x product with a two-year-old
  migration note) with a topic-grouped "common questions" entry point +
  jump links. The v2.0.0 detail was preserved verbatim under a clearly
  labelled "Version history (in depth)" section.

### Fixed

- **`docs/FAQ.md`** — the "add a custom MCP tool" answer pointed at the
  long-removed monolithic `src/research_os/server.py`; corrected to the
  split `server/tool_definitions/*.py` + `server/handlers/*.py` layout.
- **Cross-doc links** — fixed three broken/stale internal anchors
  (`PROTOCOLS.md → TOOLS.md` theory-pack section that no longer exists;
  `README.md → RESEARCHER_GUIDE.md` config section that renumbered from
  §9 to §8) and verified zero broken links across the whole `docs/` tree
  + README.
- **`docs/TOOLS.md`** — added the 8 live tools that had no entry
  (`tool_build`, `tool_git`, `tool_deliverable_chooser`, `tool_explain`,
  `tool_finalize_project`, `tool_skills`, and the `wet_lab` pack's
  `tool_wet_lab_checksum_raw` + `tool_wet_lab_run_log_init`). The doc
  now covers all 152 live tools with zero stale entries (verified by a
  cross-reference against `TOOL_DEFINITIONS`).
- **`docs/PROTOCOLS.md`** — corrected the header from "100+ protocols /
  nine categories" to the accurate **130+ protocols across thirteen
  categories**, and regenerated the auto-catalogue block via
  `scripts/regen_protocols_doc.py` so per-category counts (methodology
  44, synthesis 22) and the previously-undocumented `build`,
  `exploration`, `notebook`, and `program` categories are all present.
- **`docs/CLI.md`** — the top command table listed only 7 of the 10
  real subcommands; added `hermes`, `route`, and `refresh`, rewrote the
  intro, and added a full `research-os refresh` reference section.
- **`docs/START.md`** — fixed both "seven commands" references to the
  accurate ten, and added the missing `hermes` / `route` / `refresh`
  examples to the cheatsheet.
- **`docs/AI_GUIDE.md`** — corrected the protocol-categories heading
  ("100+ protocols, organised in 9" → "130+ protocols") and added the
  `build`, `exploration`, `notebook`, and `program` router intent
  classes to the category table, with a pointer to `PROTOCOLS.md` for
  the authoritative folder roster.
- Verified zero broken internal doc links, README Python badge matches
  the packaging classifiers (3.10 / 3.11 / 3.12), and the README IDE
  list matches the wizard's supported targets.

---

## [3.11.0] — step report adoption (2026-06-22)

A MINOR release that makes the **step report** (added in 3.10.0)
discoverable and frictionless. Fully backward-compatible — every new
behaviour is additive guidance the AI may act on, never a hard step.

### Added

- **Deliverable chooser surfaces step reports.** `deliverable_chooser`
  now returns an `interim_artifacts` list alongside the gated
  final-deliverable recommendations. A step report is offered there
  (never in `research_goal.output_types` — it isn't a scope commitment)
  once at least one step has conclusions worth presenting. Pure read of
  the existing on-disk counts; nothing forced.
- **End-of-step nudge.** `finalize_path` now returns a
  `step_report_nudge`. When a step has substantive conclusions AND at
  least one figure, it suggests a step report with the exact
  `tool_synthesis_scaffold(kind='step_report', step=…)` call and an
  explicit "offer it, don't auto-build — ask first" instruction. Stays
  silent when the step isn't presentation-ready.
- **Figure staging.** Scaffolding a step report now stages that step's
  figures into `synthesis/updates/figures/` (new `stage_step_figures`
  helper), flags the focal figure, and reports the relative
  `figures/…` paths so the page travels as one self-contained file with
  no `workspace/` references. Steps with no figures are handled
  gracefully — the report can still be authored.

### Improved

- **Updates index polish.** The auto-generated
  `synthesis/updates/index.html` diary now shows a per-entry date (from
  file mtime) and a one-line headline (the report's first paragraph,
  truncated), so it reads as a real changelog rather than a bare link
  list. Still navigation-only, still offline-safe, still derived purely
  from disk.
- **Protocol doctrine.** `docs/PROTOCOL_DOCTRINE.md` now cites
  `synthesis_step_report` as the canonical **guidance-first** protocol
  (no `required_structure`/archetype menu) contrasted against
  `synthesis_dashboard`'s deliberate prescription — a reference example
  for future protocol authors.

### Bumped

- Version → 3.11.0 across `pyproject.toml`, `__init__.py`,
  `CITATION.cff`; `synthesis_step_report.yaml` protocol version → 3.11.0
  (behaviour changed: figure staging + nudge + index).

---

## [3.10.0] — step reports (2026-06-22)

A MINOR release adding a new synthesis deliverable: the **step report** —
a single self-contained, presentation-grade HTML page about ONE analysis
step, the kind you screen-share in a meeting or attach to a milestone
email. Fully backward-compatible — nothing changes for existing
deliverables.

### Added
- **`synthesis/synthesis_step_report` protocol** — guidance-first (no
  mandated section list): the AI designs the page each step deserves. The
  protocol carries `design_principles` + `quality_standards` (the
  honesty / grounding / accessibility bar) instead of a rigid
  `required_structure`. Routed via new triggers ("step report", "visual
  for this step", "show this step at the meeting", …).
- **`tool_synthesis_scaffold` `kind="step_report"`** — seeds a MINIMAL
  shell only (Research-OS palette tokens + accessibility baseline +
  offline guarantee + an author brief in comments). No fixed sections,
  no status pills, no archetype menu — the AI composes the layout
  freely. Files land in `synthesis/updates/step-NN-<slug>.html`, folding
  in the real workspace step name so the diary sorts chronologically.
- **`synthesis/updates/index.html` diary index** — auto-regenerated on
  every step-report write (`rebuild_updates_index`). Navigation only:
  derived purely from disk, makes no claims, embeds nothing, works
  offline.

### Improved
- **`synthesis/synthesis_progress_update`** now points at the step report
  as its visual companion: when an update is really about one step, the
  right attachment is a step report (linked), not a loose figure inlined
  into the prose.

### Validated
- New `_check_step_report` gate enforces the trust invariants
  (authored-at-all, no left-in author brief, offline/self-contained, alt
  text on every image, no placeholders, emailable bundle size) and
  **never** a heading list — "Step NN" headings and single-step focus are
  expected, not penalised. `_file_kind` reads the whole file to detect the
  `data-archetype="step-report"` stamp (it sits ~9KB in, past any head
  slice). 13 new tests (`tests/unit/test_step_report.py` +
  router resolution).

---

## [3.9.0] — canonical project layout (2026-06-22)

A MINOR release that makes the project directory layout a single source of
truth and documents it in one place. Fully backward-compatible — the
folders an existing project gets at `init` are byte-identical to before.

### Added
- **`docs/PROJECT_LAYOUT.md`** — the canonical reference for the project
  directory layout: the mode-agnostic safety backbone (`.os_state`,
  `inputs/`, `workspace/`, `environment`, …) plus what each workspace mode
  adds on top. Wired into the docs index. This is the single doc to read
  for "what lives where."
- **`LAYOUT_SPEC`** + **`describe_layout(mode)`** in `project_ops` — a
  declarative layout definition and a render helper, so docs / `sys_boot` /
  the wizard can describe the directory contract without re-listing folder
  names inline.

### Improved
- The per-mode directory layout was hand-duplicated across six profiles —
  every mode restated the same ~7 safety dirs, so the contract was
  *implicit* and could silently drift. It is now **declared once** in
  `LAYOUT_SPEC` and composed (`_compose_layout`); `SCAFFOLD_PROFILES` and
  the back-compat constants (`TOP_LEVEL_DIRS` / `EAGER_DIRS` / `LAZY_DIRS`)
  derive from it. ~190 lines of duplicated tuples removed; the safety
  backbone can no longer drift between modes.

### Fixed
- (none)

### Bumped
- Version → 3.9.0.

---

## [3.8.0] — adaptive-primary autonomy gates (2026-06-22)

A MINOR release that makes the **adaptive** autonomy mode visibly primary
across the protocol catalogue and tightens every autonomy gate. No behaviour
changes — same modes, same tools, same floors — just a clearer, leaner gate
idiom plus better protocol connectivity.

### Improved

- **Autonomy gates collapsed to two behaviour lines.** Every `AUTONOMY GATE`
  block used to spell out four modes (`adaptive (default) →`, `manual /
  supervised →`, `autopilot →`), restating the proceed-path twice because
  adaptive and autopilot almost always said the same thing. All 28 well-formed
  gate blocks now lead with a single primary line —
  `proceed (adaptive default, autopilot) →` — followed by
  `confirm first (manual / supervised) →`. This makes adaptive the obvious
  default instead of one of four co-equal options, and trims ~40% of each
  gate's prose.
- **Autopilot nuance preserved inline.** In the three blocks where autopilot
  legitimately bypassed a confirm-floor that adaptive honours
  (`build/spec_and_design`, `build/test_strategy`,
  `build/release_and_changelog`), that deviation is kept as a parenthetical
  "(Under autopilot, …)" clause rather than dropped — no floor is lost in the
  collapse.
- **Protocol connectivity.** Linked the two genuinely orphaned guidance
  protocols: `glossary_update` now `see_also` writing_core + analysis_plan;
  `hypothesis_tracking` now `see_also` analysis_plan + research_design +
  synthesis_paper. (The rest of the catalogue already resolved cleanly —
  preflight's `check_routing_targets_resolve` continues to guard against
  dangling `see_also` / `next_protocol` pointers.)

### Added

- `tests/unit/test_gate_idiom_collapsed.py` — locks the collapsed gate idiom
  catalogue-wide (no verbose four-mode lines survive, every proceed-line has a
  matching confirm-line, autopilot nuance preserved in the three special
  blocks).

### Bumped

- Version → 3.8.0 (`pyproject.toml`, `__init__.py`, `CITATION.cff`).
- `version:` field on the 20 touched protocol YAMLs → 3.8.0.

---

## [3.7.0] — first-class workspace modes (2026-06-22)

A MINOR release that makes the workspace **mode** axis coherent and
discoverable. Research OS already supported six modes (`analysis`,
`hybrid`, `tool_build`, `exploration`, `notebook`, `multi_study`), but
routing only biased toward two of them and the mode system was scattered
across the router as hardcoded `if/elif` branches with no single source
of truth — and it was invisible from `sys_help`. This release unifies
the mode routing into one registry, promotes `notebook` and
`multi_study` to first-class routing citizens, and surfaces the whole
axis through help. Mode names, the config enum, and every tool signature
are unchanged, so this is backwards-compatible.

### Added
- **`sys_help(topic='modes')`** — the workspace-mode axis is now
  discoverable from help (aliases: `mode`, `workspace_mode`). It returns
  what mode is, the registered-mode enum (sourced from config so it
  can't drift), a one-line role per mode, how to set it, and how routing
  bias differs per mode. Closes the gap where the AI learned modes
  existed only by reading `config.py`.
- **`MODE_ROUTING` registry** in `tools/actions/router.py` — one table
  mapping each mode to its native sub-intents, boost weight, and whether
  it overrides the semantic router. Every mode-aware code path now reads
  from this single source of truth instead of duplicated constants.

### Improved
- **`notebook` and `multi_study` are now first-class routing modes.**
  They each boost their native sub-intents (`notebook_run` /
  `program_setup`) in `tool_route`, matching the bias `tool_build` and
  `exploration` already had. Previously they only got the weaker
  indirect workflow-shape tiebreak, so build-shaped and analysis-shaped
  prompts could out-rank a notebook/program protocol in those modes.
- **The mode-override (semantic-deferral) path generalised** from
  `tool_build`-only to any mode flagged `override=True` in the registry,
  driven by the registry's per-mode native sub-intents.
- **The wizard re-exports `VALID_WORKSPACE_MODES` from config** instead
  of keeping its own copy, so the init mode menu can never offer a mode
  the config layer would reject (drift guard).

### Fixed
- `sys_help(topic='gates')` descriptions for the `power` and
  `assumptions` gates were stale after v3.6.0 (they still described the
  removed statsmodels/scipy compute behaviour). They now correctly
  describe the verify-recorded gates.

---

## [3.6.0] — audit gates verify recorded work, they don't compute it (2026-06-22)

A MINOR release that removes the last place a Research-OS tool did the
researcher's science. The `power` and `assumptions` audit gates used to
run statistical computations themselves (statsmodels power solve;
scipy/statsmodels Shapiro-Wilk, Levene, Breusch-Pagan, Durbin-Watson,
VIF, Cook's distance) and decide the verdict. They now follow the
`audit_citations` pattern: the AI runs the diagnostics in its own code
and records them; the gate only **verifies the work was done and
written down**. Tool names and the `(scope, dimension)` surface are
unchanged, so this is backwards-compatible.

### Changed
- **`tool_audit(scope='step', dimension='power')` verifies a recorded
  justification instead of solving for power.** It reads your power /
  sample-size file and confirms it records the test family, the effect
  size **and its source** (a bare effect size with no pilot / prior /
  SESOI is flagged), alpha, n, and the target power with a conclusion.
  Returns `recorded` / `missing`; it never computes a power figure.
- **`tool_audit(scope='step', dimension='assumptions')` verifies a
  recorded diagnostics record instead of running the tests.** It reads
  your diagnostics file and confirms each named assumption check has a
  statistic, an interpretation, and — for any violation — a recorded
  response (robust SEs, a different test, a transform, …). Returns
  `recorded` / `incomplete`; it never computes a p-value.
- The legacy numeric kwargs on the power gate (`effect_size`, `alpha`,
  `n`, `test`, `k_groups`) are now accepted-and-ignored for
  back-compat — the numbers live in your record, not the tool call.

### Improved
- `docs/PROTOCOL_DOCTRINE.md` gains a **"Tools verify recorded work —
  they never do the science"** section with the litmus test: if
  removing a tool would change a scientific result, the tool was doing
  the science and is wrong.
- The `audit/audit_and_validation` assumptions step is reframed from
  "re-test assumptions" to "run the diagnostics in your code, then
  verify you recorded them."

### Removed
- `statsmodels` / `scipy` statistical computation from the audit layer
  (the `_POWER_TESTS` / `_POWER_PER_GROUP` solver tables and all
  in-tool diagnostic test runs). The arithmetic-only E-value
  conversion is unchanged.

---

## [3.5.0] — adaptive-aware autonomy gates (2026-06-22)

A MINOR release that teaches every protocol's autonomy gate to speak the
language of `adaptive` — the default autonomy mode since 3.3.0. Fully
backwards-compatible.

### Improved
- **Every `AUTONOMY GATE` block now names the risk dimension it guards**
  (reversible/cheap, irreversible, expensive, or real-money) and leads
  with how `adaptive` — the default — resolves it, instead of describing
  only `manual` / `supervised` / `autopilot` and leaving the default-level
  AI to infer. 34 gate blocks across 22 protocols updated, spanning the
  build, exploration, methodology, guidance, notebook, program,
  synthesis, reproducibility, and visualization tracks.
- **Doctrine codified.** `docs/PROTOCOL_DOCTRINE.md` gains a section,
  "Autonomy gates — name the risk, let adaptive resolve it," defining the
  canonical gate idiom so future protocols stay consistent: gates name the
  dimension to reason over, never hardcode a fixed proceed/ask rule.

### Fixed
- Protocol-version assertions in the dashboard-style test suite now check
  `>= 3.0.0` instead of pinning an exact string, so legitimate protocol
  bumps no longer break the suite.

### Bumped
- 22 protocol `version:` fields → `3.5.0` (gate behavior changed).
- Package version → `3.5.0`.

---

## [3.4.0] — terminal-facing router preview (2026-06-22)

A MINOR release that lets you drive the protocol router straight from the
terminal, no IDE or MCP client required. Fully backwards-compatible.

### Added
- `research-os route "<prompt>"` — runs the same hierarchical router the
  MCP `tool_route` uses and prints the routing decision: matched
  protocol, intent class / sub-intent, resolved level, complexity, tier,
  planned tool sequence, and ranked alternatives. `--json` emits the raw
  decision for scripting or non-MCP agents. Read-only: never persists an
  active plan. Reads project workflow shape + workspace mode when run
  inside a workspace; works statelessly anywhere else.

### Improved
- Shell completion now offers the `hermes` and `route` subcommands.
- CLI reference documents `research-os route`.

---

## [3.3.0] — self-improving, adaptive Research-OS (2026-06-22)

A MINOR release that makes Research-OS adapt to the work in front of it and
get better over time, and makes it a first-class citizen inside Hermes
Agent. Fully backwards-compatible: every existing autonomy mode, tool, and
protocol keeps working; the new behaviour is additive.

### Added — adaptive autonomy
- **`adaptive` autonomy mode (new default).** RO now proceeds automatically
  on cheap, reversible actions and pauses only on actions that are
  irreversible, expensive, or carry external/real-money cost. The bar
  tightens or relaxes with the project's earned rigor (trust score) across
  three tiers — `strict` (every floor gate), `normal` (irreversible +
  expensive), `light` (only truly irreversible / paid: path abandon,
  package install, paid tools, checkpoint rollback). The explicit
  `manual` / `supervised` / `autopilot` modes remain available for anyone
  who wants to pin behaviour.

### Added — self-improving skill registry
- **`tool_skills` (operation = `distill` | `promote` | `list`).** Closes the
  learning loop on top of `tool_lessons`: `distill` clusters recorded
  lessons by tag and crystallizes recurring patterns into reusable
  Hermes-compatible `SKILL.md` cards under `workspace/.skills/`; `promote`
  lifts durable, cross-project lessons into the user profile
  (`~/.config/research-os/profile.yaml`) so RO improves at *this user's*
  work over time; `list` enumerates the current registry. Reachable via the
  `distill_skills` shortcut intent.

### Added — Hermes Agent integration
- **`research-os hermes` CLI (`add` | `remove` | `status`).** Wires the RO
  MCP server into `~/.hermes/config.yaml` (`mcp_servers:`) and installs a
  canonical RO `SKILL.md` so Hermes loads the research workflow
  automatically. The edit is comment-preserving (ruamel round-trip),
  idempotent, and reversible; supports stdio (auto-detected launch command)
  or an HTTP/SSE `--url` endpoint.

### Improved
- **Synthesis overwrite gate is now overwrite-aware.** Force-writing a
  synthesis file that does not yet exist no longer triggers a confirmation
  gate — a fresh write destroys nothing, so only an actual overwrite of
  existing content (which auto-archives the prior version) gates.

### Fixed
- Corrected a doubled "because" in the adaptive gate's confirmation
  message.

### Bumped
- Router index `version:` 33 → 34 (adds the `distill_skills` shortcut).

### Documentation
- Documented the new `adaptive` default across SETUP, RESEARCHER_GUIDE,
  SECURITY, and FAQ, and corrected stale `autonomy_level: managed`
  references (never a valid value) to the real enum
  (`adaptive | manual | supervised | autopilot`).
- Added a `research-os hermes` section to the CLI reference.

---

## [3.2.10] — security, data/IO, durability & literature-integrity hardening (2026-06-21)

A PATCH release from an adversarially-verified audit of five under-covered
dimensions — input/SSRF & supply-chain security, data-pipeline correctness,
crash/concurrency durability, bibliography integrity, and resource-bound edge
cases. 39 findings confirmed and fixed across four gated waves. No tool or
protocol was removed and no schema broke.

### Fixed — security
- **Local-file read / SSRF via literature download.** `download_literature`
  passed a raw URL to `urlopen`, so a `file://` / `ftp://` URL (reachable from
  untrusted provider data) could read arbitrary local files. Now only
  `http`/`https` schemes are accepted.
- **API keys / author PII leaked into the share archive.** `researcher_config.yaml`
  (plaintext `api_keys` + author PII) is now excluded from the share archive and
  the export script — both in the template and for existing projects (the export
  script is always regenerated).
- **LaTeX shell-escape.** `tool_latex_compile` now runs pdflatex/bibtex with
  `-no-shell-escape` and a hardened TeX env (`shell_escape=f`, `openin/out_any=p`).
- **pip flag injection.** `package_install` rejected nothing — a package name
  starting with `-` was treated as a pip option. Names beginning with `-` are
  rejected and a `--` end-of-options separator is inserted.
- **Cytoscape `.cys` zip-slip / zip-bomb.** The `.cys` reader gained a per-member
  uncompressed-size cap (100 MiB) and project-root containment for both the input
  archive and the output path.
- **Autopilot gate `../` bypass.** The synthesis-write confirmation gate resolved
  the path naively; `workspace/../synthesis/paper.md` slipped through. The path is
  now resolved against the project root before the check.

### Fixed — data-pipeline correctness
- **Invalid JSON from non-finite stats.** `data_profile` emitted `NaN`/`Infinity`
  tokens (invalid JSON). Fixed at the source and systemically — the result
  envelope now serializes with `allow_nan=False` plus a recursive non-finite
  sanitizer, so no tool can emit invalid JSON.
- **`data_profile` crash on nested cells.** A `.jsonl`/`.json` with list/dict
  cells raised a bare `unhashable type`; `nunique`/`value_counts` are now guarded
  per-column.
- **Non-UTF-8 CSV/TSV crash.** Data tools raised a raw `UnicodeDecodeError`; added
  an encoding fallback (`utf-8-sig → cp1252 → latin-1 → replace`) with a surfaced
  `encoding_note`.
- **Nullable / datetime columns missing stats.** pandas nullable `Int64`/`Float64`
  and datetime columns now get descriptive stats (dtype introspection).
- **Whole-file memory reads.** `data_sample`/`data_profile` gained the project-root
  containment guard `data_convert` already had + a 500 MB read cap; `data_sample`
  head now streams via `nrows`. `_classify_domain` and the intake row-counter
  stream the header/rows instead of loading multi-GB files.
- **Missing optional engine UX.** parquet/feather/excel reads & writes now surface
  a one-line `pip install` hint instead of a raw pandas `ImportError`; added the
  `[data]` extra.
- **`data_sample` negative/zero `n_rows`** is rejected; empty-CSV intake reports
  `n_rows=0` (was `-1`); `context_intake` now consults size+mtime so a changed
  same-named file is re-imported (never silently skipped or overwritten).

### Fixed — durability & concurrency
- **Crashed background tasks looked successful.** A task's exit code was discarded;
  `task_status`/`task_list` now keep the `waitpid` status word, derive `exit_code`,
  and report `task_status='failed'` + `succeeded=False` on a non-zero exit.
- **Cross-session lost updates.** `save_state` and the ledger mutators
  (`update`/`set_phase`/`complete_phase`/`track_tokens`/`save_ctm`, memory
  hypothesis add/update, path abandon/rename/group, numbered-step creation) did
  unlocked read-modify-write. All now route through a locked mutator (the slow
  disk-blob + STATE.md regeneration stay outside the lock; `flock` is
  non-reentrant, so no deadlock).
- **Orphan checkpoint snapshots.** An interrupted snapshot left a dir invisible to
  repair. Snapshot/rollback-backup now drop an `.incomplete` sentinel during the
  copy; rollback refuses a sentinel'd checkpoint; `workspace_repair` quarantines
  manifest-less/sentinel dirs (never deletes) and `list` marks them.
- **`group_paths` half-move.** A mid-loop failure left steps half-moved; completed
  moves now roll back and the empty container is removed.
- **Non-atomic state writes.** `current_tier.json`, `active_plan.json` (3 sites),
  and researcher certifications (self-bricking) now use temp-file + `os.replace`.

### Fixed — bibliography integrity
- **Empty bibliographies (CRITICAL).** Every Typst paper compiled with an empty
  bibliography: `generate_citations_md` emits `### \`key\`` + `- Field: value`,
  but the Hayagriva converter expected `@key`. The parser now reads the canonical
  back-ticked-key format (strips bullets/backticks, aliases `authors`→`author`).
- **Citation-verify laundering.** `verify_citation_key` "verified" any keyword
  match; it now requires the Crossref hit to match the key's first-author surname
  + year, refusing otherwise.
- **arxiv abstract page saved as a PDF.** `search_arxiv` rewrites `abs/<id>` →
  `/pdf/<id>.pdf` for the download target (abstract URL kept as `abs_url`).
- **False "verified" badge.** `generate_citations_md` reserved the ✅ badge for an
  explicit truthy `verified` flag; an identifier alone reads "not yet verified".
- **Lenient PDF magic check.** `is_valid_pdf` matched `%PDF-` anywhere in the first
  64 bytes (HTML/JSON tokens slipped through); it now anchors after one BOM +
  leading whitespace.
- **Citation-key collisions.** Two distinct references sharing a key clobbered each
  other; entries now dedup identical refs and suffix `a/b/c` on a real collision.
- **Dangling-citation audit.** Added `audit_bibliography_resolution` (WARN-only)
  reconciling cited keys against the bibliography, wired into substantiveness,
  `audit_synthesis`, and the synthesis check.
- **Paywall key over-collapse.** `paywall_memory` collapsed every DOI-bearing URL
  to one key (a 403 on one mirror vetoed all); DOI-scoping is now reason-aware.
- **doi/url YAML escaping.** doi/url values are escaped, so quotes/backslashes no
  longer produce invalid Hayagriva YAML.

### Fixed — resource-bound edge cases
- `sys_workspace_tree` depth is coerced + clamped to `[0, 12]` (a negative/garbage
  depth no longer recurses unbounded or crashes).
- The router fall-through path now normalizes the prompt (hyphen-insensitive
  matching consistent with the main path).
- The HTTP Retry-After sleep is capped at 30 s (an untrusted header can't stall).
- Adapter `run_all` counts only actually-run adapters (+ `total_skipped`).


---

## [3.2.9] — scientific rigor + reproducibility integrity + universality (2026-06-20)

A PATCH release from an adversarially-verified audit of five under-covered,
high-value dimensions (the statistical gates had been audited for crashes,
never for METHODOLOGY; reproducibility/provenance integrity; a fresh bug sweep;
field universality; AI usability). 38 findings confirmed (3 dropped as bogus)
and fixed across four gated waves. Several audit fixes change verdicts (flagged)
but no tool/protocol was removed and no schema broke.

### Fixed — statistical / methodological correctness
- **Claim-grounding "grounded" hallucinated counts.** Integer claims (sample
  sizes / counts) were matched within a 1% tolerance, so a paper's N=2456
  "grounded" to a real 2469. Integers now require an EXACT match; floats keep
  the ±1% tolerance.
- **Claim-grounding false-blocked well-reported papers.** CI confidence levels
  (95%) and p-value thresholds (p<0.001) were extracted as claims → ungrounded
  BLOCKERS that refused to ship. Both are now excluded (context-aware).
- **Power audit reported wrong power for every non-two-sample design.** It
  hardcoded the two-sample t-test; now test-family aware (paired / one-sample /
  two-proportion / ANOVA) and stamps the assumed test. `n` documented as
  PER-GROUP (the natural total-N misreading roughly doubled reported power).
  Non-finite power is now an error, not a silent "passed". Handler coerces
  stringified numeric args (a crash the e-value path had already been hardened against).
- **E-value applied the risk-ratio formula to any scale.** Now
  `effect_measure=rr|or|hr` + `rare_outcome`: a common-outcome OR is converted
  RR≈√OR, HR is flagged, rare outcomes use the value directly.
- **Normality check was biased + over-eager.** Shapiro-Wilk took the first
  5000 (ordered) residuals → seeded random subsample; the unconditional
  "switch to rank/bootstrap" advice is now n-aware (acknowledges CLT robustness).
- Removed clinical/epi defaults leaking into field-agnostic tools (sensitivity
  multiverse grid; the prereg SAP no longer defaults multiplicity to BH).

### Fixed — reproducibility / provenance integrity
- **Re-run audit never compared the baseline it promised** — a non-deterministic
  / drifted output reported success. Now compares each re-run output's hash
  against the recorded baseline (.prov.json / output_hashes.json) and is honest
  when no baseline exists.
- **Re-run used the wrong context** (cwd=scripts/ vs the pipeline's cwd=step/ +
  env) — now aligned, delegating to the pipeline runner when a spec exists.
- **Checkpoint rollback was restore-OVER, not restore-TO** — files created after
  the checkpoint survived. Rollback now deletes non-manifest workspace files
  (scoped to workspace/, skipping ref-only data, recoverable via the backup).
- **Provenance could silently drift** — added an output-sha256 integrity check
  (an artefact edited outside its producing script is now flagged).
- Pre-rollback backups no longer evict user checkpoints (own GC bucket) or
  deep-copy large data; R/Julia outputs no longer record a Python-only env;
  unseeded randomness is flagged; the `iteration` provenance field is written.

### Fixed — correctness bugs
- `tool_python_exec` returned success on a CRASHING script (siblings didn't) →
  now errors; missing-path message echoes the path.
- Foreign-script / notebook executors crashed on non-UTF-8 output → `errors=replace`.
- `tool_literature_download` had no timeout (a hung server hung forever) → 30s.
- Pack renderers (engineering FMEA/fault-tree/requirements, wet-lab plate map)
  no longer crash on a malformed item; pack tools guard path-escape.
- `audit_methods` no longer false-flags methods (slug-vs-prose normalization);
  `advance_plan` no longer conflates a real audit error with a completeness block.
- task fd leak; same-second ID collisions (checkpoint/backup/slurm) get a uuid suffix.

### Improved — universality + usability
- **Hyphen-insensitive routing** — "agent-based", "single-cell", "fixed-effects"
  no longer strand/misroute (both prompt + trigger normalized).
- Qualitative routing now reaches phenomenology / discourse / content analysis /
  case study / narrative inquiry; the dead `workflow_shape` signal is revived
  (inferred from workspace.mode); engineering simulation/CFD/controls prompts route.
- Dead doc references → real `sys_help` topics; stale protocol + adapter counts
  corrected; `output_types` vocab completed; pack tools accept `filepath` alias.

## [3.2.8] — research-grade visual-design system (dashboards / posters / figures) (2026-06-19)

Turns the deliverable design surface from a single fixed template ("generic AI
slop") into a **composable design system the AI designs from per project** — a
design skill + a design audit that reviews stylistic choices. Driven by a
design-research workflow (current-surface map + grounded dashboard/poster/figure
experts → build spec). MINOR-shaped content shipped under the 3.2.8 label;
several audit fixes change verdicts (flagged below) but no tool/protocol was
removed and no schema broke.

### Added
- **`viz/palettes.py`** — one source of truth for the visual identity, consumed
  by chrome AND the audit: three selectable professional palettes (ro_house /
  okabe_ito / clinical), each light+dark, AA-contrast, CVD-safe; sequential
  (viridis) / diverging (PuOr) anchors; banned rainbow colormaps; colour-science
  predicates (is_neon tuned so professional-saturated colours pass).
- **Composable dashboard archetypes** — the single `_DASHBOARD_HTML` becomes a
  shared shell + four selectable `<main>` archetypes: single-viewport-brief (no
  scroll), scroll-lite-narrative (in-page nav required, default),
  comparison-scorecard, multi-panel-exploratory. `:root` tokens are generated
  from the chosen palette (palette selection is real); `<body data-archetype>`
  is stamped for the audit.
- **Composable poster archetypes** — `classic` (default) / `billboard`
  (asymmetric centre + sidebar) / `hero` / `portrait` presets + `poster-stats`;
  poster type scale raised to true poster size (headline 48→90pt, title 56→80,
  body 16→24). Three selectable palettes wired through.
- **`synthesis/deliverable_design` protocol** — the visual-design skill (the
  "UI/UX pro max" for research deliverables): 7 principles + a 6-step
  archetype/palette/budget selection scaffold + the anti-pattern list. Routes on
  "design my dashboard" / "make this professional" / "the dashboard looks
  generic" / etc.
- **`tool_synthesis_scaffold` gains `archetype=` + `palette=`** (optional,
  validated, reported + stamped). Old calls unchanged.
- **The design audit** — reviews stylistic choices, not just structure:
  dashboard (scroll budget / endless scroll, in-page nav, per-step recap,
  workspace+tool leaks, neon/off-palette, buried lede, density, uncaptioned
  figures, colour-not-sole-channel, archetype-vs-declared), poster (size-aware
  font floor, single+finding headline, column/section sanity, palette restraint,
  density, captions, internal-step leak), figure (banned rainbow colormap,
  palette adherence, axis labels/units, finding-led caption, internal-ref leak,
  zero-baseline, spaghetti, aspect ratio).
- **Figure primitives** in `viz/style.py`: `ranked_dot`, `lollipop`,
  `facet_grid` (shared axes), `direct_label_endpoints`, `ro_colorbar`.
- **Slide layouts** in touying-mini: `big-number-slide`, `quote-slide`,
  `two-column-slide`, `image-full-slide`.

### Improved
- `synthesis_dashboard` no longer mandates the cream/serif identity as THE style
  (the doctrine conflict) — the RO house palette is the default for figure
  cohesion, a custom-but-professional palette is fine; "endless scroll" added to
  forbidden structure; delegates archetype/palette choice to `deliverable_design`.
  `printable` + `synthesis_slides` delegate likewise.
- Venue templates `generic_two_column` + `humanities_essay` consume the shared
  `common.typ` ro-* tokens (H1 now RO navy; generic heading sizes shift ≤1pt to
  the shared scale).

### Fixed (audit verdict-changing — by design)
- `audit_color_palette` was a membership allow-list that **punished any custom
  palette**; it now JUDGES quality (neon → block, lack of restraint → warn) and
  scans the chrome `<style>` block. A custom-but-professional palette passes.
- Removed `per_step` (and `audit`) from `DASHBOARD_SECTIONS` / `SECTION_BARS`:
  the dashboard content audit no longer **rewards** the per-step recap
  anti-pattern it elsewhere bans.
- `_check_poster`'s misleading flat 14pt body floor → a size-aware poster floor.

## [3.2.7] — UX + output-design + override polish, fresh bug-sweep (2026-06-19)

A PATCH-only iteration (no new tools, protocols, or config knobs) from an
adversarially-verified audit across five themes: init/start UX, usage-protocol
refinement, override ergonomics, output design, and a fresh bug sweep. 45
findings confirmed (50 checked; 4 dropped as bogus/stale, 1 deferred) and fixed
across four gated waves. One stale finding was caught + avoided during
implementation: `tool_synthesize` is a removed tool, so its
`override_completeness_gate` is an internal plan flag, not a user-facing kwarg —
it was not documented as one.

### Fixed
- **Wizard model-profile choice was a silent no-op.** `init_config` wrote only
  the legacy top-level `model_profile`; every reader prefers `ai.model_profile`.
  Now synced at both write sites.
- **`sys_config set` accepted off-enum typos.** A typo like `gate_strictness: lite`
  was written silently, then silently treated as the default. Now rejected up front.
- **Boolean config knobs stored truthy strings.** `figures.svg_allowed=false` was
  stored as the string `"false"` (truthy), inverting the toggle. Registered as
  bool fields so they coerce to real `False`.
- **E-value audit crashed on string CI bounds** (`TypeError`). CI bounds are now
  coerced like `risk_ratio`, with a clean error envelope on bad input.
- **`StateLedger._load` had no JSON-decode guard** — a corrupted `state_ledger.json`
  crashed every state read. Now backs up the broken file and reseeds defaults.
- **`data_convert` could write outside the project** and falsely error on an
  absolute path. Added an up-front containment check.
- **Multiple research questions collapsed to one** in `intake.md` / `STATE.md`.
- **`--transport sse` silently fell back to stdio** with no warning; now warns.
- **Scaffolded README + ISBN User-Agent** linked a 404 GitHub URL (wrong casing).
- **`GETTING_STARTED` "More" links** pointed at docs never scaffolded into a project.
- **`start --workspace <non-RO dir>`** warned then launched anyway; now fails fast.
- **Protocol tool-call examples were wrong**: `tool_verify` (wrong arg shape),
  `tool_ground` (nonexistent params), `tool_thought` (`entry_type=`→`kind=`),
  references to removed `grounding_register` / `grounding_verify`.
- **Dead/contradictory protocol pointers**: `analysis_plan` now loops back per the
  core-loop doctrine; `session_boot` + `scope_clarification` marked `terminal`.
- **Router index** referenced 16 deprecated audit-alias names → canonical `tool_audit`.
- **Dashboard `--muted` failed WCAG AA contrast** (4.35:1 → 5.3:1).
- **Handout used an unbundled font** (`Inter`) → font warning + silent fallback;
  now the bundled New Computer Modern Sans; handout wired into the overflow gate.
- Smaller fixes: `step_revision_options` IndexError on underscore-less step_id;
  missing `encoding=utf-8` on file writers; `set_config` clobbering a scalar
  intermediate (now warns); dispatch.py operator-precedence; `nature.typ` false
  header comment.

### Improved
- **Unified output visual identity.** Poster + slide palettes now mirror the
  figure/dashboard `RO_PALETTE`; the slide deck applies an RO navy accent that was
  previously computed but never used (title/section/content/focus slides); shared
  Typst design tokens (colour + type scale + fonts) in `common.typ`; PLOS/Cell
  headings use the shared token; poster body switched to sans + ragged-right for
  across-the-room legibility.
- **Modern dashboard standards**: dark-mode, reduced-motion, focus-visible, skip-link.
- **Honest override + config docs.** `warn_only` / `allow_override` marked RESERVED
  (not yet enforced); `project_tier` precedence stated truthfully; `hybrid` workspace
  mode documented; cross-deliverable override now requires a rationale regardless of
  policy (consistent with its six siblings); `sys_help(topic='overrides')` is the
  canonical bypass list; ship gate documented as ignoring `quality_gate_policy`.
- **Onboarding affordances**: doctor/verify now checks the MCP server command is on
  PATH (the #1 silent first-session failure); wizard confirmation card shows Mode +
  Model class; doctor glyphs degrade to ASCII on non-UTF-8 terminals.
- **WARN-only poster/slide design lints** (font floor + colour-vision-deficiency
  check), scoped to hand-rolled overrides so clean scaffolds stay silent.

## [3.2.6] — core bug-sweep + the 3.2.5 deferred items (2026-06-19)

Two halves: (1) the items flagged-but-deferred from 3.2.5, and (2) a deep
adversarially-verified bug-sweep of the CORE surface (handlers, synthesis,
audit gates, state/provenance, router internals, exec/data, CLI) that 3.2.5
didn't touch — 67 confirmed findings, all fixed.

Scoped as a PATCH per maintainer direction (one release). **Note:** this
release adds genuine new surface — 2 infra adapters, 1 protocol, 2 pack
tools, new router triggers — which is conventionally MINOR; it's bundled
under PATCH at the maintainer's request.

### Security

- **Arbitrary code execution fixed in `tool_rmarkdown_render`.** `output_format`
  + `doc_path` were f-string-interpolated into `Rscript -e "rmarkdown::render(...)"`,
  so a crafted value could break out and run arbitrary R → shell. Now the R
  code is fixed and the path + format are passed as `commandArgs` (argv) —
  injection-proof. Also: `pip install` now has a timeout (could hang the
  server); `data_convert` no longer overwrites the source in place; typst
  compile + verify-outputs reject paths escaping the project root.

### Added (the 3.2.5 deferred items)

- **MLflow / Weights & Biases adapter** — detects `mlruns/` / `wandb/` /
  tracker imports; extracts per-run params / metrics / tags as provenance.
  Detect+extract only (no new catalog tools). The biggest external-coverage
  gap (almost all ML/CS research uses a tracker).
- **Zenodo / OSF / Figshare / Dryad deposit adapter** — DMP-deposit
  provenance across every field (funder compliance).
- **`methodology/spatial_analysis` protocol** — the analysis counterpart to
  map-plotting (CRS, spatial dependence/autocorrelation, spatial-vs-aspatial
  model choice, MAUP/edge effects, spatial cross-validation); non-prescriptive.
- **wet_lab `tool_wet_lab_run_log_init` + `tool_wet_lab_checksum_raw`** — the
  two generic instrument-run-log tools (stub a family run-log; stream-sha256
  + record a raw file). The 5 instrument-specific QC tools remain a documented
  manual step (they'd need proprietary-format parsers).
- 8 adapters now bundled (was 6); 128 protocols (was 127).

### Fixed (core bug-sweep)

- **Envelope conformance.** Broadened `_is_legacy_envelope` so the dispatcher
  upgrades ANY `{status,…}` handler result lacking `payload` — repaired ~15
  core tools that leaked non-conformant envelopes. Explicit fixes for what the
  normalizer can't infer: `tool_step_complete` (overall_status→status, payload
  preserved), `latex_compile` (no longer reports success on a failed compile),
  `sys_session_handoff` (wraps its markdown), `path_finalize` (string error,
  not a dict), and `resolve_gate_strictness` / `dry_run` / `quick_route`
  (status-less dicts). New **core-handler envelope conformance test** — the
  gap that let the whole class ship.
- **Dead dispatch / router drift.** `tool_step(operation='env_lock')` actually
  runs now (was always "handler not callable"). The anti-one-shot deliverable
  gate + heavy-step weighting referenced tools removed long ago, so they never
  fired for Typst deliverables — refreshed to live tools (drift guard added).
  `_read_model_profile` honours `ai.model_profile`. Override gates require a
  rationale whenever honoured (not only under `policy=enforce`).
- **Quality-gate false ship-blocks.** %-claim grounding, cross-deliverable
  metric/figure consistency, references under any heading depth, Typst
  word-count, the bare-word "placeholder" blocker, `n=` matching, and
  URL-literal "hardcoded path" flags — all no longer block valid work.
- **State / provenance integrity.** Provenance sidecars use the `<stem>`
  readers expect; ledger mutations are atomic under the lock; `analysis.md`
  writes atomically; rollback backups are GC-managed; symlink repoints can't
  drop the link; step regexes handle steps ≥100.
- **Synthesis.** Typst special chars in title/author/abstract are escaped
  (compile breakage); commented-out HTML no longer trips the dashboard
  audit; the offline blocker catches single-quoted external scripts;
  citation formatters handle dict-shaped authors.
- **CLI / config.** `sys_config set` no longer strips the 177 inline help
  comments from `researcher_config.yaml` (ruamel round-trip) + re-locks 0600
  + coerces list/bool fields; `init` flag fixes (`--name` slug, `--mcp-scope`,
  `--ide none`). Plus router detector caching, ISO/NULL data previews, and
  mode-aware errors for `mem_log` / `tool_ground` / `tool_verify`.

### Bumped

- Version 3.2.5 → 3.2.6 across `pyproject.toml`, `__init__.py`, `CITATION.cff`.
  Router index v29 → v30; `_route_meta.json` + `_embeddings.npz` rebuilt.

---

## [3.2.5] — pack/adapter robustness + universal-coverage pass (2026-06-19)

A deep audit of the 5 domain packs (humanities, qualitative, theory_math,
wet_lab, engineering) and 6 infra adapters (slurm, snakemake, nextflow,
cytoscape, redcap, synapse) — driven by an adversarially-verified multi-agent
review — found they were real and working but **structurally inconsistent,
invisible, and untested at the boundary**, and that the router stranded real
fields it could already serve. This release fixes that whole class.

Scoped as a PATCH per maintainer direction (one release, not a flood). Note:
a few items here — new router triggers, a new `sys_help` topic, new additive
`sys_boot` fields — are conventionally MINOR; they're bundled in under PATCH
because they fix dead/hidden/misrouting behaviour rather than add new surface.

### Fixed (bugs)

- **REDCap adapter went dark on UTF-8 BOM CSVs** (the standard Windows
  web-UI export) — no detection, no PHI warnings. Now reads `utf-8-sig`.
- **SLURM directive parser** dropped space-separated long opts
  (`--time 01:00:00` → `'true'`) and **every PBS `-l` resource**; the cost
  estimator hard-crashed on non-numeric nodes (`-N jobname`, ranges); the
  walltime parser misread bare minutes (~60× off) and `days-hours`. All fixed;
  `-N` now disambiguated by scheduler (Slurm=nodes, PBS=job-name).
- **Engineering FMEA** bolding corrupted every RPN≥100 row (double
  `.replace("|", …)` hit the leading pipe); **requirements_matrix** raised
  `KeyError` on a requirement missing `id`.
- **qualitative** speaker-turn detector never matched `I:` / `R:` / `P:` (the
  most common transcript convention) — the colon was double-counted.
- **humanities transcribe** returned `status:success` on a missing image;
  now a proper error. **wet_lab** reagent/lineage outputs no longer escape to
  `inputs/` or break on `/` in catalog numbers (reagents accumulate into one
  ledger). **nextflow** no longer recurses into `.git`/`.venv`/`node_modules`
  or captures trailing `//` comments into directive values. **synapse**
  `project_id` now `fullmatch`-validated.

### Improved (consistency + wiring)

- **One envelope, not eleven.** Shared `pack_ok`/`pack_err` (from
  `research_os.plugins`) and `ok_envelope`/`err_envelope` (from
  `research_os.adapters`) replace ~10 copy-pasted pack helpers + 6 byte-
  identical adapter copies that had already drifted (mismatched error keys,
  one pack missing `_err`). `register_adapter` now rejects a compiled
  `re.Pattern` as a `tools_md_patterns` source (was a latent CPython-only fluke).
- **Bundled packs report the wheel version** (were stale 1.9.x / 1.11.0).
- **Preflight now validates pack-protocol tool refs + routing targets** — the
  blind spot that let broken pack refs ship green. It immediately caught and we
  fixed: theory_math tool-prefix typos, a dangling conjecture `on_failure`,
  wet_lab `instrument_run_log`'s 7 phantom tools (rewritten to the real manual
  workflow), and plate-map / sample-lineage / experiment-design / humanities
  refs to tools that never existed.

### Added (discoverability — "how do users actually use the packs?")

- **The pack domain detectors are now wired in.** They were registered but
  **read nowhere** — the signal "this is wet-lab / humanities work" was
  computed and discarded. New `run_pack_domain_detectors()` powers a `sys_boot`
  nudge (`field_signals` + `pack_nudge` + `pack_capabilities` +
  `adapters_detected`) and a level-0 route hint.
- **`sys_help(topic='packs')` / `topic='adapters')`** — dynamically lists all
  11 modules + how to use them; the `fields` topic now points to it.
- **Universal field routing.** `methodology/deep_domain_research` (the
  any-field-from-the-literature path) gained field-agnostic triggers + cross-
  field anchors (panel data, GARCH, econometric, spatial autocorrelation,
  spectroscopy, doctrinal); the level-0 fallback now names it +
  `scope_clarification`. Survival → `cox_ph_diagnostics`, remote-sensing →
  `geospatial_visualization`, scale-validation → `survey_psychometrics`; the
  greedy bare-`status` shortcut no longer hijacks "conjecture status".
- **`AGENTS.md`** gained a compact packs/adapters block (still under the lean
  budget); the **wizard** domain menu added geoscience / ecology / astronomy /
  public-health / education / law / humanities / engineering + a "what packs
  are available?" prompt.
- **New contract tests** (`tests/unit/test_pack_adapter_contract.py`) hold the
  live registry to one bar: every pack contributes tools/router + wires its
  detector + ships loadable YAML + reports the wheel version; every adapter
  `describe()` returns a dict + every adapter tool dispatches to a clean
  envelope. A new pack/adapter can no longer ship half-wired.

### Bumped

- Version 3.2.4 → 3.2.5 across `pyproject.toml`, `__init__.py`, `CITATION.cff`.
  Router index v28 → v29; `_route_meta.json` + `_embeddings.npz` rebuilt.

---

## [3.2.4] — leaner per-session context (2026-06-18)

Efficiency release. `AGENTS.md` is loaded into context every session and had
grown to 372 lines; this trims the always-on footprint without losing any
operating rule — deep detail now lives in `sys_help` topics, loaded on demand.

### Improved

- **`AGENTS.md` slimmed 372 → ~160 lines (-57%).** Rewritten as a lean
  always-on CORE — session loop, token economy, operating contract, all 12
  hard rules (one line each), workspace modes, quick-lookup table — that
  delegates deep detail to `sys_help` topics (`routing`, `overrides`,
  `iteration`, `recovery`, category orientation) which already existed and
  largely duplicated AGENTS. Every safety-critical rule + concept preserved.
- **`templates/CLAUDE.md` slimmed 47 → ~21 lines** — it duplicated the boot
  loop + modes now in AGENTS.md; reduced to the Claude-Code-specific
  essentials + a pointer to AGENTS.md.
- **`sys_boot` payload trimmed** — `config_reconcile_hint` no longer re-lists
  values already structured in `config_directives` (boot ~535 → ~494 tokens).

### Added

- **`tests/unit/test_agents_md_lean.py`** — a guard that keeps `AGENTS.md`
  ≤ 200 lines AND verifies the critical anchors (session loop, hard rules,
  token economy, operating contract, `sys_help` pointer) are never dropped in
  the name of brevity. Institutionalises the "keep it short" constraint so it
  can't silently bloat back.

### Note

- The largest per-session context cost is the MCP **tool catalog** (~14.5K
  tokens of tool descriptions). Those are deliberately left intact — they
  drive tool-selection accuracy, and trimming them would trade correctness
  for marginal savings. Flagged for a future, carefully-measured pass.

---

## [3.2.3] — routing accuracy on real-world phrasing (2026-06-18)

Optimization release: make routing land the right protocol on the queries
researchers actually type (paraphrases + jargon, not the exact trigger
phrase), and tighten the operating manual so the AI stops over-reading.

### Improved

- **Routing accuracy on paraphrase / jargon queries: top-1 52% → 88%,
  top-3 84% → 96%** (measured on a new 25-prompt hard eval), with the
  existing easy fixture held at 100% — zero regression. Achieved by adding
  specific, substring-safe **triggers** to the nine protocols that misfired
  (inter_rater_reliability, preregistration, data_management_plan,
  replication_study, reproducibility, hyperparameter_search_design,
  journal_selection, synthesis_paper, writing_limitations). Rebuilt
  `_route_meta.json` + `_embeddings.npz`; router index v27 → v28.
- **AGENTS.md gains a "Token economy" contract** — summary-first protocol
  loads, never re-read payloads already in context, search-don't-dump (no
  loading `_router_index.yaml` / the full tool catalog to look around), read
  file slices not whole files. Codifies the don't-waste-tokens discipline.

### Added

- **`HARD_FIXTURE` paraphrase regression guard** in the semantic-routing
  test suite (top-1 ≥ 80%, top-3 ≥ 90%) — routing is now permanently
  *measured* on the phrasings users misfire on, so future edits can't
  silently regress paraphrase accuracy.

### Investigated, not shipped (kept the proven baseline)

- A hybrid **dense + BM25 + stemmed-trigger** retriever was prototyped and
  measured against the hard eval — it **regressed** the well-tuned baseline
  (BM25 promotes generic high-token-overlap protocols; suffix-stemming broke
  exact-trigger matches). Reverted. For *paraphrase* misses the effective
  lever is trigger coverage + sharper summaries, not lexical fusion; that's
  what shipped.

---

## [3.2.2] — hybrid mode, AI-maintained config, honest environments (2026-06-18)

Driven by an end-to-end audit of a real **research + software** project
(`reaction-similarity`). The audit found steps advancing with an untouched
`plan.md`, an `environment/requirements.txt` that was a full `pip freeze` of
the *server's* conda env, a trivial workflow diagram, an empty glossary, and a
write-once `researcher_config.yaml` that never tracked actual behaviour. This
release closes all of those. (Numbered 3.2.2 by request; the surface is
backwards-compatible — every existing tool keeps its name + schema.)

### Added

- **Hybrid mode (research + software).** New `workspace.mode: hybrid` (wizard
  choice + `--workspace-mode hybrid`). `detect_software_components()` finds inner
  code repos / packages (pyproject / Cargo / package.json / `.git`; RO scaffold
  dirs excluded); `sys_boot` reports `software_components` and the workflow DAG
  renders each as a `Software` node the latest step "informs".
- **researcher_config is the AI's operating contract.** `sys_boot` now returns
  `config_directives` (autonomy, gate policy, ambiguity posture, agent_notes,
  output_types, citation_style, compute env) + a `config_reconcile_hint`. The AI
  is instructed to FOLLOW these every session and keep them in sync via
  `sys_config(set)` when intent shifts. New config fields: `interaction.agent_notes`
  (free-form project directives) and `runtime.compute_environment` + `package_manager`.
- **Live context drop-zone detection.** `inputs/context/` (+ per-step `context/`)
  is watched: `sys_boot` peeks and `tool_route` surfaces NEW/CHANGED files since
  the last turn, so a mid-session "I dropped a paper in context/" makes the AI read
  it. First scan is a silent baseline.
- **Glossary nudge.** `sys_boot.glossary_unfilled` flags an empty `docs/glossary.md`
  once real work exists.
- **`--mcp-scope {workspace,global}`** on `init`, plus a loud **restart notice** the
  wizard + AGENTS surface after MCP setup.

### Improved

- **Step gate now inspects `plan.md`.** Scaffolding step N+1 is blocked when the
  previous step's `plan.md` is still the unfilled seed (≥4/6 sections untouched) —
  the exact slip seen in the audited project. Overridable via
  `sys_path(allow_unfinalized_predecessor=true, …)`.
- **Import-driven `environment/requirements.txt`.** `env_snapshot` + step `env_lock`
  pin only the packages the project's own scripts import (scanned from `.py`/`.ipynb`),
  excluding the Research-OS server stack (research_os, mcp, fastembed, …) that shares
  the interpreter.
- **Realistic workflow diagram.** `workspace/workflow.mermaid` + `docs/workflow_dag.mermaid`
  are now built by one shared builder: real data-dependency edges (from
  `data/past_step_input` symlinks, with a sequential fallback), node purpose labels,
  status colours, dead-end styling, branch subgraphs, raw-data source node — replacing
  the `init → every step` fan-out.
- **`inputs/` relaxed to a soft guard.** Only `.os_state/` is hard-locked now.
  `inputs/` is writable; `inputs/raw_data/` + `inputs/literature/` need `force=true`
  + a confirm-with-researcher warning (and flag the intake stale); `inputs/context/`
  is a free drop-zone.
- **Canonical MCP entry.** One portable `mcp_server_entry()` everywhere; Claude Code's
  real project file (root `.mcp.json`) is now written with that same entry so it stops
  drifting to abs-path `claude mcp add` configs.
- **Interview-before-scaffold.** AGENTS instructs the AI to ask the questions that
  shape the scaffold (question / domain / output / autonomy / compute) and fold them
  into the config BEFORE running init, rather than scaffolding with defaults.

### Removed

- **No `codemeta.json` at scaffold.** It shipped as root clutter with placeholder
  "Anonymous Researcher" content; it's now generated on demand by `sys_export_ro_crate`
  / the share-archive export. `CITATION.cff` is still emitted.
- **Per-step `outputs/reports/` is no longer pre-created.** Empty in every step it became
  a magnet for misplaced analysis artefacts; it's created on demand for presentation
  artefacts only (the inventory tolerates its absence). `outputs/figures` + `outputs/tables`
  unchanged.

---

## [3.2.1] — plan.md is a living document (2026-06-18)

PATCH. Fixes a gap in 3.2.0: the AI was told to *write* a step's `plan.md`
before the work but never prompted to *update / reconcile* it as the step ran.

### Fixed

- **`plan.md` is now a LIVING plan.** Its seed reframes it as written-then-kept-
  current and adds a `## Progress & deviations from plan` section. The
  `analysis_plan` protocol's `document_conclusions` step now explicitly instructs
  the AI to reconcile plan-vs-actual (method swaps, dropped/added analyses, or
  "went to plan") and keep `inputs/research_plan.md`'s iteration log in sync, and
  `tool_path_finalize` nudges when that section was left unfilled.
- **Protocol caught up with 3.2.0.** `document_conclusions` no longer tells the AI
  to write a `## Plain-language summary` into `conclusions.md` (3.2.0 moved that to
  the README's `## In plain English`); the step now points there + lists the
  current `conclusions.md` sections.

---

## [3.2.0] — Workspace declutter: clean step layout, iterative planning, grounded literature (2026-06-18)

MINOR release. Backwards-compatible: every existing tool keeps its name + schema,
and pre-3.2 projects keep working (reading code tolerates the old per-step data
names + the retired sidecars). Driven by an end-to-end audit of a real generated
project — the overhaul makes a project folder show only what a researcher needs
to read, and makes planning + literature + paths first-class.

### Added

- **Per-step `plan.md` (co-scientist iterative planning).** Every numbered step is
  created with a `plan.md` written BEFORE any code: prior-step recap + the step's
  design + the open questions for the researcher to iterate on (propose → critique
  → refine, then build). Wired into the `analysis_plan` protocol (new
  `draft_step_plan` step) and surfaced under the README's "Read next".
- **`inputs/research_plan.md` (whole-project plan).** A living plan — question,
  hypotheses, planned step sequence, iteration log — that the AI + researcher
  refine together; the arc each step's `plan.md` fits into. Read by
  `iterative_planning`.
- **Project-root `literature/` corpus of record.** Every paper used anywhere is
  auto-aggregated at step finalize: `inputs/literature/` → `literature/inputs/`,
  and each step's papers (from its `literature/` AND `context/` folders) →
  `literature/steps/<NN_slug>/` — PDF + `.meta` provenance sidecar, symlinked.
  `citations.md` folds the corpus in, so a paper dropped into a step's `context/`
  still reaches the bibliography.
- **PATH-container grouping — `sys_path(operation='group', name=, steps=[…])`.**
  Consolidate a run of steps that explored one direction into a descriptive
  `workspace/<slug>_PATH_<k>/` folder instead of suffixing names. Moves the
  folders, re-points every absolute `data/*` symlink, and preserves **continuous**
  step numbering (path 2 keeps going at step 06, never resets). New shared
  `discover_step_dirs` / `resolve_step_dir` helpers keep grouped steps visible to
  the DAG, manifest, citations, numbering, synthesis, literature + rigor.
- **`data/share/`** per step — a curated dataset you package to hand to a
  collaborator, separate from the next-step pipeline.
- **`workspace/audit.md` — single project-end meta-review.** At the ship gate,
  `tool_finalize_project` writes one human-facing audit: per-step concerns grouped
  by step, each with evidence path(s), a sha256 content hash of the evidence, and
  the suggested fix. The per-gate machine detail stays in `workspace/logs/audits/`.
- **`docs/GLOSSARY.md`** — the project-structure vocabulary, including the 3.2
  concepts.

### Improved

- **Clean step root.** A step now holds `README.md` (plain-English overview, the
  canonical plain-language summary), `conclusions.md` (the deep report — findings,
  decision WITH step-to-step + version lineage), and `plan.md`. No more
  `step_summary.yaml` (derived mirror, retired) and no auto-created `pipeline.yaml`
  (only when you use `tool_step_pipeline`).
- **Clearer per-step data folders.** `data/input` → `data/past_step_input`,
  `data/output` → `data/next_step_output` (producer/consumer semantics);
  `project_inputs` kept. Reading code resolves either flavour, so pre-3.2 projects
  keep working.
- **Figures ship three sidecars, not four.** `.png` (+ `.svg`/`.html` on request) +
  `.prov.json` + `.caption.md`. The plain-English interpretation lives inline in
  `conclusions.md`; the `.summary.md` sidecar regime is removed.
- **`outputs/reports/` repurposed** to optional *snapshot presentation* artefacts
  (a one-off dashboard/slide/diagram), not findings narratives — findings live in
  `conclusions.md`.
- **Workspace declutter.** Per-gate audit `.md`/`.json` moved from `workspace/`
  root into `workspace/logs/audits/`; `tools.md`, `audit.md`, and
  `workflow.mermaid` recognised as canonical workspace files by the hygiene gate.

### Fixed

- **No project-root `outputs/` in analysis mode.** `deep_domain_research` now writes
  its pipeline survey to `docs/`, not a stray `outputs/reports/`.
- **`synthesis/claim_index.json` no longer written** — it was write-only
  infrastructure that cluttered the synthesis folder; structured findings are the
  source of truth.
- **`workflow.mermaid` / `tools.md`** are no longer flagged as workspace clutter.

### Removed

- The derived `step_summary.yaml` sidecar, the per-figure `.summary.md` sidecar,
  `synthesis/claim_index.json`, and the dead `loaded_data` state field. Stale
  copies left by a pre-3.2 release are cleaned at finalize / on state migration.
  Synthesis, audits, rigor signals, and preview all parse `conclusions.md`
  directly now.

---

## [3.1.0] — Index-free routing, output integrity, and figure/deliverable consistency (2026-06-17)

MINOR release. Backwards-compatible: every existing tool keeps its name + schema
(new capability is added via new operations/scopes and a new alias). Driven by a
fresh 11-area discovery audit of the 3.0.0 codebase.

### Added

- **Compiled routing sidecar (`_route_meta.json`).** Routing no longer parses the
  104K `_router_index.yaml` at runtime. `build_embeddings.py` compiles a compact,
  comments-free JSON mirror (protocols/shortcut_intents/hierarchy + pre-baked
  `tier` + `workflow_shape`) that `router.py` and `semantic.py` share via a single
  load. It parses ~300× faster (~0.42 ms vs ~126 ms) and removes the per-route
  protocol-body reads. The YAML stays the authoring source; `--route-meta-only`
  rebuilds the sidecar without fastembed. New preflight gate validates the sidecar
  is fresh + consistent + embeddings-parity-checked.
- **`tool_verify(scope='outputs')`** — the "did the work actually land?" gate.
  Resolves a protocol's declared `expected_outputs` against the filesystem
  (glob-aware) and reports each present / empty / missing with a `next_action`.
  The injected protocol-completion step now requires it before logging
  `completed`, so the system refuses to call a missing or empty file "done".
  `docs/VERSIONING.md` documents the in-project versioning convention.
- **`sys_path(operation='rename')`** — give a generic analysis step a meaningful
  label. Keeps the `NN_` lineage number, renames the folder, and re-points every
  downstream `data/*` symlink that targeted it. **`sys_step`** is now an alias for
  `sys_path` (the clearer name for numbered steps).
- **Routing-targets preflight gate** — every `next_protocol` / `on_failure` /
  `see_also` must point at a real protocol (dangling links were previously silent).

### Improved

- **Figures.** `tool_figure_palette('accent')` now returns the exact `RO_PALETTE`
  colours `apply_research_os_style` applies (a hand-coloured figure matches an
  auto-styled one); adds `diverging_emphasis`. `audit_figure_quality` runs its
  text-overlap + default-font (DejaVu) legibility scan on a PNG's sibling SVG too,
  and a corrupt/empty image now warns instead of crashing the audit.
- **Synthesis deliverables.** `tool_typst_compile` archives the prior render to
  `synthesis/archive/<name>_<timestamp>.pdf` before overwriting (no silent
  clobber), flags single-page-target overflow (poster/cover-letter rendered to
  >1 page = content overflowed — where overlapping text shows up), and counts
  pages without the off-by-one `/Type /Pages` miscount. The poster check no longer
  false-blocks scaffold-authored posters (`#headline` / `#block-section`).
- **Wizard.** Ctrl+C/Ctrl+D mid-wizard exits cleanly instead of a traceback; the
  "already exists" check moved to the start (no more filling out the whole wizard
  to be rejected at the end); email + ORCID inputs are format-validated.
- **Doctrine.** `power_analysis` replaced its data-shape→test-family menu with
  scaffold form (name the dimensions that fix the test, justify the choice).

### Fixed

- `state_freshness_check` read `workspace/state.json` — a file that never exists —
  so the staleness signal was permanently dead; now reads the real ledger.
- `get_dag_path` / `add_dag_node` stopped persisting the constant
  `execution_dag_path` back into the ledger every call (write churn + schema noise).
- Dead-end pause detection read `protocol_name` but the execution log writes
  `protocol` — the signal was silently dead.
- Autopilot gate used `str.lstrip('./')` (strips characters), so `.synthesis/x`
  was mangled into `synthesis/x` and falsely gated; now strips the prefix properly.
- Maintainer docs (CLAUDE.md) pointed at the long-gone `src/research_os/server.py`
  monolith — repointed to the `server/` package; dropped stale protocol counts.

### Bumped

- `version` → 3.1.0 (pyproject / `__init__` / CITATION); router index counter → 27.

### Deferred (tracked for a future release)

- Tool-cluster consolidation (SLURM 4→1) — aliased, low user-visible benefit.
- A first-class renamable BRANCH object + retro-organization of loose work
  (higher-risk state-schema change beyond the step rename shipped here).
- Deeper audit-gate hardening (claims-gate-on-by-default, ship-gate
  rerun-resolution) — behavior-changing, staged separately.

---

## [3.0.0] — Workspace modes, real rigor, and a system built for every researcher (2026-06-16)

MAJOR release. Research OS now fits the *shape* of your work — classic
linear analysis, iterative tool/software building, lightweight exploration,
notebook-driven analysis, or a multi-study program — instead of assuming one
shape. Alongside the modes it turns several "advertised but unenforced"
rigor promises into enforced ones, overhauls routing for both beginners and
deep-critic PIs, and improves every protocol.

### Added — Workspace modes

- **`workspace.mode`** in `researcher_config.yaml` (+ `research-os init
  --workspace-mode`, and a wizard "What are you building?" step):
  `analysis` (default, unchanged) · `tool_build` · `exploration` ·
  `notebook` · `multi_study`. A `SCAFFOLD_PROFILES` registry scaffolds each
  shape; state, router, and audits dispatch on the active mode.
- **`tool_build` mode** — Research OS governs an inner project from above:
  `spec/` + `decisions/` (ADRs) + `eval/` (the harness that defines "done")
  + `milestones.md` + `governance.md`, with the tool itself in an inner dir
  that gets its OWN `git init`. "Done" = tests + build + eval pass.
- **`build/` protocol family** — `spec_and_design` → `implement_iteration`
  (loop) → `test_strategy` → `benchmark_vs_baseline` → `release_and_changelog`.
  Plus `exploration/` (triage → loop → promote-to-step) and `notebook/` +
  `program/` orienting protocols.
- **`tool_git`** (inner-repo version control; commits stamped with the RO
  step for provenance), **`tool_build`** (configured build/test/lint
  runner), and **`tool_audit(scope='tool', dimension=tests|git_hygiene|build)`**.

### Added — Rigor that is actually enforced

- **`tool_finalize_project`** — a server ship-gate that HARD-BLOCKS "done"
  on unresolved audit blockers, cited-but-invalid PDFs, ungrounded numbers,
  or stub sections, unless a logged researcher override clears it.
- **PDF integrity** — literature downloads are validated by the `%PDF-`
  magic header; a renamed 403/HTML page is deleted + recorded, never counted
  as a paper. Every PDF count uses magic validation, not `glob("*.pdf")`.
- **Substrate-checked grounding** — `tool_verify` now checks a claim against
  its cited file (a number is "verified" only if the source actually
  contains it; self-asserted support becomes "unverified").

### Added — Beginner ↔ PI gradient

- **`tool_explain`** — a layered, grounded tutor (intuition → mechanics →
  caveats → when-not-to-use → reading list) for any skill level.
- **`tool_deliverable_chooser`** — an `output_types`-gated "I'm done, what
  now?" on-ramp.
- **Mode-scoped tool listing** — the per-turn catalog shrinks from 151 to
  ~113–128 tools.
- **Router overhaul** — beginner-vocabulary layer ("i have a csv what do i
  do", "make a chart", "is my result significant"), a confidence-margin gate
  that asks instead of confidently misrouting, capped reckless single-word
  triggers, mode-aware routing bias, and `workflow_shape` as a routing signal.

### Improved

- **Every protocol** swept for doctrine compliance: hardcoded thresholds /
  method menus / canned step sequences replaced with "name-the-dimension +
  cite-the-source" scaffolds; scope-tag mislabels fixed; `see_also`
  cross-links added.
- Typst deliverables compile across all 12 venues (uniform `template`/`conf`).
- Audits read the real `synthesis/paper.typ` (dual Typst + Markdown), so the
  rigor gates no longer silently no-op.
- New researcher docs: `TOOL_BUILDER.md`, a beginner on-ramp in `START.md`,
  workspace modes documented across the guides.
- New `scripts/lint_coherence.py` preflight gate: docs/templates can no
  longer reference a removed tool or hand-write a tool/protocol count.

### Fixed

- All 7 IDE rule templates + docs purged of removed-tool references
  (`tool_plan_*`, `tool_synthesize`/`dashboard`/`figure`, `tool_grounding_*`).
- `synthesis_check` no longer reports success on a message-less error.
- 11 broken documentation cross-references.

### Behaviour changes that may affect existing projects (why this is MAJOR)

- A project with placeholder/HTML files named `*.pdf` will see them no
  longer counted as literature — the literature gate may newly fire (add a
  real PDF, or override with a rationale).
- `tool_finalize_project` can refuse to finalize a project with unresolved
  blockers; previously every blocker was advisory.
- `tool_verify` returns `unverified` for self-asserted claims that do not
  resolve to a cited source.
- New field `workspace.mode` defaults to `analysis`; existing projects keep
  classic behaviour with no change.

### Migration

- Analysis projects upgrade with no changes (mode defaults to `analysis`,
  byte-identical scaffold). Re-run `research-os init --refresh` to pick up
  the updated `AGENTS.md` / IDE rules.
- The planned tool-cluster consolidations (merging the SLURM / exec / route
  families; `sys_path` → `sys_step`) are deferred to 3.1.0 and will ship with
  aliases so no call site breaks.

---

## [2.4.4] — figure + dashboard style polish (2026-06-10)

PATCH release. Lifts the visual quality of both the figures AI produces
and the dashboard chrome that surrounds them to match a published
Research-OS reference deliverable (cream background, italic serif
titles, muted CVD-safe accent palette, value-labels-above-bars, clean
spines, generous whitespace). Also turns the loose "look at the
rendered figure" guidance into a mandatory render → view → v2 loop so
the AI can no longer ship a figure it never opened.

### Added

- **`research_os.tools.actions.viz.style`** — new module exporting
  the Research-OS publication style preset for matplotlib:
  - `apply_research_os_style(destination=..., palette=...)` —
    one call sets rcParams (cream bg, serif typography, dropped
    spines, dotted horizontal grid, constrained_layout on,
    300 dpi save) and returns a context dict with the destination
    figsize + palette so the AI's first render lands close to
    publication-ready. Destinations: `single_col` / `two_col` /
    `full_width` / `slide` / `slide_half` / `dashboard` /
    `dashboard_tile` / `poster`.
  - `RO_PALETTE` — five muted CVD-safe accents
    (navy `#1F4D7A`, olive `#9B7E2D`, forest `#3F6049`, oxblood
    `#9B3737`, mustard `#C3A14E`) plus a diverging emphasis pair
    (oxblood / forest) and a neutral chrome set
    (cream / warm-dark / muted / hairline).
  - `DESTINATION_FIGSIZES` — pre-tuned `(width, height)` for every
    destination so the AI doesn't pick a 6×4 default that crops at
    print size.
  - `label_bars_above(ax, bars, unit="ms")` — italic value labels
    floating 2 % above each bar, matching the reference figure
    aesthetic (`467 ms`, `128 ms`, …). Reserves headroom so the
    label doesn't crash into the next bar in a stacked chart.
  - `label_diverging_bars(ax, bars, values)` — signed delta labels
    coloured forest (positive) / oxblood (negative) for the
    diverging-bar comparison panel.
  - `polish_axes(ax)` — re-asserts top + right spine off and
    dotted horizontal grid on a specific axes after the AI built
    the chart.
  - `apply_suptitle(fig, title, subtitle=...)` — italic serif
    suptitle + smaller subtitle line, positioned to never overlap
    constrained_layout.
  - Graceful import: when matplotlib isn't installed, the module
    still imports and returns `applied=False` from
    `apply_research_os_style` instead of raising.
- **`first_render_spacing_discipline:`** block in
  `visualization/figure_guidelines` — a 9-item upfront discipline
  (pick destination, leave y-margin for value labels, plan legend
  placement, decide tick rotation, reserve suptitle headroom) so the
  FIRST render doesn't need a v2 to fix spacing. Calls out the
  matplotlib `tight_layout()` ↔ `constrained_layout` conflict.
- **`visually_verify_render` step** in
  `visualization/visualization_workflow` — the workflow's
  counterpart to the strengthened `pre_publish_self_review` step in
  `figure_guidelines`. Both protocols now teach the same mandatory
  render → open the PNG → check overlap / clipping / legend
  placement / palette cohesion → write v2 if anything fails → only
  ship v_final loop.
- **Research-OS accent palette in `audit_color_palette`** — the
  five RO_PALETTE accents + the neutral chrome colours are now in
  the allowed-palette set, so dashboards built from the new
  scaffold and figures generated through `apply_research_os_style`
  no longer trip the out-of-palette warning.

### Changed

- **`synthesis/scaffold._DASHBOARD_HTML`** — full CSS rewrite to
  match the reference figure aesthetic. Cream background, two-font
  stack (EB Garamond serif for titles + figure captions, Inter sans
  for body), italic serif `h1` / `h2` / `h3` / table headers, muted
  accent palette as CSS variables (`--accent` navy, `--accent-gold`
  olive, `--accent-green` forest, `--accent-red` oxblood,
  `--accent-mustard`), hairline rule colour for separators,
  near-white cards on cream, italic `figcaption` for figure
  interpretation, print-friendly fallback retained. Adds an
  `.eyebrow` line and a `.lead` paragraph class in the hero so the
  TL;DR has room to breathe.
- **`visualization/figure_guidelines`** (v2.0.0 → v2.4.4) — adds the
  `research_os_style_preset` reference block, the
  `first_render_spacing_discipline` rules, the new `set_up_canvas`
  step (call `apply_research_os_style` BEFORE writing the chart
  code), and rewrites `pre_publish_self_review` into the mandatory
  open-the-PNG view loop with explicit `sys_file_read filepath=...`
  instructions and a 14-item OBSERVATION checklist that the human
  eye must verify against the rendered pixels.
- **`visualization/visualization_workflow`** (v2.0.0 → v2.4.4) —
  inserts `visually_verify_render` after `build_each_figure` so the
  on-demand figure workflow inherits the same loop. Updates
  `build_each_figure` to mention `apply_research_os_style` + the
  spacing discipline.
- **`synthesis/synthesis_dashboard`** (v2.4.3 → v2.4.4) — adds a
  "visual cohesion with the figures" principle pointing at
  `apply_research_os_style()`; bumps version.

### Test gate

- **`tests/unit/test_viz_style.py`** — new file covering the style
  preset surface (palette has 5+ entries, DESTINATION_FIGSIZES has
  the expected destinations, `apply_research_os_style` returns the
  context dict, helpers no-op safely without matplotlib bars).
- **`tests/unit/test_v244_dashboard_style.py`** — new file covering
  the dashboard CSS rewrite (cream bg + accent palette present in
  scaffold, section IDs preserved, print stylesheet retained, new
  accent palette passes `audit_color_palette` without warnings,
  protocol YAMLs updated with the new spacing + view loop language).
- preflight passes · pytest passes · ruff clean.

### Not behaviour change for existing projects

- Pre-v2.4.4 dashboards on disk are untouched — the new CSS only
  applies to scaffolds created after upgrading. Re-scaffold with
  `tool_synthesis_scaffold(kind='dashboard', overwrite=true)` to
  adopt the new style.
- The style preset is opt-in. Plotting scripts that don't import
  `apply_research_os_style` continue to render with matplotlib
  defaults. The `figure_guidelines` protocol recommends adopting
  the preset for visual cohesion with the dashboard, but doesn't
  reject figures that depart from it (journal templates win).

---

## [2.4.3] — output_types gating + scope-creep fix (2026-06-09)

PATCH release. Closes two architectural holes that the v2.4.2
ontology-mapping audit surfaced as the root cause of "AI auto-creates
deliverables the user didn't ask for":

1. **The synthesis pipeline was hardcoded to `synthesis_paper`.**
   `get_next_protocol()` in `tools/actions/protocol.py` ran a fixed
   9-step PIPELINE ending at `synthesis_paper` regardless of the
   researcher's declared `research_goal.output_types`. A project whose
   wizard answer was `output_types: [dashboard]` still saw "next is
   `synthesis_paper`" from the loader. Fixed: pipeline is now the
   universal analysis prefix + a synthesis tail filtered by declared
   `output_types`. Empty `output_types` falls back to `synthesis_paper`
   (legacy behaviour preserved).
2. **`next_protocol` chains auto-fired in every autonomy mode.** Six
   protocols silently chained: `analysis_plan → reproducibility`
   (every analysis step triggered an audit), `audit_and_validation →
   synthesis_paper` (every audit triggered a paper draft),
   `reproducibility → audit_and_validation`,
   `cox_ph_diagnostics → audit`, `missing_data_strategy → audit`,
   `qualitative_quality_audit → audit`. Fixed: each chain now carries
   an explicit `AUTONOMY GATE` annotation telling the AI to suggest
   (not auto-chain) in `manual` / `supervised` / `coaching` modes.
   Single-step requests stop at the requested step.

Three parallel `Explore`-agent audits drove the fix. Reports captured
in chat transcripts (not checked in).

### Added

- **`output_types_gate(root, kind, *, autonomy=None)`** in
  `tools/actions/synthesis/check.py`. Returns
  `{verdict: 'proceed'|'ask'|'skip', declared_outputs, message, kind}`.
  - `proceed` when `output_types` is empty (no preference declared) OR
    `kind` is in the declared set.
  - `ask` when `output_types` is non-empty and `kind` is NOT in the
    set; the returned `message` is a one-line prompt the AI lifts
    verbatim to the researcher.
  - `skip` reserved for future use (researcher explicitly opted out).
  - Normalises aliases (`lay-summary` → `lay_summary`,
    `Lay Summary` → `lay_summary`) and ignores the `exploratory`
    sentinel (which marks "no deliverable yet").
- **`tool_synthesis_scaffold(kind, confirmed=false)`** — new
  `confirmed` kwarg. When the output_types gate returns `ask` and the
  caller has not passed `confirmed=true` (or the existing
  `overwrite=true`), the scaffold returns `status='ask'` instead of
  writing. The AI is expected to surface the message to the researcher
  and only re-call with `confirmed=true` after they say yes. Prevents
  the failure mode where the AI auto-creates a paper / dashboard /
  poster the user never asked for.
- **`SYNTHESIS_OUTPUT_TYPE_MAP`** in
  `tools/actions/protocol.py` — single source of truth mapping each
  `output_types` keyword (`paper`, `dashboard`, `poster`, `slides`,
  `report`, `lay_summary`, `grant`, `abstract`, `essay`, `handout`) to
  its synthesis protocol + "done" predicate. New synthesis protocols
  must register here to participate in pipeline filtering.

### Changed

- **`get_next_protocol(root)`** consults
  `inputs/researcher_config.yaml#research_goal.output_types`. The
  analysis prefix (session_boot → project_startup → domain →
  methodology → literature → analysis_plan → reproducibility →
  audit_and_validation) is unchanged. The synthesis tail is now
  dynamic — for `output_types: [dashboard, lay_summary]`, the
  pipeline terminates at `synthesis/synthesis_lay_summary` (in
  declared order), NOT `synthesis/synthesis_paper`. Empty list →
  fallback to `synthesis_paper` (no regression for unfilled projects).
  Response envelope gains `declared_output_types` field.
- **`tool_synthesis_check`** envelope gains an `intent_gate` field. If
  the kind being audited isn't in declared `output_types`, the gate's
  one-line message also appears in `warnings`.
- **`synthesis_paper`** (v2.3.0 → 2.4.3) — adds an explicit
  `verify_intent` first step that reads `output_types` and stops the
  AI if `paper` isn't declared. Closes the auto-create-paper failure.
- **`synthesis_dashboard`** (2.4.2 → 2.4.3) — same `verify_intent`
  first step for `dashboard`. Reinforces the existing trigger gate.
- **`synthesis_slides`** (2.3.0 → 2.4.3) — `slides` prerequisite added.
- **`synthesis_lay_summary`** (2.4.2 → 2.4.3) — `lay_summary`
  prerequisite added.
- **`printable`** (2.3.0 → 2.4.3) — `poster` / `handout` prerequisite
  added.
- **Autonomy-gate annotations** added to the six high-risk
  `next_protocol` chains (`guidance/analysis_plan` →
  `reproducibility/reproducibility`; `audit/audit_and_validation` →
  `synthesis/synthesis_paper`; `reproducibility/reproducibility` →
  `audit/audit_and_validation`; the three `methodology/*` audits →
  `audit/audit_and_validation`;
  `visualization/interactive_dashboard_design` →
  `synthesis/synthesis_dashboard`). Each carries a comment block
  telling the AI to surface "Next: ..." as a SUGGESTION in
  `manual` / `supervised` / `coaching` modes; only `autopilot`
  auto-chains, and `autopilot` further gates synthesis chains on
  `output_types` membership.

### Test cleanup

- **Renamed** `tests/unit/test_v242_synthesis_dashboard_lints.py`
  → `tests/unit/test_synthesis_check.py`. Per-release test naming
  (`test_v<version>_<feature>.py`) is now retired as a convention;
  new tests for this surface land in the topic-named file.
- **+13 regression tests** in the renamed file covering:
  output_types_gate proceed / ask / empty / alias-normalisation /
  exploratory-sentinel; synthesis_scaffold returns `ask` / honours
  `confirmed=true` / proceeds for declared kinds; pipeline tail
  respects dashboard-only / paper+lay_summary / empty-fallback;
  synthesis_check envelope includes the intent_gate field.

### Test gate

- preflight 29/29 · pytest 1643/1643 (+13 new in
  `test_synthesis_check.py`) · ruff clean.

### Not behaviour change for existing projects

- Projects with `output_types: []` (or no `researcher_config.yaml`)
  see the legacy fallback: synthesis_paper terminal, no `ask`
  envelopes. This is the on-disk default for every project initialised
  before v2.4.3 and for every fresh `research-os init` until the
  researcher fills in `output_types`. Recommendation: update the
  wizard answer once to make the intent explicit.
- The AUTONOMY GATE annotations are guidance to the AI, not
  loader-enforced refusals (which would be MINOR-shaped). An AI client
  that ignores them will still see the same `next_protocol` values it
  did in v2.4.2; correct AI behaviour is now spelled out in the
  protocol text + the new gate helper.

---

## [2.4.2] — dashboard quality + synthesis hygiene (2026-06-09)

PATCH release. Six fixes driven by an audit of the
`/scratch/vsetlur/ontology-mapping` v2.1 synthesis run, which surfaced
a recurring failure mode: the AI authoring a slap-together dashboard
(one section per workspace step, figure + caption underneath each),
inventing non-canonical filenames (`paper-lay.md`, `REPRODUCIBILITY.md`,
`METHODS.md`, `CITATIONS.md`) in `synthesis/`, and leaving behind
random `.md` / `.mermaid` / `.json` clutter at `workspace/` root. All
fixes are protocol guidance, scaffold rewrites, lint additions, and
one tool-mode extension; no breaking changes to existing APIs.

### Changed

- **`synthesis/synthesis_dashboard` — rewrite (v2.3.0 → v2.4.2).**
  The protocol now explicitly forbids the per-step recap antipattern
  and requires a custom, story-driven structure: Hero / Headline →
  Key findings (organised by claim, not by step) → Comparison
  (adopted vs ruled out) → Methods → Limitations → References.
  Introduces an explicit choice between Plan-mode (collaborative
  outline) and Autopilot (AI picks the headline finding and structure)
  before scaffolding. Quality bar now lists `forbidden_structure`
  (per-step recap, directory dump, caption-only sections) and
  `required_structure` (hero + ≥3 claim-driven findings sections).
- **`synthesis/synthesis_paper` — clarification (v2.3.0 → v2.4.2).**
  States explicitly that `synthesis/paper.pdf` is mandatory before the
  paper deliverable is "done" (a stranded `paper.md` with no rendered
  PDF is a blocker). Lists the four most common AI-improvised
  filenames that downstream tools do NOT recognise (`paper-lay.md`,
  `REPRODUCIBILITY.md`, `METHODS.md`, `CITATIONS.md`) and points each
  at its canonical destination.
- **`synthesis/synthesis_lay_summary` — clarification (v2.0.0 → v2.4.2).**
  Canonical filename is `synthesis/lay_summary.md` (not `paper-lay.md`,
  `lay.md`, `summary.md`, `paper_lay.md`); downstream tools recognise
  only the canonical name.
- **`writing/writing_conclusions` — figure/table citations (v2.0.0 →
  v2.4.2).** Per-step `conclusions.md` template gains a mandatory
  **Figures + tables produced** section that lifts directly into
  paper / dashboard / slides synthesis. Every Findings bullet must
  cite at least one figure / table / output file produced by the
  step; an unciteable finding is rejected. The Statistical summary
  table gains a `Source` column. Closes the gap where downstream
  synthesis stages had to guess which figures backed which findings.
- **`tool_synthesis_curate_figures` — multi-figure curation.** New
  `mode` parameter: `'focal'` (default, unchanged behaviour — one
  focal figure per step, named `figNN_<slug>.png` for paper.typ) and
  `'all'` (every figure in every step's `outputs/figures/`, named
  with the step number prefix, plus every figure's caption sidecar
  copied or seeded). The `'all'` mode fixes the failure where the
  AI bypasses curation and writes step figures directly to
  `synthesis/figures/`, leaving them without `.caption.md` sidecars.
  Backwards-compatible: omitting `mode` keeps the v2.4.1 behaviour.

### Added

- **`synthesis_check` — story-structure lints for dashboards.**
  Three new checks on `synthesis/dashboard.html`:
    1. BLOCKER on ≥4 `Step NN` section headings (per-step recap
       antipattern). Tolerates up to 3 (a comparison block
       referencing specific steps is fine).
    2. WARN on 2-3 `Step NN` headings (graduated nudge to
       claim-driven headings).
    3. WARN on missing hero / TL;DR / headline-finding section in
       the first viewport (any of "Headline", "TL;DR", "Hero",
       "Key finding(s)", "Summary", "Top-line", "Bottom line",
       "At a glance" as heading text or section id satisfies it).
- **`synthesis_hygiene` — synthesis-directory filename lint.**
  Every `tool_synthesis_check` call now also walks `synthesis/` for
  non-canonical files and surfaces per-file rename / delete hints.
  Recognises the four most common AI-improvised names from the
  ontology-mapping audit (`paper-lay.md` → `lay_summary.md`;
  `REPRODUCIBILITY.md`, `METHODS.md`, `CITATIONS.md` → delete and
  fold into canonical artefacts). Unknown filenames get a softer
  "move to archive/ or fold into canonical deliverable" warning.
  Subdirectories (`figures/`, `archive/`, `scripts/`,
  `dashboard_data/`, `_typst_templates/`) are ignored.
- **`workspace_hygiene` — workspace-root clutter lint.** Every
  `tool_synthesis_check` call now also walks `workspace/` for loose
  files / subdirectories outside the canonical set (`methods.md`,
  `analysis.md`, `citations.md`, `researcher_certifications.yaml` +
  the `logs/`, `scratch/`, `archive/`, `.preregistration/`, and
  numbered `NN_<slug>/` directories). Loose planning docs, hand-rolled
  audits, `.mermaid` diagrams, and agent briefs at workspace root get
  per-file relocate hints (move to `scratch/`, `logs/`, or
  `archive/`).
- **Dashboard scaffold rewrite.** `tool_synthesis_scaffold(kind='dashboard')`
  now writes a story-arc skeleton: hero section with metric-card
  grid + interpretive caption slot, key-findings block organised by
  claim, comparison block for adopted-vs-rejected, methods block
  linking to paper.pdf, limitations + open questions, references +
  cite. CSS is inline and CVD-aware. The previous scaffold's
  per-section `<!-- AI: ... -->` markers explicitly warn against
  per-step recap and step-numbered headings.

### Test gate

- **`tests/unit/test_v242_synthesis_dashboard_lints.py`** — 9 new
  regression tests covering: dashboard step-by-step recap BLOCKER,
  hero-section absence WARN, story-driven structure passes,
  `synthesis_hygiene` flags `paper-lay.md` / `REPRODUCIBILITY.md` /
  `METHODS.md` / `CITATIONS.md` with the right rename hints,
  `workspace_hygiene` flags `v2_1_*.md` / `tools.md` /
  `workflow.mermaid` / `step_completeness_audit.{md,json}` /
  loose subdirectories, `curate_figures(mode='all')` curates every
  figure with caption sidecars, `curate_figures(mode='focal')`
  default unchanged, unknown `mode` rejected.
- 1630 tests pass (was 1621 in v2.4.1; +9 new).

### Not behaviour change

- The `synthesis_check` BLOCKER list grew by one (≥4 `Step NN`
  headings). Projects that *want* a per-step structure can either
  cap to ≤3 such sections (a comparison block referencing 2-3 steps
  is fine) or set the dashboard mode to a printable / handout
  artefact (those protocols don't run the per-step lint).
- `tool_synthesis_curate_figures` continues to default to `'focal'`
  mode; no behaviour change for callers that don't pass `mode`.

---

## [2.4.1] — deferred v2.4.0 follow-ups (2026-06-09)

PATCH-then-some release. Lands five of the items the v2.4.0
CHANGELOG explicitly deferred (one of them — `research-os refresh` —
is technically a new CLI subcommand and so a borderline MINOR
addition; the rest are pure cleanups). Shipped as 2.4.1 because the
combined surface change is small and additive: no existing project
or caller breaks; readers + writers stay tolerant; old field names
migrate silently.

### Added

- **`research-os refresh`** — new CLI subcommand. Detects drift
  between a project's copies of bundled templates (`AGENTS.md`,
  `CLAUDE.md`, `.claude/rules/research-os.md`, IDE rule files) and
  the version shipped with the installed `research-os` package.
  Read-only by default; `--check` exits non-zero on drift (CI-friendly);
  `--write [--yes]` overwrites drifted project copies; `--json` emits
  machine-readable output; `--regen-readme` also rebuilds the project-
  root README.md from current state. Smoke-tested against the
  `/scratch/vsetlur/ontology-mapping` project that drove the v2.4.0
  audit: correctly flagged the +13-line AGENTS.md drift from the
  rule #10 rewrite and the +1-line `.claude/rules/research-os.md`
  drift; flagged CLAUDE.md as identical; ignored un-wired IDE rules.
  Closes "no refresh CLI" deferred item.
- **`project_ops.regenerate_root_readme(root)`** — public helper that
  rewrites the project-root README.md with a "Project status" section
  listing actual on-disk numbered step folders (with a one-line
  summary cribbed from each step's README) plus any synthesis
  deliverables present (`paper.{typ,pdf}`, `slides.{typ,pdf}`,
  `poster.{typ,pdf}`, `dashboard.html`). Idempotent. Internal
  `_write_project_root_readme` gained a `force=False` kwarg so the
  wizard's skip-if-exists default is preserved.
- **Checkpoint retention tags.** `create_checkpoint(description, root,
  *, tag=None, keep=5)` now accepts an optional `tag` (e.g.
  `"release-candidate"`, `"before-major-refactor"`). Tagged checkpoints
  survive the per-create GC pass; untagged ones beyond `keep` are
  pruned. `.meta.json` schema gains an optional `tag` field;
  `list_checkpoints` surfaces it.
- **Per-create checkpoint GC.** `create_checkpoint` now calls
  `_prune_old_checkpoints` immediately after writing the snapshot,
  surfacing the `{kept, removed, tagged}` report under `gc` in the
  return envelope. Previously the pruner only ran at numbered-step
  creation, so explicit `tool_checkpoint` chains accumulated unboundedly
  (audit found one project at 61 MB across 2 checkpoints on a <5 MB
  source tree).

### Changed

- **`step_summary.yaml` soft-deprecated.** `tool_path_finalize` still
  writes the file (downstream readers — synthesis, audits, doctor —
  consume it) but the emit now carries a deprecation banner naming
  the file as DERIVED from `conclusions.md`, AUTO-GENERATED, "do
  NOT edit by hand", and "slated for removal once readers migrate
  to parsing conclusions.md directly". The payload gains a
  `_derived_from: "conclusions.md"` field so machine readers can
  detect the soft-deprecation programmatically.
  `templates/step_summary.yaml.template` gets a matching DEPRECATION
  NOTICE at the top telling new protocol authors NOT to scaffold the
  file and pointing them at `conclusions.md` prose answers instead.
  The 4 protocols that currently scaffold this file (analysis_plan,
  qualitative_research, close_reading, proof_verification_workflow)
  stay unchanged for back-compat; their migration is queued.
- **Dead state-ledger fields dropped.** `checkpoint_history` and
  `rollback_history` were written every checkpoint / rollback but
  never read by any code path (the `.meta.json` sidecars in
  `.os_state/checkpoints/` are the authoritative log). `rollback()`
  no longer appends; `_migrate` strips both from older state files
  on load. Reduces in-state JSON bloat across long sessions.

### Not in this release (planned for v2.5.0 / v3.0)

The v2.4.0 deferral list shrank by 5; the remaining items either
require breaking schema changes or coordinated multi-file migrations:

- Full `step_summary.yaml` retirement (delete the writer + migrate
  the 4 protocols that scaffold the editable template to require
  prose in conclusions.md). Breaking for any external reader of the
  file → v3.0.
- `.preregistration/` + `.grounding/` directory removal (migrate
  content into per-step `preregistration.md` + `.os_state/grounding.jsonl`).
  Touches 20+ readers; needs a back-compat-tolerant migration
  pattern → v2.5.0.
- Auto-invoked finalize hook at end of synthesis flow (the helper
  exists now via `regenerate_root_readme`; wiring it to fire
  automatically requires changes to the synthesis check / compile
  tools) → v2.5.0.
- Per-step `logs/` removal + cross-step utility canonical home
  (`workspace/scratch/` IS used in practice; needs a positive
  convention before removing the catch-all) → v2.5.0.

### Verified

- **Preflight: 29/29 passed.**
- **Pytest: all green** (12 new tests across refresh CLI + checkpoint
  GC + tag retention).
- **Ruff: clean.**

### Bumped

- `pyproject.toml`, `src/research_os/__init__.py`, `CITATION.cff` to
  `2.4.1`.

---

## [2.4.0] — scaffolds as questions, not templates (2026-06-08)

MINOR release. Driven by a 10-perspective adversarial audit of a real
project run (`AUDIT_ontology_mapping.md`, 233 findings across 10
personas — PI, junior researcher, senior domain reviewer, fresh-AI
handoff, Research-OS architect, code-quality, organization, outputs
quality, docs, reproducibility/citations). The synthesis identified
v2.0–v2.3 as having succeeded at producing **consistent structure**
(every project gets the same folder layout) but failing at consistent
**substance** (auto-generated figure captions leaked into papers as
placeholder rows; hallucinated bibliographies survived to submission;
empty literature/ stubs read as "no citations needed" when really the
AI just hadn't downloaded any). v2.4.0 closes the highest-impact gaps
without breaking existing projects.

### Added

- **`audit_pdf_grounding(entries, root)`** in
  `tools/actions/synthesis/citations.py` — reports which citation
  entries have a downloaded PDF on disk vs which don't. Searches
  `inputs/literature/<key>.pdf`, `inputs/literature/<doi-slug>.pdf`,
  and `workspace/*/literature/<key>.pdf`. Returns
  `{grounded: [...], ungrounded: [{key, doi, url, title}, ...],
  count, grounded_count}`. Closes the audit's strongest unified
  finding (8/10 auditors): a project shipped 21 references in
  `synthesis/references.bib` while `find . -name '*.pdf'` returned
  zero results.
- **`require_pdfs` flag on `write_references_bib`** — when true, drops
  ungrounded entries from the bib and lists them at the file tail as
  commented-out `UNGROUNDED ENTRIES`. Default keeps every entry but
  adds a header comment noting how many lack on-disk grounding so the
  gap is visible at the bib level even without opting in.
- **`figures:` block in `researcher_config.yaml`** — three knobs
  (`svg_allowed`, `summary_sidecar`, `interactive_html_allowed`) that
  control the per-figure sidecar regime. All three default to a lean
  shape (no SVG, no auto-summary, interactive HTML allowed). Added to
  both `templates/researcher_config.yaml` and the in-code
  `CONFIG_TEMPLATE`, kept in sync by
  `test_config_template_matches_file`. `figures` registered in
  `docs/CONTRACT.md` A.3 stable-section list.
- **`validation_warnings` on `active_plan.json`** — `_persist_active_plan`
  now scans the decomposition for entries whose `tool` field is in
  `_REMOVED_TOOLS` (`tool_synthesize`, `tool_dashboard`,
  `tool_slides_create`, etc.) and writes a per-step warning. Surfaces
  stale router-index entries at plan-write time so the AI sees them
  before dispatching, not after burning a turn on the friendly
  redirect.

### Changed

- **Figure audit no longer warns "PNG without SVG companion"** by
  default. `audit_figure_quality` reads `researcher_config.figures.*`
  via the new `_load_figures_config` helper; the SVG warning fires
  only when `svg_allowed=true`; the summary-sidecar warning fires
  only when `summary_sidecar=true`. Drops a long-running source of
  false-positive noise.
- **`tool_path_finalize` stops auto-emitting `.summary.md` sidecars.**
  Plain-English interpretation now integrates into `conclusions.md`
  next to the inline `![](outputs/figures/<slug>.png)` embed. The
  auto-generated sidecars trained the AI to leave stub captions
  ("Auto-drafted caption: regenerate from analysis context") that
  leaked verbatim into one project's `synthesis/paper.md` as 92
  placeholder rows visibly telling reviewers the AI gave up. Opt back
  in via `figures.summary_sidecar=true`.
- **`AGENTS.md` hard rule #10 rewritten.** Replaces the "every figure
  carries four sidecars including an SVG companion" mandate with a
  lean default (`<slug>.png` + an authored `<slug>.caption.md`), opt-in
  SVG / summary sidecars, encouragement of interactive `.html`
  companions for visualisation types that benefit (networks,
  multi-panel dashboards), and an explicit requirement that the AI
  `sys_file_read` every figure before declaring a step done — catches
  legend-over-plot, missing axis labels, palette regressions,
  snake-case-leaking-into-label bugs that no JSON audit catches.
- **`_seed_step_subfolder_readmes` stops pre-creating stub READMEs**
  in `literature/`, `environment/`, and `context/` per step. These
  dirs stay in `EXPERIMENT_SUBDIRS` (paths exist) but are empty until
  a tool writes into them. Audit found pre-seeded stubs trained the
  AI to leave dirs as boilerplate; caused `literature/` to read as
  "no citations" when really the AI just hadn't downloaded any; and
  cluttered every step folder with content nobody wrote. The README
  that answers "what goes here?" now lives once in
  `RESEARCHER_GUIDE.md` rather than duplicated 14× on disk.
- **`outputs/README.md` template updated** to reflect the new figure
  contract: reports go DEEPER than `conclusions.md` (choices,
  reasoning, comparison of options); figures are `.png`-only by
  default with optional interactive `.html` companions; AI MUST read
  each figure before finalize.
- **Doc hardening: dropped hardcoded tool / protocol counts** across
  `README.md`, `docs/{TOOLS,PROTOCOLS,RESEARCHER_GUIDE,START,AI_GUIDE}.md`.
  Replaces "144 tools" / "117 protocols" with vague phrases
  ("~150 tools", "100+ protocols", "every tool", "All core protocols").
  CLAUDE.md doctrine already forbids hand-written counts; the
  maintainer was violating it in 9+ places. Counts go stale within a
  release. CONTRACT.md keeps its v2.0.0-anchored snapshot table.
- **Doc drift fix: `README.md:117` `code/` → `scripts/`.** The README
  showed `01_baseline_eda/code/` in its file-layout diagram while the
  framework, RESEARCHER_GUIDE, and every real project use `scripts/`.
  A junior researcher walking through README and then opening a real
  project would have hit the inconsistency immediately.

### Migration

- **Existing projects are unaffected by the figure default change**
  — `audit_figure_quality` still reads existing `.summary.md` and
  `.svg` files when they're present; the change is that it no longer
  *warns* on their absence. To restore the v2.3 warning behaviour,
  add to `inputs/researcher_config.yaml`:
  ```yaml
  figures:
    svg_allowed: true
    summary_sidecar: true
  ```
- **Existing per-step `literature/README.md` / `environment/README.md` /
  `context/README.md` stubs are not touched** — the change only
  affects newly-created steps. Delete the stubs by hand if you want
  empty dirs in legacy steps.
- **`write_references_bib` signature gained two optional kwargs**
  (`root`, `require_pdfs`). All existing positional calls keep
  working; opt-in to PDF filtering by passing both.
- **AGENTS.md template change does NOT propagate** to existing
  projects (the wizard only copies once). Re-run `research-os init`
  in a temp dir and diff the AGENTS.md against your project's copy
  to pick up the new hard rule #10 wording. A `research-os refresh`
  CLI subcommand to do this automatically is planned for 2.4.x.

### Not in this release (planned for 2.4.x / 2.5.0)

The full audit surfaced ~50 P0 framework changes; this release ships
the highest-impact subset that doesn't break existing projects. The
following remain for follow-up:

- Per-step `step_summary.yaml` retirement: the YAML stub anti-pattern
  flagged by 9/10 audits. The derived emit in `tool_path_finalize`
  stays in 2.4.0; the editable scaffold via `step_summary.yaml.template`
  + the `update_step_summary` step in `analysis_plan.yaml` /
  `literature_per_step.yaml` await migration to prompt-laden README
  prose.
- `.os_state` simplification: collapse `state_ledger.json` +
  `manifest.json` overlap, drop dead fields, bound checkpoint storage
  (single snapshot can be 39 MB of duplicate workspace; no GC).
- `research-os refresh` CLI subcommand: auto-upgrade
  `AGENTS.md` / `CLAUDE.md` / IDE-config templates in an existing
  project to match the bundled current version.
- Sparse-root finalize hook: regenerate top-level `README.md` at
  project finalize (currently write-once at init).
- Per-step `logs/` removal + cross-step utility canonical home
  (`workspace/scratch/` IS used in practice but the framework doesn't
  document a canonical place for it).
- Hard removal of `.preregistration/` + `.grounding/` hidden dirs in
  workspace (content moves into per-step README / methodology.md +
  `.os_state/grounding.jsonl`).

### Verified

- **Preflight: 29/29 passed.**
- **Pytest: all green.**
- **Ruff: clean.**

### Bumped

- `pyproject.toml`, `src/research_os/__init__.py`, `CITATION.cff` to
  `2.4.0`.

---

## [2.3.0] — guided synthesis (2026-06-08)

MINOR release. Retires the synthesis auto-generators in favour of
**AI-direct authoring**: the AI writes `synthesis/paper.typ` /
`slides.typ` / `poster.typ` / `essay.typ` / `dashboard.html` directly,
following the matching synthesis protocol. Tools validate and
compile; they no longer generate the prose / layout. The previous
auto-generators produced rigid, low-quality output — a 3MB
monolithic dashboard, a markdown-only paper intermediate, slide
decks no audience could read. Removing them moved 9700+ lines of
generator code out of the codebase and let the synthesis protocols
become true scaffolds (per `docs/PROTOCOL_DOCTRINE.md`).

### Breaking changes

The following tools were removed. Each returns a `_REMOVED_TOOLS`
redirect message naming the new protocol + surviving tools:

- `tool_synthesize` → follow `synthesis/synthesis_paper`; write
  `synthesis/paper.typ` directly; compile via `tool_typst_compile`.
- `tool_dashboard` (+ 7 operations: `create`, `story_generate`,
  `story_edit`, `story_quality_bar`, `reviewer_sim`, `test_generate`,
  `test_run`) → follow `synthesis/synthesis_dashboard`; write
  `synthesis/dashboard.html` directly.
- `tool_slides_create` → follow `synthesis/synthesis_slides`; write
  `synthesis/slides.typ` (Touying); compile via `tool_typst_compile`.
- `tool_poster_create` → follow `synthesis/synthesis_poster`
  (redirect to `synthesis/printable`); write `synthesis/poster.typ`.
- `tool_humanities_essay_scaffold` → use
  `tool_synthesis_scaffold(kind='essay')` + author content.
- `tool_paper_compile_typst` → use `tool_typst_compile` (generic .typ
  → .pdf; the AI authors the .typ directly, no markdown
  intermediate).
- `tool_section_substantiveness` → folded into
  `tool_synthesis_check(mode='substantiveness')` (now also handles
  Typst headings).
- `tool_figure` dispatcher and operations `caption_synthesise`,
  `interactive_autogen`, `paper_autoembed` → the AI authors plain-
  English figure summaries, interactive companions, and Typst
  `#figure(...)` blocks directly when writing the plotting script or
  paper.typ. `tool_figure_palette` is now a top-level tool.
- `tool_reviewer` operation `simulate` → the AI walks the paper
  through the persona YAMLs in `assets/reviewer_personas/` directly
  (`tool_reviewer` keeps `response`, `rebuttal`, `compile` for real
  external reviews).

The autopilot floor gate enforcement also shifted: `tool_typst_compile`
replaces `tool_synthesize` / `tool_dashboard(operation='create')` as
the final-deliverable gate.

### Added

- **`tool_typst_compile`** — generic Typst compiler. Takes any
  AI-authored `.typ` source (paper, slides, poster, essay,
  cover_letter, response_to_reviewers) and renders the PDF.
  Resolves bundled venue templates from `_typst_templates/`;
  auto-generates `synthesis/biblio.yml` from `workspace/citations.md`
  when missing. Returns `pdf_path`, `page_count`, `citation_count`,
  `typst_warnings`, `typst_errors`.
- **`tool_synthesis_check`** — quality audit for AI-authored
  synthesis files. Auto-detects file type from the path. Modes:
  `all` (default), `substantiveness`, `structure`, `accessibility`,
  `cliches`. Per-IMRAD-section content depth audits for paper /
  essay; slide-count + speaker-notes + path-leak audits for slides;
  section + headline + QR audits for poster; engineering invariants
  (offline, alt-text, semantic `<section id>`, no placeholders, no
  filesystem-path leaks) for dashboard.
- **`tool_synthesis_scaffold`** — writes a `<=80`-line skeleton
  `synthesis/<paper|slides|poster|essay>.typ` or `dashboard.html`
  with section headers + `// AI: author this section` markers.
  Idempotent (refuses overwrite without `overwrite=true`).
- **`tool_figure_palette`** — promoted from an operation under
  `tool_figure` to a top-level tool. Returns CVD-safe palettes
  (Okabe-Ito qualitative, viridis sequential, PuOr diverging,
  accent).

### Improved

- **Synthesis protocols rewritten as scaffolds.** `synthesis_paper`,
  `synthesis_dashboard`, `synthesis_slides`, `printable` (poster +
  handout), `humanities_essay_structure`, `synthesis_grant`,
  `synthesis_abstract`, `synthesis_report`, `synthesis_lay_summary`,
  `synthesis_progress_update`, `synthesis_from_inputs` — each
  collapsed from 100-370 lines of prescriptive recipe to <=130 lines
  of scaffold (design principles + quality standards + workflow +
  available tools). Spec files (`synthesis_spec.yaml`,
  `slides_spec.yaml`, `dashboard_spec.yaml`) are no longer required.
- **Cleaner `synthesis/` folder.** After a full project run:
  `paper.typ`, `paper.pdf`, `slides.typ`, `slides.pdf`, `poster.typ`,
  `poster.pdf`, `dashboard.html`, `biblio.yml`, `figures/`. No
  intermediate `.md` files, no spec YAMLs, no handout duplicates.
- **`researcher_config.yaml` schema simplified.** The `synthesis:`
  block is empty by default. Removed knobs:
  `figures_auto_embed*`, `figure_xref_rewrite`, `slide_engine`,
  `slide_template`, `slide_theme`, `slide_speaker_notes_enabled`,
  `slide_print_handout`, `poster_engine`, `poster_template`,
  `poster_theme`, `poster_qr_url`, `poster_handout_pdf`,
  `drafter_loop_*` (5 knobs).
- **`_router_index.yaml` v21.** Synthesis decompositions point at
  the new `tool_synthesize_plan` → `tool_synthesis_scaffold` →
  `tool_synthesis_check` → `tool_typst_compile` chain.

### Removed

- 9 implementation files under `src/research_os/tools/actions/synthesis/`:
  `dashboard.py` (1604 lines), `dashboard_app.py` (1424), `slides.py`
  (946), `drafter_loop.py` (850), `reviewer.py` (partial — `reviewer_simulate`),
  `figure_auto_embed.py` (747), `poster_typst.py` (697),
  `dashboard_humanities.py` (465), `dashboard_qualitative.py` (455),
  `humanities_essay.py` (212), `synthesize.py` (1374),
  `dashboard_story.py` (300). Total: ~9700 lines.
- `src/research_os/tools/actions/viz/dashboard_tests.py` (the
  Playwright scaffold for auto-generated dashboards).
- `src/research_os/assets/reveal/` (260 KB), `slide_templates/`
  (24 KB), `poster_templates/` (20 KB) — vendored assets only
  the removed generators consumed.
- 12 obsolete test files (`test_v191_dashboard_app`,
  `test_v190_dashboard_content`, `test_dashboard_humanities`,
  `test_dashboard_qualitative`, `test_v191_story_mode`,
  `test_slides_engine`, `test_poster_typst`, `test_drafter_loop`,
  `test_figure_auto_embed`, `test_humanities_essay_structure`,
  `test_synthesize_auto_proceed`,
  `test_synthesize_blocks_on_unresolved_findings`,
  `test_synthesize_uses_pack_sections`, `test_paper_drafter_loop`,
  `test_researcher_config_synthesis`,
  `test_audit_audit_figure_coverage`,
  `test_citation_retrieval_empty_response`,
  `test_audit_findings_explain`).

### Migration

Existing project files (`synthesis/paper.md`, `synthesis/dashboard.html`
from prior versions) are preserved as-is on disk. The new tools do
not regenerate them. To produce the new artefact next to the old:
ask the AI to follow the matching synthesis protocol (e.g. "redo the
paper as Typst") — it will author `synthesis/paper.typ` and you can
delete the old `paper.md` once you're happy with the new PDF.

Tool count: **148 → 144** (8 removed + 4 added). Protocol count
unchanged at **117 core**.

### Bumped

- `pyproject.toml`, `src/research_os/__init__.py`, `CITATION.cff`
  to `2.3.0`.
- 11 rewritten synthesis-related protocols to `version: '2.3.0'`.
- `_router_index.yaml` to `version: 21`.

---

## [2.2.0] — multi-perspective validation pass (2026-06-06)

MINOR release. Shipped after a 35-agent audit (10 researcher-domain
perspectives, 5 technical, 5 UX, 5 AI-model personas, 5 online-research,
5 meta-improvement) surfaced 119+ findings across 12 themes. The
synthesis selected v2.2.0 over v2.1.2 because 6 p0 + 12 p1 work-items
genuinely add tools and knobs rather than just polish.

### Added

- **`sys_where`** — ~30-token mid-session orientation snapshot
  (project_root, tier, active_plan position, unresolved BLOCK count,
  last protocol). Use instead of `sys_boot` when you only need to
  remember "where am I?".
- **`sys_export_ro_crate`** — emits `ro-crate-metadata.json` +
  `codemeta.json` at project root. Closes the FAIR-alignment claim
  that was unbacked in v2.0–v2.1. Discoverable by Zenodo, OSF,
  downstream RO-Crate consumers.
- **`sys_export_share_archive`** now bundles `ro-crate-metadata.json`
  + `codemeta.json` + `CITATION.cff` at archive root automatically.
- **Autopilot floor gates** (`research_os.server.autopilot_gate`) —
  8 floor gates enforce mandatory audits before tier advance, even
  in autopilot mode. Closes the bypass path where `autopilot=true`
  silently skipped block-severity findings.
- **`research-os mcp` / `research-os api-key` / `research-os completion`**
  CLI subcommands (4 → 7). `mcp` adds/removes external MCP server
  configs (memory, filesystem, github). `api-key` securely stores
  per-provider keys (chmod 600). `completion` emits shell completion
  for bash / zsh / fish (uses `argcomplete` when installed, falls
  back to a hand-rolled script otherwise).
- **`argcomplete>=3.0`** as the new `completion` optional extra
  (`pip install 'research-os[completion]'`) + included in `dev`.
- **`model_profile` + `ai.context_class` config knobs** —
  `researcher_config.yaml`'s `ai` section now carries
  `model_profile: small|medium|large` (controls protocol-detail
  level) and `context_class: short|long` (controls history-window
  size). `sys_boot` respects both.
- **`docs/SECURITY.md`** — new page documenting path-containment,
  autopilot floor gates, override rationale enforcement, the
  `.os_state/overrides.log` audit trail, and the boundary between
  trusted and untrusted MCP-tool inputs.
- **`research-os doctor`** expanded to 25+ checks (was 18+).
  New checks include: `tool_short_field_present`, `citation_cff_valid`,
  `external_pack_entrypoints`, `embeddings_fresh`, and
  `docs_referenced_scripts`.
- **22 work-item implementation report** ships in `docs/SECURITY.md`
  + this CHANGELOG entry as evidence of the multi-perspective audit
  that drove this release.

### Changed

- **Envelope normalization at the dispatcher.** Pack and adapter tools
  that previously returned the legacy `{"status", "data"}` shape are
  now upgraded to the v2.1.0 envelope by
  `research_os.server.envelopes._normalize_envelope`, invoked once in
  `dispatch._handle_tool_call`. Closes the v2.1.0 envelope gap for
  13+ pack + adapter tools in one place rather than per-tool. New
  pack code should call `_success` / `_error` directly per
  `docs/PLUGIN_AUTHORING.md`.
- **`RoError(what, why, next_action)` signature** loosened from
  keyword-only to positional. Matches the contract documented in
  `docs/CONTRACT.md` A.6.2 verbatim.
- **`did_you_mean` is namespace-aware** for the `sys_/tool_/mem_`
  prefixes. Typing `sys_X` now prefers other `sys_*` matches before
  cross-namespace.
- **Envelope adds `next_recommended_call_structured`** — a
  `{"tool": str, "arguments": dict}` form derived from
  `next_recommended_call` when parseable. Strict tool-loop clients
  dispatch this directly without re-parsing free-form text.
- **`override_rationale` enforcement** wired across 9 handler sites
  (synthesis_writing, synthesis_visual, audit_core, audit_gates,
  methodology, meta_workspace.sys_path_create,
  meta_workspace.sys_checkpoint_rollback, tool_step_complete,
  tool_path_finalize). Thin rationales (`'TODO'`, `'preview'`,
  single-word, <20 chars) are rejected before the underlying audit
  runs. Empty-rationale paired with override flag now returns an
  explicit error instead of silently no-opping.
- **`sys_file_*` path containment.** `sys_file_read`, `sys_file_write`,
  `sys_file_list`, and `sys_file_delete` now refuse paths that
  resolve outside the workspace root. Closes the host-FS escape
  (`../../etc/passwd`) that was reachable from any MCP client.
- **CLAUDE.md, FAQ.md, START.md** updated to current counts (preflight
  25+, doctor 20+, subcommands 7). Future drift is policed by the
  new `preflight_docs_consistency` test.

### Fixed

- **Test `test_audit_version_coherence_rejects_unknown_step_id`**
  updated to `pytest.raises((RoError, FileNotFoundError))` —
  `iteration._step_dir` now raises `RoError` per the contract.
- **`docs/CONTRACT.md` A.6.1** corrected: the `data` alias removal is
  slated for **v3.0.0** (not v2.2.0 as the row erroneously claimed).
  The alias is preserved in `_success` / `_error` through every v2.x
  release for back-compat with v2.0 callers.
- **`docs/CONTRACT.md` A.3** no longer lists `tool_stack` as a stable
  top-level `researcher_config.yaml` section — the key was never
  shipped in `templates/researcher_config.yaml`.
- **Internal work-item IDs (W##, FIX-#) stripped** from tool
  descriptions (`audit.py`, `meta.py`, `synthesis.py`) and
  user-facing docs (`SECURITY.md`, `FAQ.md`, `AI_GUIDE.md`,
  `AGENTS.md`). Inline `# W##:` source comments cleaned up
  (substance kept). Future leaks are caught by
  `test_tool_description_no_version_chatter`.
- **`docs/TOOLS.md` lists `sys_where` + `sys_export_ro_crate`** —
  both were callable but undocumented after Wave-D.
- **Tool count references** updated 146 → 148 across
  `docs/{TOOLS,AI_GUIDE,FAQ,RESEARCHER_GUIDE,CONTRACT,START}.md`.
  Doctor check count 14/18+ → 20+. START.md subcommand count
  4 → 7 with the full list.

### Removed

- **`dashboard_v2.py` / `dashboard_v2_humanities.py` /
  `dashboard_v2_qualitative.py` / `humanities_essay_scaffold.py`**
  deprecation shims (one-minor-cycle removal promised in v2.1.1).
  Canonical paths: `dashboard_app`, `humanities_essay`.

### Verified

- **Preflight: 29/29 passed.**
- **Pytest: 1894 passed, 13 skipped, 0 failed.**
- **Ruff: clean.**
- **5 independent validators** reviewed the diff by reading + reasoning
  (not pytest): logic, consistency, contract, UX, tests. Their
  2 blockers + 14 concerns were triaged and fixed before release.

### Migration

- No required code changes. Every addition is additive; the `data`
  envelope alias is kept. Tool argument names unchanged.
- If your code imported from
  `research_os.tools.actions.synthesis.dashboard_v2*` or
  `research_os.tools.actions.synthesis.humanities_essay_scaffold`,
  switch to `dashboard_app` / `humanities_essay` (the canonical
  modules). The shims were removed per the v2.1.1 deprecation
  promise.
- If you parsed `envelope["data"]`, that still works through every
  2.x release. Switch to `envelope["payload"]` before v3.0.0.

---

## [2.1.1] — Cleanup release (2026-06-06)

PATCH release. Pure cleanup — no behavior changes, no new tools, no
new protocols, no API or tool-signature changes.

### Changed

- Source files renamed to canonical names (no `_v2`, `_scaffold`,
  etc.): `humanities_essay_scaffold.py` → `humanities_essay.py`
  (back-compat shim kept at the old path through v2.2.0). The
  `dashboard_v2*.py` shims created in v2.1.0 stay in place for one
  more minor cycle per the migration table (removed v2.2.0). 11
  unit-test filenames dropped a redundant `_v2` suffix
  (`test_audit_audit_*_v2.py` → `test_audit_audit_*.py`,
  `test_router_output_v2.py` → `test_router_output.py`).
- `docs/` folder reduced to one file per concept, no version
  suffixes. Version-tagged historical reports + working-session
  scratchpads removed (preserved in git history; recover via
  `git show v2.1.0:docs/<file>`). Final shape: 22 markdown files +
  2 mermaid diagrams (`PROTOCOL_GRAPH.mermaid`, `workflow_dag.mermaid`).
- `docs/README.md` rewritten as a single audience-routing page
  (researchers / AI agents + plugin authors / maintainers +
  integrators).
- Root `README.md` release badge bumped to v2.1.1; deep links to the
  deleted V2_RELEASE_NOTES + MIGRATION_v1_to_v2 docs replaced with
  pointers to `CHANGELOG.md` (with `[2.0.0]` section hint where the
  context warrants it).
- Code + protocol comments swept for historical-version references:
  ~115 strips across 23 files (server, audit/state, synthesis/viz,
  cli + plugins, router_index protocols). 1 pure-historical block
  deleted. Git log + CHANGELOG carry version history; live doctrine
  stays focused on current behavior. Stable surfaces (e.g.
  `_REMOVED_TOOLS` migration data, the canonical replacement entry
  points) were KEPT — those name the version because the version is
  load-bearing user-facing data, not commentary.

### Added

- `.gitignore` entries blocking future creation of version-tagged
  docs + handoff scratchpads in `docs/`. Patterns added:
  `/docs/v*_handoff/`, `/docs/*_handoff/`, `/docs/AUDIT_v*.md`,
  `/docs/USABILITY_v*.md`, `/docs/CHANGELOG_DETAILED_v*.md`,
  `/docs/MIGRATION_v*.md`, `/docs/V[0-9]*.md`, `/docs/V[0-9]*/`,
  `/docs/audit_v*/`, `/docs/usability_v*/`, `/docs/PHASE_*.md`,
  `/docs/archive/`. Prevents the clutter from recurring; future
  sessions that try to write these paths get them silently ignored.

### Verified

- MCP wiring smoke (in `/tmp/ro_v211_mcp/`): `research-os init`
  scaffolds correctly, `.claude/mcp.json` writes the standard
  `research-os start` config, `research-os doctor` reports
  `mcp_configs_wired: pass`, `research-os start` boots cleanly,
  and `TOOL_DEFINITIONS` count (146) matches the v2.1.0 surface
  (unchanged).

### Migration

- No code changes required. Imports from old `_v2` paths still
  resolve via the deprecation shim (removed v2.2.0).
- Imports of `from research_os.tools.actions.synthesis.humanities_essay_scaffold import scaffold_humanities_essay`
  keep working via the new 2-line shim at the old path; update at
  your convenience to
  `from research_os.tools.actions.synthesis.humanities_essay import scaffold_humanities_essay`.
- Anyone with local edits to deleted docs: recover via
  `git show v2.1.0:docs/<file>` (or any tag where the file lived)
  and re-save outside the repo as a personal note.

---

## [2.1.0] — consistency + organization (2026-06-06)

**Tagline:** internal-consistency MINOR with honest validation.
v2.0.0 shipped the structural refactor; v2.1.0 standardizes the
surfaces — return envelope shape, error message pattern, dashboard
module naming, paper-pipeline doc — and field-validates the result
with 10 perspective agents × scenarios + 20 random natural-language
prompts. The initial Wave-D validation hit 5.54/10 avg and surfaced
18 fixes; 11 land in this release (the GREEN-gate blockers + the
quick HIGHs), 7 are tagged for v2.1.x patches with the gap honestly
acknowledged below — NO RATING PADDING.

### Added

- **v2.1.0 response envelope shape** (`status` / `payload` / `data`
  alias / `audit_findings` / `next_recommended_call` / `tier_transition` /
  `tokens_estimate` / `ro_version`). Backwards-compatible: handlers
  keep using `_success(data)` and the new fields auto-populate with
  sensible defaults. `payload` and `data` reference the same object
  for one minor cycle; `data` removed in v2.2.0.
- **`RoError(what, why=None, next_action=None)`** structured-error
  primitive at `research_os.server.errors`. The dispatcher catches it
  and renders the v2.1.0 error envelope with the parts on
  `payload.{what, why, next_action}`. The `next_action` clause is also
  promoted to envelope-level `next_recommended_call` so the AI has a
  literal next-call hint on every failure.
- **Did-you-mean suggestions** on unknown-tool dispatcher errors and
  on protocol-loader `FileNotFoundError`. Builds the nearest-3 list
  via `difflib`. Closes the top "typo dies silently" friction point
  from v2.0.0 validation.
- **`docs/PAPER_PIPELINE.md`** canonical model: `synthesis/paper.md`
  (AI-edited intermediate) → `paper.typ` (default, fast) or
  `paper.tex` (when `pdf_compile_engine: latex`) → `synthesis/paper.pdf`
  (researcher-facing). Per-pack section overrides documented. File-
  format invariants locked.
- **`docs/CONTRACT.md` §A.6.1 + §A.6.2** — formalizes the v2.1.0
  envelope shape stability promise + the `RoError` exception
  signature stability.

### Changed

- **Dispatcher exception handling** in `research_os.server.dispatch`
  now catches `RoError`, `KeyError`, `TypeError`, `FileNotFoundError`,
  and bare `Exception` in order — each emits a structured WHAT/WHY/NEXT
  envelope instead of bare stringified errors. Closes the documented
  v2.0.1 "wrap dispatcher KeyError" item.
- **Dashboard module names normalized** — `dashboard_v2.py` →
  `dashboard_app.py`; `dashboard_v2_humanities.py` →
  `dashboard_humanities.py`; `dashboard_v2_qualitative.py` →
  `dashboard_qualitative.py`. `render_dashboard_v2()` →
  `render_dashboard_app()`. `DASHBOARD_V2_CSS` → `DASHBOARD_APP_CSS`.
  Legacy `dashboard.py` (still alive as the `dashboard_legacy=true`
  fallback) keeps its name. Migration aliases left at the old paths
  for one minor cycle (removed v2.2.0).

### Deprecated

- `envelope["data"]` key — now an alias for `envelope["payload"]`;
  removed in v2.2.0. Migration table in
  `docs/MIGRATION_v2_0_to_v2_1.md`.
- `from research_os.tools.actions.synthesis.dashboard_v2 import ...` —
  migration shim re-exports from `dashboard_app.py`; removed in
  v2.2.0.

### Fixed

- (CodeQL) Three release-gate blockers fixed during the v2.0.0 ship
  ceremony: `cli.py:520` extraneous f-string; `test_v161_consolidation.py`
  monkeypatch path post-Phase-10 server split; `test_v160.py` lean
  variant test pollution under `_fresh_import()` test order.

### Validation

- **Phase 13 multi-perspective matrix.** 10 perspective agents (naive_ai,
  experienced_ai, undergrad, grad_dissertation, postdoc_audit,
  pi_review, industry, methodology_auditor, reproducibility,
  maintainer) × scenarios in `/tmp/ro_v21_validation/` + 20 random
  natural-language prompts. **Initial Wave-D rating: 5.54/10 avg**
  (lowest: pi_review 5.0; highest: experienced_ai 6.0). All 5 GREEN
  targets failed in the initial pass. See `docs/V21_VALIDATION_REPORT.md`
  for the full 10×6 grade matrix, friction-points-by-frequency,
  worst-prompt analysis, and v2.1.0/v2.1.x/v2.2.0 deferral list.
- **Phase 14 fix list** — 11 of 18 surfaced fixes landed (FIX-1, 2, 3,
  4-partial, 5, 8, 9, 11, 13, 14, 18). The five blockers flagged by
  ≥9/10 perspectives (envelope ro_version lie, envelope fields never
  populated, ghost tool refs in error/help advice, --ide none silently
  rejected, AGENTS.md teaches legacy names) are all closed.
- **Phase 15 mini re-validation** — 9 targeted spot-checks of the
  fixes hit, all PASS. See `docs/v21_handoff/PHASE_15_MINI_REVALIDATION.md`
  for the matrix + honest expected-rating projection (~7.0-7.5/10).
  A full 10-perspective re-run was deferred under release-ship time
  pressure; tagged for v2.1.1.

### Deferred to v2.1.x (acknowledged gap, NO PADDING)

The Wave-D report surfaced 7 fixes not landed in v2.1.0. These are
the gap between the 5.54 baseline + 9 fixes (~7.0-7.5 projected) and
the 8.5 GREEN target. Each will land as a v2.1.x patch:

- **FIX-6** — narrow handler-level `except Exception` so dispatcher's
  typed RoError catches actually fire (7/10 perspectives).
- **FIX-7** — migrate 13+ pack tools to the v2.1.0 envelope (5/10
  perspectives) — they currently return v2.0 `{status, data}`.
- **FIX-10** — extend AI_GUIDE.md / TOOLS.md / RESEARCHER_GUIDE.md
  with v2.1.0 envelope-field docs (4/10 perspectives).
- **FIX-12** — pack-context bias in router scoring (5/10 perspectives;
  architectural — will likely land as v2.2.0).
- **FIX-15** — flip causal-language detector default to observational
  (2/10 perspectives, BLOCK for methodology-audit use cases) — needs
  domain reviewer input on default thresholds.
- **FIX-16** — namespace-aware did-you-mean ranking (5/10 perspectives).
- **FIX-17** — re-tag `pre_submission_checklist` + `audit_and_validation`
  + `data_management_plan` as `[any]` not pack-specific.

### Documentation

- `docs/v21_handoff/V21_MASTER_PLAN.md` — wave layout + per-phase exit
  criteria.
- `docs/v21_handoff/PHASE_1_RENAMES.md`, `PHASE_2_ENVELOPE_AUDIT.md`,
  `PHASE_3_ERROR_AUDIT.md`, `PHASE_8_GATE_FIRING_MATRIX.md`,
  `PHASE_13_SCHEMA.md` — per-phase audit + planning artifacts.

### Deferred to v2.1.x / v2.2.0

- Phase 5 protocol taxonomy reorganization (117 protocols into a deeper
  navigable hierarchy) — needs a dedicated session; tracked for v2.2.0.
- Phase 6 router consolidation (slim `_router_index.yaml` 2027 → ≤500
  lines, semantic-primary + hierarchical-fallback) — needs Phase 5
  first; tracked for v2.2.0.
- Wire orphan audit gates `evalue` + `figure_coverage` (per
  `docs/v21_handoff/PHASE_8_GATE_FIRING_MATRIX.md`) — needs domain
  reviewer sign-off on thresholds; tracked for v2.1.x.
- 97 `except: pass` site sweep + 360 WHAT_ONLY raise sweep
  (per `docs/v21_handoff/PHASE_3_ERROR_AUDIT.md`) — RoError + dispatcher
  primitives are in place; per-site rewrites land as v2.1.x patches.

---

## [2.0.0] — release-prep (2026-06-06)

**Tagline:** comprehensive release — end-to-end coherent system, field-validated
by 20 independent agents across 4 perspectives × 5 scenarios, with measurable
improvements vs the v1.11.0 baseline on every cell of the matrix.

### Highlights

- **Tool surface collapsed 344 → 146 live (-58%)** with 80 backward-compat
  aliases + 78 deprecated aliases + 24 hard-removed (return `_REMOVED_TOOLS`
  envelope). 25-family consolidation pass via the proven `_ALIAS_PARAM_INJECTION`
  pattern — every legacy name keeps dispatching for the v2.0.x runway.
- **`server.py` 7,499-line monolith dissolved** into 32-module
  `src/research_os/server/` package (largest module: `tool_definitions/meta.py`
  at 579 lines, -92% from peak). Public API preserved end-to-end via
  `__init__.py` re-exports.
- **MCP `instructions` field on the `initialize` handshake** — names the
  canonical per-turn sequence (`sys_boot → tool_route →
  sys_protocol_get(format=summary) → sys_active_tools`) at the protocol
  layer so any MCP client surfaces the right startup ritual.
- **`sys_protocol_get` default `format` flipped `"full"` → `"summary"`** —
  the single biggest token-cost win (5–10× cheaper per-turn at ~300 tokens
  vs ~1.5–3K). MAJOR-breaking; pass `format="full"` to opt back in.
- **5 CRAFT-inspired structural additions** drove the rating lift beyond
  surface cleanup: (1) audit-as-data (every audit emits a JSON companion +
  `.audit_findings.jsonl` ledger queryable via
  `tool_audit_findings(operation=query|diff)`); (2) drafter review-rewrite
  loops on paper/slides/poster; (3) `research-os doctor` install + workspace
  health checks; (4) `docs/CONTRACT.md` stable-surface promise;
  (5) audience-segmented `docs/README.md` four-audience router.
- **Validation:** 20 agents × 4 perspectives × 5 scenarios. Mean
  `final_rating` moved **6.35 → 7.70 (+1.35; +21%)**, total HIGH-friction
  items **124 → 63 (-49%)**, first-5-turn HIGH **66 → 42 (-36%)**, deliverable
  rate 11/20 → 14/20 (+15 pp). Every cell improved, no regressions.
  Full report: [`docs/V2_VALIDATION_REPORT.md`](docs/V2_VALIDATION_REPORT.md).
- **YELLOW recommendation** — ship with documented caveats. The Phase 15
  GREEN gate targets (avg ≥ 9.5, HIGH ≤ 5, all four perspectives ≥ 9.0) are
  not met; they were calibrated against a hypothetical v3-grade product.
  Deeper structural gaps (domain-pack coverage for bioinformatics + systems
  benchmarks; pack-aware audit gates) carry over to v2.0.x patch +
  v2.1.0 minor per
  [`docs/V2_RELEASE_NOTES.md`](docs/V2_RELEASE_NOTES.md) §"Deferred".
- **Upgrade path:** most projects work unchanged via alias dispatch.
  Full instructions, breaking-change details, per-surface recipes, and the
  complete old→new tool table at
  [`docs/MIGRATION_v1_to_v2.md`](docs/MIGRATION_v1_to_v2.md).
- **Two v2.0.1 BLOCKER regressions surfaced by Phase 15b re-validation
  were fixed before tagging** (commits `0c45b79` + `b3b24a0`):
  `sys_tool_describe` `NameError` (`_resolve_tool_name` missing import
  after the Phase 10 server-package split) and
  `tool_audit(scope='synthesis', dimension='all')` bare `KeyError` on
  `paper_path` (now defaults to `'synthesis/paper.md'`). `Server()` also
  now reports the canonical `__version__` at the MCP initialize handshake.

### Added
- `tool_audit(scope=, dimension=)` unified per-dimension audit dispatcher and `tool_audit_findings(operation=query|diff)` ledger reader. Both share the existing `_ALIAS_PARAM_INJECTION` / `_DEPRECATED_ALIASES` machinery so the prior tool surface (`tool_audit_synthesis`, `tool_audit_step_completeness`, `tool_audit_findings_query`, etc.) keeps dispatching with the legacy behaviour preserved end-to-end. `tool_audit_quality_full` stays separate as the canonical aggregator.
- `tool_dashboard(operation=create|story_generate|story_edit|story_quality_bar|reviewer_sim|test_generate|test_run)` unified dashboard dispatcher. Single entry point for the seven previously per-operation dashboard tools; each legacy name routes through alias + param injection so existing callers, scripts, and protocols keep working unchanged.
- `tool_step(operation=iterate|iterations_list|revision_options|env_lock)` unified step-lifecycle dispatcher and `tool_step_pipeline(operation=define|run|status|diagram)` unified step sub-task pipeline dispatcher. Single entry points for the eight previously per-operation step tools; each legacy name routes through alias + param injection so existing callers, scripts, and protocols keep working unchanged. `tool_step_complete` stays standalone as the top-level end-of-step bundle.
- `tool_lessons(operation=record|consult|failure_record|failure_check|failure_list|dead_end|mistake_replay)` extended dispatcher for the entire "what went wrong / what did we learn" family, and `tool_reliability(operation=log_event|report)` unified reliability-log dispatcher. Single entry points for the seven lessons / failure-memory / dead-end / mistake-replay tools and the two reliability-log tools; each legacy name routes through alias + param injection so existing callers, scripts, and protocols keep working unchanged.
- `tool_sensitivity(operation=define|run)` unified sensitivity dispatcher and `tool_preregister(operation=freeze|diff)` unified preregistration dispatcher. Single entry points for the two previously per-operation sensitivity tools and the two previously per-operation preregister tools; each legacy name routes through alias + param injection so existing callers, scripts, and protocols keep working unchanged.
- `tool_reviewer(operation=simulate|response|rebuttal|compile)` unified reviewer-response dispatcher. Single entry point for the four previously standalone reviewer-response scaffold tools (`tool_reviewer_simulate`, `tool_response_to_reviewers`, `tool_rebuttal_draft`, `tool_reviewer_response_compile`); each legacy name routes through alias + param injection so existing callers, scripts, and protocols keep working unchanged.
- `tool_data(operation=sample|profile|convert)`, `tool_figure(operation=palette|caption_synthesise|interactive_autogen|paper_autoembed)`, and `tool_thought(operation=log|trace)` unified dispatchers. Single entry points for the three data tools, four figure helpers, and two ReAct trace tools previously exposed as per-operation surface; each legacy name routes through alias + param injection so existing callers, scripts, and protocols keep working unchanged.
- `tool_scratch(operation=write|run|list|clear)` and `tool_task(operation=run|status|list|kill)` unified dispatchers. Single entry points for the four scratch-sandbox tools and the four background-task tools previously exposed as per-operation surface; each legacy name routes through alias + param injection so existing callers, scripts, and protocols keep working unchanged.
- `sys_config(operation=get|set|validate)` and `sys_env(operation=snapshot|docker_generate)` unified dispatchers. Single entry points for the three researcher-config tools and the two environment tools previously exposed as per-operation surface; each legacy name routes through alias + param injection so existing callers, scripts, and protocols keep working unchanged.
- `docs/V2_MIGRATION_TABLE.md` — running ledger of every old→new tool consolidation (old name, new name, dispatch kwarg, value, status). First entry: the 26→3 audit-family collapse (phase-9-c1).

### Changed
- Audit family consolidated 26 → 3 tools (phase-9-c1). 23 per-dimension `tool_audit_*` tools collapse into `tool_audit(scope=, dimension=)`; the 2 findings-ledger tools collapse into `tool_audit_findings(operation=)`. Every legacy name is aliased + parameter-injected so older scripts, protocols, and researcher commands continue to produce identical output. `_ALIAS_PARAM_INJECTION` now accepts multi-kwarg specs (tuple of `(key, value)` pairs) so the audit family can inject both `scope` and `dimension` from a single alias.
- Dashboard family consolidated 7 → 1 tool (phase-9-c2). The seven per-operation `tool_dashboard_*` tools (`create`, `story_generate`, `story_edit`, `story_quality_bar`, `reviewer_sim`, `test_generate`, `test_run`) collapse into `tool_dashboard(operation=...)`. Legacy aliases continue to dispatch through the consolidated handler via `_ALIAS_PARAM_INJECTION`. Shipped protocol YAMLs (`synthesis/synthesis_dashboard`, `visualization/interactive_figure_design`, `audit/pre_submission_checklist`, `guidance/autopilot`) and `_router_index.yaml` rewritten to the canonical `tool_dashboard(operation='…')` surface so reviewer-facing guidance stays on the live names.
- Step family consolidated 8 → 2 tools (phase-9-c3). The four step-lifecycle tools (`tool_step_iterate`, `tool_step_iterations_list`, `tool_step_revision_options`, `tool_step_env_lock`) collapse into `tool_step(operation=...)`. The four step sub-task pipeline tools (`tool_step_pipeline_define`, `tool_step_pipeline_run`, `tool_step_pipeline_status`, `tool_step_pipeline_diagram`) collapse into `tool_step_pipeline(operation=...)`. Every legacy name is aliased + parameter-injected so older scripts, protocols, and researcher commands continue to produce identical output. `tool_step_complete` stays standalone as the top-level end-of-step bundle; `tool_step_literature_list` belongs to the literature/search family and is not consolidated here. Shipped protocol YAMLs (`guidance/analysis_plan`, `methodology/deep_domain_research`) and `_router_index.yaml` rewritten to the canonical `tool_step(operation='…')` / `tool_step_pipeline(operation='…')` surface so reviewer-facing guidance stays on the live names.
- Lessons + reliability family consolidated 10 → 2 tools (phase-9-c4). The pre-existing `tool_lessons` (which already absorbed `tool_lessons_record` + `tool_lessons_consult`) is extended to cover `tool_failure_record` (operation=`failure_record`), `tool_failure_check` (`failure_check`), `tool_failure_list` (`failure_list`), `tool_dead_end_lessons` (`dead_end`), and `tool_mistake_replay` (`mistake_replay`). The two reliability-log tools (`tool_reliability_log_event`, `tool_reliability_report`) collapse into a separate `tool_reliability(operation=log_event|report)` entry point. Every legacy name remains callable via alias + param injection. Shipped protocol YAMLs (`audit/audit_and_validation`, `guidance/session_resume`, `literature/literature_search`, `synthesis/synthesis_progress_update`) and `_router_index.yaml` rewritten to the canonical `tool_lessons(operation='…')` / `tool_reliability(operation='…')` surface so reviewer-facing guidance stays on the live names.
- Sensitivity + preregister families consolidated 4 → 2 tools (phase-9-c5). The two sensitivity tools (`tool_sensitivity_define`, `tool_sensitivity_run`) collapse into `tool_sensitivity(operation=define|run)`. The two preregister tools (`tool_preregister_freeze`, `tool_preregister_diff`) collapse into `tool_preregister(operation=freeze|diff)`. Every legacy name is aliased + parameter-injected so older scripts, protocols, and researcher commands continue to produce identical output. Shipped protocol YAMLs (`methodology/preregistration`, `methodology/missing_data_strategy`, `methodology/method_comparison`, `audit/audit_and_validation`, `audit/provenance_completeness`, `synthesis/synthesis_null_findings`) and `_router_index.yaml` rewritten to the canonical `tool_sensitivity(operation='…')` / `tool_preregister(operation='…')` surface so reviewer-facing guidance stays on the live names.
- Reviewer family consolidated 4 → 1 tool (phase-9-c6). The four reviewer-response scaffold tools (`tool_reviewer_simulate`, `tool_response_to_reviewers`, `tool_rebuttal_draft`, `tool_reviewer_response_compile`) collapse into `tool_reviewer(operation=simulate|response|rebuttal|compile)`. Every legacy name is aliased + parameter-injected so older scripts, protocols, and researcher commands continue to produce identical output.
- Data + figure + thought families consolidated 9 → 3 tools (phase-9-c7). The three data tools (`tool_data_sample`, `tool_data_profile`, `tool_data_convert`) collapse into `tool_data(operation=sample|profile|convert)`. The four figure helpers (`tool_figure_palette`, `tool_figure_caption_synthesise`, `tool_figure_interactive_autogen`, `tool_paper_figures_autoembed`) collapse into `tool_figure(operation=palette|caption_synthesise|interactive_autogen|paper_autoembed)`. The two ReAct trace tools (`tool_thought_log`, `tool_thought_trace`) collapse into `tool_thought(operation=log|trace)`. Every legacy name is aliased + parameter-injected so older scripts, protocols, and researcher commands continue to produce identical output. Shipped protocol YAMLs (`audit/pre_submission_checklist`, `guidance/analysis_plan`, `guidance/project_startup`, `methodology/data_management_plan`, `methodology/data_quality_audit`, `methodology/exploratory_data_analysis`, `methodology/missing_data_strategy`, `synthesis/synthesis_paper`, `visualization/figure_guidelines`, `visualization/interactive_figure_design`, `visualization/visualization_workflow`) and `_router_index.yaml` rewritten to the canonical `tool_data(operation='…')` / `tool_figure(operation='…')` / `tool_thought(operation='…')` surface so reviewer-facing guidance stays on the live names.
- Misc-family audit (phase-9-c8). The remaining `tool_<verb>_*` families flagged as natural sub-systems consolidate 8 → 2 tools: the four scratch-sandbox tools (`tool_scratch_write`, `tool_scratch_run`, `tool_scratch_list`, `tool_scratch_clear`) collapse into `tool_scratch(operation=write|run|list|clear)`; the four background-task tools (`tool_task_run`, `tool_task_status`, `tool_task_list`, `tool_task_kill`) collapse into `tool_task(operation=run|status|list|kill)`. The two `tool_quick_*` tools (`tool_quick_review` stages a paper-review markdown; `tool_quick_route` is the throwaway-intent classifier used to short-circuit protocol load) share a prefix only — no functional overlap — and are kept standalone. Every legacy name is aliased + parameter-injected so older scripts, protocols, and researcher commands continue to produce identical output. Shipped protocol YAMLs (`guidance/casual_exploration`, `guidance/chat_handoff`, `guidance/session_resume`, `guidance/autopilot`, `guidance/analysis_plan`, `methodology/deep_domain_research`, `methodology/reproduction_attempt`, `methodology/simulation_studies`) and `_router_index.yaml` rewritten to the canonical `tool_scratch(operation='…')` / `tool_task(operation='…')` surface so reviewer-facing guidance stays on the live names.
- SYS_* judgment pass (phase-9-c9). The `sys_*` MCP-level primitives were reviewed family-by-family. Two genuinely over-fragmented families consolidate 5 → 2 tools: `sys_config_get` / `sys_config_set` / `sys_config_validate` collapse into `sys_config(operation=get|set|validate)`, and `sys_env_snapshot` / `sys_env_docker_generate` collapse into `sys_env(operation=snapshot|docker_generate)`. Every other `sys_*` family is intentionally kept separate because each is a distinct primitive AIs need to find by name — discovery surface (`sys_boot`, `sys_active_tools`, `sys_protocol_*` ×6, `sys_help`, `sys_tool_describe`, `sys_state_get`), high-frequency file I/O (`sys_file_read` / `_write` / `_list` / `_delete` / `_validate_md`), checkpoint trio (`sys_checkpoint_create` / `_rollback` / `_list`), workspace pair (`sys_workspace_scaffold` / `_tree`), and the standalone interaction tools (`sys_session_handoff`, `sys_export_share_archive`, `sys_notify`, `sys_active_project`, `sys_dep_inventory`, `sys_semantic_tool_search`, `sys_packs_installed`, `sys_adapters_installed`). Every legacy name remains callable via alias + param injection. Shipped protocol YAMLs (`guidance/session_boot`, `guidance/project_startup`, `guidance/analysis_plan`, `methodology/cox_ph_diagnostics`, `methodology/pick_tool_stack`, `methodology/mixed_language_orchestration`, `methodology/reproduction_attempt`, `reproducibility/reproducibility`) and `_router_index.yaml` rewritten to the canonical `sys_config(operation='…')` / `sys_env(operation='…')` surface so reviewer-facing guidance stays on the live names.
- All shipped protocol YAMLs that previously referenced per-dimension audit tool names now reference the consolidated `tool_audit(scope='…', dimension='…')` / `tool_audit_findings(operation='…')` form (96 substitutions across 33 protocol files) so reviewer-facing guidance stays on the canonical surface.
- **MAJOR-breaking:** `sys_protocol_get` default `format` flipped from `"full"` to `"summary"` (phase-9-cross-cutting). Callers that previously did not pass a `format` argument received the entire YAML (~1.5-3K tokens per call); they now receive the ~300-token summary view. This is the single biggest token-cost win identified in the Phase-15a baseline. Callers who genuinely need the bulk payload must now pass `format="full"` explicitly. The schema default + handler default + AI orientation docs all updated together; the inputSchema now declares `"default": "summary"` so well-behaved clients see the new default automatically.
- Every `TOOL_DEFINITIONS` entry now carries two introspection fields — `status` (`live` | `alias` | `deprecated`) and `pack` (`core` | `<pack_name>`) — set automatically by `_annotate_core_tool_metadata()` for core tools and by `plugins/loader.py` + `adapters/loader.py` at registration time for pack / adapter tools. `sys_tool_describe` surfaces both so the router, list_tools, and any external tooling can filter without re-deriving the answer. 167 entries annotated (146 live + 21 alias from the consolidation overlap; 144 core + 23 from packs / adapters).
- Every shipped protocol YAML (153 files across core + the 5 bundled packs) now carries a `scope_tags` block — `domain` (e.g. `[biology, wet_lab]`, `[qualitative]`, `[any]`), `audience` (e.g. `[researcher]`, `[auditor]`, `[naive_ai]`), and `workflow_shape` (e.g. `[experiment_pipeline]`, `[proof]`, `[linear_essay]`, `[interview_study]`, `[systems_benchmark]`, `[any]`). The router uses these as a soft filter so the embedding-similarity ranking only competes within the project's declared scope.
- `tool_route` now returns a `recommended_action` field — a single-string hint naming the exact next tool to call (e.g. `"sys_protocol_get(protocol_name='guidance/project_startup', format='summary')"`). Saves the AI one round-trip of reasoning per turn.
- MCP `Server` instantiation now passes the `instructions=` field with the canonical per-turn sequence (sys_boot → tool_route → sys_protocol_get format=summary → sys_active_tools), so any MCP client that surfaces server-supplied instructions sees the right startup ritual without having to call sys_help.

### Deprecated
- Legacy per-dimension audit tool names — `tool_audit_assumptions`, `tool_audit_citations`, `tool_audit_claims`, `tool_audit_cliches`, `tool_audit_code_quality`, `tool_audit_coherence`, `tool_audit_cross_deliverable_consistency`, `tool_audit_dashboard_content`, `tool_audit_evalue`, `tool_audit_figure`, `tool_audit_figure_coverage`, `tool_audit_figure_full`, `tool_audit_figure_interactivity`, `tool_audit_figure_quality`, `tool_audit_power`, `tool_audit_prose`, `tool_audit_reproducibility`, `tool_audit_reviewer_responses`, `tool_audit_statistical_power`, `tool_audit_step_completeness`, `tool_audit_step_literature`, `tool_audit_synthesis`, `tool_audit_version_coherence`, `tool_audit_findings_query`, `tool_audit_findings_diff`. All continue to work via alias dispatch through v2.0.x; scheduled for hard-removal in v2.1.0 per `docs/V2_MIGRATION_TABLE.md`.
- Legacy dashboard tool names — `tool_dashboard_create`, `tool_dashboard_story_generate`, `tool_dashboard_story_edit`, `tool_dashboard_story_quality_bar`, `tool_dashboard_reviewer_sim`, `tool_dashboard_test_generate`, `tool_dashboard_test_run`. All continue to work via alias dispatch through v2.0.x; scheduled for hard-removal in v2.1.0 per `docs/V2_MIGRATION_TABLE.md`.
- Legacy step tool names — `tool_step_iterate`, `tool_step_iterations_list`, `tool_step_revision_options`, `tool_step_env_lock`, `tool_step_pipeline_define`, `tool_step_pipeline_run`, `tool_step_pipeline_status`, `tool_step_pipeline_diagram`. All continue to work via alias dispatch through v2.0.x; scheduled for hard-removal in v2.1.0 per `docs/V2_MIGRATION_TABLE.md`.
- Legacy sensitivity + preregister tool names — `tool_sensitivity_define`, `tool_sensitivity_run`, `tool_preregister_freeze`, `tool_preregister_diff`. All continue to work via alias dispatch through v2.0.x; scheduled for hard-removal in v2.1.0 per `docs/V2_MIGRATION_TABLE.md`.
- Legacy reviewer tool names — `tool_reviewer_simulate`, `tool_response_to_reviewers`, `tool_rebuttal_draft`, `tool_reviewer_response_compile`. All continue to work via alias dispatch through v2.0.x; scheduled for hard-removal in v2.1.0 per `docs/V2_MIGRATION_TABLE.md`.
- Legacy data + figure + thought tool names — `tool_data_sample`, `tool_data_profile`, `tool_data_convert`, `tool_figure_palette`, `tool_figure_caption_synthesise`, `tool_figure_interactive_autogen`, `tool_paper_figures_autoembed`, `tool_thought_log`, `tool_thought_trace`. All continue to work via alias dispatch through v2.0.x; scheduled for hard-removal in v2.1.0 per `docs/V2_MIGRATION_TABLE.md`.
- Legacy scratch + task tool names — `tool_scratch_write`, `tool_scratch_run`, `tool_scratch_list`, `tool_scratch_clear`, `tool_task_run`, `tool_task_status`, `tool_task_list`, `tool_task_kill`. All continue to work via alias dispatch through v2.0.x; scheduled for hard-removal in v2.1.0 per `docs/V2_MIGRATION_TABLE.md`.
- Legacy sys_config + sys_env tool names — `sys_config_get`, `sys_config_set`, `sys_config_validate`, `sys_env_snapshot`, `sys_env_docker_generate`. All continue to work via alias dispatch through v2.0.x; scheduled for hard-removal in v2.1.0 per `docs/V2_MIGRATION_TABLE.md`.

### Removed
- **Phase 14a — first-wave consolidation aliases hard-removed.** The 21 legacy tool names introduced as consolidation aliases in v1.6.1 have expired their 4-minor-version deprecation runway and are now removed. Calling any of them returns a friendly `_REMOVED_TOOLS` error envelope naming the canonical v2 entry point. Old plans, scripts, or third-party callers that still name these will see a clear migration message instead of a generic "unknown tool" error.
  - **Search cluster (5):** `tool_search_semantic_scholar`, `tool_search_pubmed`, `tool_search_crossref`, `tool_search_arxiv`, `tool_search_web` → call `tool_search(query=..., source='semantic_scholar'|'pubmed'|'crossref'|'arxiv'|'web')` instead.
  - **Plan cluster (3):** `tool_plan_turn`, `tool_plan_advance`, `tool_plan_clear` → call `tool_plan(operation='turn'|'advance'|'clear')` instead.
  - **Grounding / verify cluster (4):** `tool_grounding_register`, `tool_ground_from_context` → call `tool_ground(mode='explicit'|'from_context', ...)`. `tool_claim_verify`, `tool_grounding_verify` → call `tool_verify(scope='claim'|'project', ...)`.
  - **Lessons cluster (2):** `tool_lessons_record`, `tool_lessons_consult` → call `tool_lessons(operation='record'|'consult', ...)` instead. (Other lessons-family aliases remain deprecated for the v2.0.x runway.)
  - **Path cluster (3):** `sys_path_create`, `sys_path_abandon`, `sys_path_list` → call `sys_path(operation='create'|'abandon'|'list', ...)` instead.
  - **Memory cluster (4):** `mem_methods_append`, `mem_decision_log`, `mem_hypothesis_update`, `mem_analysis_log` → call `mem_log(kind='methods'|'decision'|'hypothesis'|'analysis', ...)` instead.
- The corresponding `TOOL_DEFINITIONS` entries and `_HANDLERS` entries were dropped (handler functions like `_handle_sys_path_create` remain in the module — they're called internally by the consolidated dispatchers via the legacy fallback path). `tool_log_decision`, the silent pre-v1.6.1 nickname that previously chained through `mem_decision_log → mem_log`, now resolves directly to `mem_log` with `kind='decision'` injected so the nickname keeps working.
- **Phase 14b — tikzposter LaTeX poster path hard-removed.** The legacy `create_poster()` + `_poster_tex_escape()` functions under `src/research_os/tools/actions/synthesis/latex.py` (387 lines) are deleted. `tool_poster_create` is unchanged on the surface (Typst engine is the only path); the `engine='latex'` branch in `_handle_tool_poster_create` now returns a structured error pointing callers at the Typst surface. The legacy `layout` / `audience` LaTeX-only kwargs are no longer documented (`engine` is retained on the schema for back-compat with a hard-error guard). `researcher_config.synthesis.poster_engine` is pinned to `"typst"` — the validator enum now rejects `"latex"`. Protocol `synthesis/printable` updated (`template: tikzposter` → `academic_36x48` / `academic_48x36` / `public_24x36` per audience; description text re-pointed at Typst). Router index summary + triggers updated. Docs (`PROTOCOLS.md`, `RESEARCHER_GUIDE.md`, `TOOLS.md`, `ROADMAP.md`) re-pointed at Typst. Test `test_legacy_tikzposter_path_still_works` replaced by `test_legacy_tikzposter_create_poster_is_gone` and the enum-shape test now asserts `"latex" not in synthesis.poster_engine`. `_REMOVED_TOOLS` entries added for `tool_poster_create_latex` / `tool_poster_compile_latex` (nicknames that were never real tools but a future caller might try). Audit of all other handlers in `server.py` found zero truly orphan handlers; every handler is referenced either by the dispatcher map or called internally by a Phase 9 consolidator.
- **Phase 14d — dead config fields removed.** Five `researcher_config.yaml` fields identified by the v1.9.2 Lens-7 audit as declared-but-never-read are removed from the on-disk template, the in-code `CONFIG_TEMPLATE` constant, and `docs/RESEARCHER_GUIDE.md`. None of these fields had any consumer in `src/`, `tests/`, or shipped protocols — the comments that claimed they were "Read by `methodology/pick_tool_stack`" were inaccurate. The `pick_tool_stack` protocol picks language + library purely from method + field-practice + literature signal; it never consulted these fields. Existing projects on prior versions that hand-set these keys are unaffected (the keys silently become unknown extras; `validate_config` does not enforce key membership).
  - **Runtime cluster (1):** `runtime.default_n_for_sampling` — no caller anywhere; `tool_data(operation='sample')` takes its `n` argument from the tool call, not from config.
  - **Tool-stack cluster (4):** entire `tool_stack:` block removed: `tool_stack.preferred_languages`, `tool_stack.allow_mixed_language_steps`, `tool_stack.field_practice_overrides_preference`, `tool_stack.cite_field_practice_when_choosing`. The `methodology/pick_tool_stack` protocol itself is unchanged — it asks the AI to pick based on method + literature signal + env compatibility, never consulting these config fields.
- Trivial dead-variable cleanup in `tools/actions/audit/audit.py:651` (`f_stat`, `f_p` from `het_breuschpagan` unpack are now `_f_stat`, `_f_p` — they were tuple-discard placeholders flagged by Lens-9 as the one real `vulture --min-confidence 80` finding still present after v1.9.3's larger sweep).

### Fixed
- `sys_tool_describe` `NameError` regression introduced by the Phase 10
  server-package split — `meta_routing.py` referenced `_resolve_tool_name`
  which wasn't re-exported from `_handlers_runtime.py`. Fixed in commit
  `0c45b79`: added the import + `__all__` entry so the introspection path
  works from the first `list_tools()` call.
- `tool_audit(scope='synthesis', dimension='all')` raised a bare
  `KeyError` on `paper_path`. Fixed in commit `0c45b79`: handler now
  defaults to `'synthesis/paper.md'` (matches what the `audit_synthesis`
  worker already assumes when callers omit the kwarg).
- MCP `Server()` instance now reports the canonical `__version__` at the
  MCP initialize handshake instead of hard-coding `'0.1.0'`. Fixed in
  commit `b3b24a0` (phase-13 follow-up).

### Validation
- **Phase 15b re-validation: 20 agents × 4 perspectives × 5 scenarios = 20
  independent runs against the v2.0.0 candidate.** Mean `final_rating`
  moved **6.35 → 7.70 (+1.35; +21%)**, total HIGH-friction items
  **124 → 63 (-49%)**, first-5-turn HIGH **66 → 42 (-36%)**, deliverable
  rate 11/20 → 14/20 (+15 pp). Every cell of the 4×5 matrix moved up by
  +0.7 to +1.9 points; no regressions in any of the 20 runs. Full
  per-perspective × per-scenario rating table, friction-event delta, the
  carryover deferral list (v2.0.1 patch / v2.1.0 minor / v3.0.0 major),
  and the YELLOW shipping recommendation at
  [`docs/V2_VALIDATION_REPORT.md`](docs/V2_VALIDATION_REPORT.md).

### Migration
- Most projects work unchanged — every consolidated tool name keeps
  dispatching via `_DEPRECATED_ALIASES` + `_ALIAS_PARAM_INJECTION` for
  the v2.0.x runway. Hard removal of the v2.0 deprecated aliases is
  scheduled for v2.1.0. Full instructions, breaking-change details,
  per-surface recipes, and the complete old→new tool table at
  [`docs/MIGRATION_v1_to_v2.md`](docs/MIGRATION_v1_to_v2.md) (the v1→v2
  upgrade guide) plus [`docs/V2_MIGRATION_TABLE.md`](docs/V2_MIGRATION_TABLE.md)
  (the running ledger of every old→new consolidation).
- Release-shaped overview, headline numbers, and YELLOW caveat at
  [`docs/V2_RELEASE_NOTES.md`](docs/V2_RELEASE_NOTES.md).

---

## [1.11.0] - v1.11.0 - Figure auto-embed + real slides/poster + reviewer scaffold + 8 deferred items closed (2026-06-05)

MINOR release. Closes F-005 + F-019 + AUDIT-026 + AUDIT-047 + AUDIT-063
+ AUDIT-073 + humanities_essay_structure deferrals. Ships the headline
figure-auto-embed pass (walk every step's outputs/figures/ into the
right section of paper.md before PDF compile, with a companion
orphan-coverage audit gate). Real Reveal.js v5 + Touying-Typst slide
compilers across 5 stock templates replace the v1.10.x skeleton. Real
Typst poster compiler across 5 size templates replaces the legacy
tikzposter LaTeX engine (still reachable via `poster_engine: latex`).
Adds `tool_audit_cross_deliverable_consistency` (5-dimension check
across paper/dashboard/slides/poster). Adds the reviewer scaffold (4
tools + 7 bundled personas + 1 protocol) for pre-submission
adversarial self-review with per-comment rebuttal generation and
hand-waving audit. Adds humanities-monograph ISBN verifiers (WorldCat,
OpenLibrary, LOC). Synthesis-pipeline config block lands in
`researcher_config.yaml` (13 fields) so figure / slide / poster
behaviour is declarative.

Deferred to v2.0.0: tool surface consolidation (search/plan/path/mem
clusters); `server.py` refactor (6.4K lines into focused submodules);
deprecation cleanup (hard-remove the 21 aliases that fire telemetry
today).

### Added
- docs(TOOLS.md): new "Per-step audit overrides" section catalogs every override_<gate> kwarg the server accepts (override_completeness_gate, override_dashboard_content_gate, override_discussion_coverage, override_gate, override_literature_gate, override_no_pdfs, override_rationale, allow_unfinalized_predecessor) with a tool-by-tool table and worked call snippets.
- docs(AI_GUIDE.md): new "When to override a gate" section with five worked examples (data-engineering step, literature unreachable, methodology pending, pre-publication final pass, researcher discretion) clarifying when the override path is appropriate and when fixing the underlying blocker is the right answer.
- docs: documented the override_rationale REQUIREMENT under interaction.quality_gate_policy=enforce and the workspace/logs/override_log.md line format (timestamp, tool, gate, rationale, JSON extras) so authors of the pre-submission audit have a stable contract to read.
- tests(unit): test_override_docs.py grep-asserts that every override_<gate> kwarg present in server.py is mentioned in both docs/TOOLS.md and docs/AI_GUIDE.md, plus that override_rationale, workspace/logs/override_log.md, and the two new section anchors are present in both guides.
- Humanities monograph citation verifiers: `verify_worldcat`, `verify_openlibrary`, `verify_loc` in `research.citations_isbn`, with an `verify_citation_auto` dispatcher that picks the chain based on whether the citation carries an ISBN or only a DOI. Offline-safe (5s timeout, never raises). Stdlib only.
- `synthesis.citations.verify_citation_entry` helper that routes ISBN-bearing citations through the new monograph verifiers and falls back to Crossref for DOI-only entries.
- New `synthesis/humanities_essay_structure` protocol — non-IMRAD interpretive shape (thesis → contextual framing → 3-5 close readings → critical conversation → counter-argument + reply → conclusion + stakes) so humanities projects no longer fall into the IMRAD synthesis_paper template.
- New `tool_humanities_essay_scaffold` MCP tool — writes `synthesis/paper.md` with the six humanities-essay section headings + one-paragraph stubs. Idempotent: preserves substantive researcher prose on re-run.
- New router entry under `synthesize` intent class with `humanities_essay` sub-intent and triggers for "humanities essay", "close-reading essay", "write the essay", "essay structure".
- COREQ (Tong et al. 2007, 32 items) and SRQR (O'Brien et al. 2014, 21 items) reporting-standard checklists under `templates/checklists/`, with `id` / `domain` / `item_text` / `guidance_short` per item; closes AUDIT-026.
- `tool_qualitative_select_standard` (qualitative pack) — reads `workspace/study_design.yaml`, picks COREQ for interview/focus-group studies and SRQR otherwise, copies the matching bundled checklist into `workspace/checklists/<standard>_coverage_v<N>.yaml` so the `walk_checklist` step has a populated file to mark up.
- tests/unit/test_protocol_no_deprecated_aliases.py: regression gate that grep-walks every protocol YAML across core + every research_os_<pack> and fails if any of the 21 deprecated alias names appears as a whole word.
- AUDIT-063: tool_synthesize accepts `auto_proceed=true` to process every section (methods → results → discussion → introduction → abstract) plus the full assembly in ONE call when `interaction.autonomy_level=='autopilot'`. Returns a structured error in manual/supervised/coaching modes. Backwards-compat: default `false` preserves every existing call site.
- Dashboard v2 now surfaces qualitative-pack sections (codebook table with kappa, themes hierarchy with subthemes, per-transcript saturation grid + curve, member-checking log per round) when the project's pack is detected as qualitative.
- Dashboard v2 now surfaces humanities-pack sections (apparatus criticus table, numbered close-reading anchors, critical-conversation map from citation chains, manuscript witness list with sigla) when the project's pack is detected as humanities.
- dashboard_v2.detect_active_pack(root) — resolves the active domain pack from researcher_config.yaml (pack/domain/packs) then falls back to workspace markers. Humanities wins over qualitative on tie.
- Figure auto-embed (v1.11.0 headline feature): src/research_os/tools/actions/synthesis/figure_auto_embed.py walks every numbered step's outputs/figures/ and inserts each figure into the right section of synthesis/paper.md, driven by a YAML frontmatter sidecar (section_hint, figure_priority, poster_priority, alt_text, figures_for_paper, interactive_required). Three modes: append_to_section / explicit_map / reorder. Idempotent — preserves manual placements.
- tool_paper_figures_autoembed — call directly or let tool_synthesize invoke it when synthesis.figures_auto_embed=true. Multi-paragraph captions split into headline + 'Note:' appendix. Logs every run to workspace/logs/figure_auto_embed.md.
- tool_audit_figure_coverage — BLOCKs the master quality audit when a step has a figure on disk (figures_for_paper!=false) but synthesis/paper.md does not embed it. Opt out per-step (step_summary.yaml.figures_for_paper) or per-figure (caption sidecar frontmatter).
- Cross-reference rewrite: rewrite_figure_xrefs converts bare stems ('see 01_volcano') to @fig:01_volcano cross-refs, skipping code blocks / inline code / image-link payloads / tokens already in @fig: form. Gated by synthesis.figure_xref_rewrite (default true).
- templates/step_summary.yaml.template now documents the figures_for_paper field; researcher_config.yaml ships synthesis.figures_auto_embed / figures_auto_embed_mode / figure_xref_rewrite.
- Real slide compilation engine (`tool_slides_create`) with two backends: `engine="reveal"` emits a single self-contained `synthesis/slides.html` using vendored Reveal.js v5 (speaker-notes plugin included), and `engine="touying"` emits `synthesis/slides.typ` against a bundled Touying-compatible Typst template and compiles to `synthesis/slides.pdf` via the typst CLI.
- Five stock slide templates under `src/research_os/assets/slide_templates/`: `conference_15min`, `conference_5min_lightning`, `lab_meeting_30min` (with backup section), `defense_45min` (35-slide chapter-arc), `public_outreach` (no-jargon).
- Optional `print_handout=True` (default) writes `synthesis/slides_handout.pdf` — a 2-up A4 condensed PDF with speaker notes printed beneath each slide; works for either engine via the touying handout fallback.
- Vendored Reveal.js v5 (MIT) + a minimal Touying-compatible Typst template (`touying-mini`, MIT) under `src/research_os/assets/reveal/` and `src/research_os/assets/typst_packages/touying-mini/`; LICENSE + NOTICE shipped beside each.
- Real Typst poster compilation backing `tool_poster_create`: 5 templates (academic_36x48, academic_48x36, academic_a0_portrait, academic_a1_landscape, public_24x36), light/dark/institution_branded themes, hero figures sorted by `poster_priority` frontmatter, optional QR code, US-letter handout PDF.
- `poster-mini` Typst helper package at `assets/typst_packages/poster-mini/` (poster-page / poster-header / poster-footer / poster-block / poster-headline / poster-figure / poster-bullets) plus 5 thin template wrappers at `assets/poster_templates/`.
- Reviewer-response scaffold: 7 bundled reviewer personas (methodology_skeptic, domain_expert, statistician, reproducibility_advocate, scope_creep_critic, novelty_critic, presentation_critic) + 4 tools (tool_reviewer_simulate, tool_rebuttal_draft, tool_reviewer_response_compile, tool_audit_reviewer_responses) + synthesis/reviewer_response protocol. Pre-submission adversarial self-review against synthesis/paper.md, per-comment rebuttal scaffolds with auto-discovered workspace evidence, compiles to response_to_reviewers.md/.pdf, audits for hand-waving + missing evidence.
- `tool_audit_cross_deliverable_consistency` — cross-deliverable consistency audit across paper, dashboard, slides, and poster along 5 dimensions: numeric claims (±1% tolerance), figure stems, citation keys, headline findings (Jaccard ≥ 0.30), and reproducibility footer (RO version + commit hash + build timestamp). Skipped when <2 deliverables exist; override via `override_cross_deliverable` + `override_rationale`.
- Reference-project manifests now declare a v1.11.0 contract: synthesis_deliverables (paper/slides/poster fan-out with per-deliverable tool + args + checks), cross_deliverable (title/figure-registry/citation-set consistency), and synthesis_behavior (theory-math-specific gate flags). biology_genomics_mini also declares a reviewer_simulation block (7 personas, min 30 comments).
- New reference project tests/fixtures/projects/theory_math_graph_proof/ — sub-cubic 4-colourability (corollary of Brooks 1941) with 3 inputs. Doubles as a regression target for the DEG-trigger false-positive routing bug flagged in the v1.11.0 smoke pass.
- tests/fixtures/figures/ — 4 placeholder PNGs paired with .caption.md sidecars carrying YAML frontmatter (figure_id, title, license, alt_text, source, generated_by, data_provenance) and the W3C three-part caption body shape.
- tests/fixtures/projects/humanities_ms_review/inputs/citations/monographs.yaml — 3 ISBN-bearing monograph fixtures (Bede OUP 2009, Augustine OUP 1992, Liuzza Broadview 2014) for the OpenLibrary / WorldCat / LOC verifiers.
- qualitative_interviews manifest now declares pii_redaction_expectations (must fire before synthesis; 18 HIPAA classes) and coreq_checklist (32 items walked, 28+ present) so the harness can audit the qualitative pipeline end-to-end.
- humanities_ms_review manifest now declares routing_expectations for the essay output path (project_kind=humanities + output_type=essay → humanities/output/humanities_essay_structure) and isbn_verifier_expectations (3 entries, all verifiers acceptable, network_required false for offline CI).
- tests/unit/test_v1110_reference_project_manifests.py — 23 hermetic tests pinning the new manifest contract, the graph-theory fixture presence, the caption-sidecar frontmatter shape, and the ISBN-extraction handshake against the existing _extract_isbn helper.
- Preflight check #22: `check_no_deprecated_aliases_in_protocols` scans every shipped protocol YAML for references to names in `_DEPRECATED_ALIASES` and fails the gate if any are found. Protocols must call the consolidated handler directly.
- Synthesis-config block: researcher_config.yaml ships 13 declarative knobs under `synthesis:` (figure auto-embed mode + xref rewrite; slide engine + template + theme + speaker_notes + handout; poster engine + template + theme + qr_url + handout). All optional with safe defaults.
- Preflight check: `check_figures_for_paper_field` — once any fixture ships captioned figures, the gate confirms `figures_for_paper` is declared at step or sidecar level.

### Changed
- AUDIT-047: swept all 21 deprecated tool-name aliases from 75 shipped protocol YAMLs (74 core + wet_lab pack) and rewrote each to its canonical name via the server _ALIASES table. Also rewrote the 5 remaining sites in `_router_index.yaml` (sys_path_create / sys_path_abandon → sys_path; mem_methods_append / mem_decision_log → mem_log). Bumped version of every touched protocol to 1.11.0. Dispatcher still rewrites old names for back-compat, so end-user projects on prior versions are unaffected.
- synthesis/synthesis_paper protocol prose documents the new autopilot short-circuit alongside the existing 10-turn multi-turn enforcement.
- tool_dashboard_create result dict gains an active_pack field (empty string for generic STEM projects). Existing callers ignore unknown fields, so this is backwards-compatible.
- synthesis/synthesis_paper protocol final_assembly step now describes the auto-embed pass + tool_audit_figure_coverage as part of the assembly + audit loop.
- `tool_slides_create` inputSchema gained `engine`, `template`, `theme`, `speaker_notes_enabled`, `print_handout` kwargs. Legacy `output_format` (`reveal`/`beamer`/`pdf`) and `audience` kwargs are still accepted and silently mapped to the new `engine=` argument.
- `tool_poster_create` default engine flips from legacy tikzposter LaTeX to Typst. Set `researcher_config.synthesis.poster_engine: latex` (or pass `engine='latex'`) to opt back into the tikzposter path; legacy `layout` / `audience` kwargs still route there.
- `synthesis.poster_template` validator enum: `academic_36x48` / `academic_48x36` / `academic_a0_portrait` / `academic_a1_landscape` / `public_24x36`. Renames `a0_portrait` → `academic_a0_portrait` and `a0_landscape` → `academic_a1_landscape`; adds `public_24x36` for community-event posters.
- `qualitative/output/qualitative_report_format.select_standard` step now calls `tool_qualitative_select_standard` instead of leaving the file copy as prose; protocol bumped to 1.11.0. Qualitative pack `__version__` bumped to 1.11.0.

### Fixed
- Humanities smoke gap — `humanities/textual/close_reading` and `humanities/archival/archival_research` citation chains were terminal (next_protocol: null), forcing humanities synthesis through IMRAD `synthesis_paper`; the new structure protocol gives the chain a humanities-shape destination.

### Closed
- AUDIT-073 — dashboard v2 qualitative + humanities renderers shipped (40 new unit tests).

### Deferred
- Tool surface consolidation (search/plan/path/mem clusters) → v2.0.0. Aliases continue to log deprecation telemetry to `.os_state/deprecations.log`.
- `server.py` refactor (split 6.4K lines into focused submodules) → v2.0.0.
- Hard removal of the 21 `_DEPRECATED_ALIASES` → v2.0.0 (MAJOR — breaking).
- Wiring `verify_citation_entry` into the live `tool_citations_verify` pipeline → next minor; requires upstream `mem_citations_generate` to populate `isbn` fields on monograph entries.

### Known issues (deferred to v1.11.1)
- **theory_math pack — Path coercion**: `src/research_os/tools/actions/state/config.py:224,356` and 16 sites in `audit/audit.py` do `root / 'workspace'` without `root = Path(root)` coercion. Handlers called with a `str` root (rare in production; common in ad-hoc smoke harnesses) raise `TypeError`. Test suite uses `Path` so the gate is green; production paths from MCP transport are already `Path`. Fix: single-line coercion at each entry point.
- **theory_math pack — pack-blind discovery**: `tools/actions/protocol.py:502` (`list_protocols`) walks only `PROTOCOLS_DIR`, never `_pack_protocol_dirs_safe()`. Symptom: `sys_protocol_list(category='theory_math')` returns core-only 117. Resolution via `sys_protocol_get` works.
- **theory_math pack — router false-positive**: `DEG` trigger (intended for "DEG analysis" / "differential expression") matches "maximum degree 3" in graph-theory prompts. Routes theory-math conjectures into `guidance/analysis_plan` instead of `theory_math/method/proof_strategy_selection`.
- **theory_math pack — IMRAD-only synthesis**: `tool_synthesize(output_type=paper)` emits `[abstract, introduction, methods, results, discussion, references]` even when project pack is `theory_math` (which prefers `[introduction, preliminaries, main_theorems, proofs, discussion]`). Synthesis pipeline has no hook to consult pack-supplied section schema.
- **tool_synthesize — silent citation retrieval failure**: e2e smoke against `biology_genomics_mini` shipped `paper.md` with `citations_used=0` due to `'list index out of range'` in upstream Semantic Scholar / Crossref adapter. Surfaces as cross-deliverable consistency blockers (439 numeric mismatches downstream). Tool succeeds; citations missing.
- **E2E manifest — persona-name drift**: `tests/fixtures/projects/biology_genomics_mini/manifest.yaml` lists personas (`skeptical_methodologist`, `statistics_referee`, `domain_expert_neuroscience`, `bioinformatician_reviewer`, `ethics_irb_reviewer`, `editor_in_chief`) that do not exist in `src/research_os/assets/reviewer_personas/`. Real persona ids: `methodology_skeptic`, `statistician`, `domain_expert`, `reproducibility_advocate`, `novelty_critic`, `scope_creep_critic`, `presentation_critic`. Fix: rename manifest entries to canonical ids.
- **Handout naming convention**: implementation writes `slides_handout.pdf` / `poster_handout.pdf`; some manifests expect `slides.handout.pdf` / `poster.handout.pdf`. Pick one and update both sides.
- **Typst font warnings**: every PDF compile emits non-fatal warnings for missing `Linux Libertine` / `Times New Roman` / `Times`. Ship a bundled fallback (e.g. New Computer Modern) or document the font install requirement.

---

## [1.9.4] — Fresh-agent usability validation: 22 fixes across docs / protocols / templates (2026-06-05)

MINOR release. Closes 21 of 22 prioritized fixes from a 5-scenario
fresh-agent usability validation (Claude Opus 4.7, 1M ctx, doc-surface
only across biology RNA-seq, humanities close-reading, qualitative
interviews, engineering microbenchmark, theory/math proof). Average
usability rating moved **6.6 / 10 → 7.8 / 10**; HIGH-severity friction
**12 → 1**; first-5-turns HIGH friction **2 → 0**. One new protocol
(`methodology/qualitative_pii_redaction`), one new schema field
(`next_protocol_kind` on all 148 protocols), `citation_style` enum
widened, two new Typst venue templates. No public-API tool removed.
No tool's existing input schema changed.

Full detail: [`docs/USABILITY_v1.9.4.md`](docs/USABILITY_v1.9.4.md)
(synthesis), `docs/usability_v1.9.4/scenario_{1..5}*.md` (per-scenario
trace + re-run reports), and the "Validated in v1.9.4" appendix in
[`docs/AUDIT_v1.9.2.md`](docs/AUDIT_v1.9.2.md).

Release gates: preflight 23/23 (new check: `next_protocol_kind
declared on every protocol`); pytest **899 passed** (was 896
baseline; +3 from new Typst venue parametrisations for
`humanities_essay` + `chicago_thesis`); ruff clean.

### Added

* **`docs/USABILITY_v1.9.4.md`** — 5-scenario fresh-agent validation
  synthesis (165 turns logged, friction matrix, cross-scenario
  themes, 22-fix priority list, deferred items, full re-validation
  results table).
* **5 per-scenario reports** under `docs/usability_v1.9.4/`
  (initial + re-run for biology / humanities / qualitative / theory;
  initial only for engineering).
* **New protocol: `methodology/qualitative_pii_redaction.yaml`** —
  HIPAA Safe Harbor 18-class + GDPR Art. 9 + IRB-compliant
  pre-coding gate. Hard prerequisite of `methodology/qualitative_research`.
  Routes via `_router_index.yaml` when raw transcripts present without
  redacted counterpart (F-017).
* **New schema field: `next_protocol_kind`** on every protocol YAML
  (`forward_default` | `iterate_back` | `terminal`). Backfilled across
  all 148 protocols (base + 5 packs) via inference. Documented in
  `PROTOCOL_DOCTRINE.md` (F-007). Soft preflight check added.
* **`step_intent` field** in `templates/step_summary.yaml.template`
  (plan / ground / analyse / visualise / synth / proof / apparatus).
  Per-step audit waivers documented per intent class (F-001).
* **2 new Typst venue templates**: `humanities_essay.typ`
  (single-column, footnotes, block-quote macro, generous margins) +
  `chicago_thesis.typ` for humanities + Chicago-citation outputs
  (F-018). Registered in `VENUE_TEMPLATES` + `VENUE_CITATION_STYLE`.
* **PII redaction policy template**: `templates/qualitative/pii_policy.md`
  (F-017 supporting material).
* **End-to-end recipes table** in `docs/USE_CASES.md` (qualitative
  pipeline, ML benchmark, theory/math proof, humanities essay,
  viz-only). Plus "Common first prompts (start here)" table covering
  data+hypothesis, text corpus, interview transcripts, benchmark
  vocabulary, conjecture-to-prove, mid-pipeline, unclear-intent
  (F-008, F-021).
* **Appendix A — Common figure recipes** in
  `docs/RESEARCHER_GUIDE.md` (volcano / UMAP / heatmap / forest /
  survival KM / log-log benchmark) mapping each to its protocol
  stack + enforced sidecar/audit conventions (F-016).
* **Theory_math pack surfaced in 4 user-facing docs**:
  `docs/USE_CASES.md` (theorist row, 8 protocols + 3 tools),
  `docs/PROTOCOLS.md` (8-protocol section), `docs/START.md` (theory +
  qualitative + humanities first prompts), `docs/AI_GUIDE.md` (full
  domain-packs section with theory_math workflow) (F-014).
* **Return-shape JSON examples** in `docs/TOOLS.md` for
  `tool_intake_autofill`, `tool_dashboard_create`, `tool_step_complete`,
  `tool_audit_quality_full` (F-013). Cited by the biology re-validation
  as "single highest-leverage doc choice; lets a fresh agent simulate
  calls without grepping src/".

### Improved (AI guidance prose across protocols)

Scenarios improved: biology RNA-seq DE (S1), humanities close-reading
(S2), qualitative interviews (S3), engineering benchmark (S4),
theory/math proof (S5) — all 5.

* **`methodology/qualitative_research.yaml`** — `next_protocol` fixed
  from `guidance/analysis_plan` → `methodology/qualitative_quality_audit`
  (F-006). `ingest_transcripts` step now STOPs and routes when raw
  transcripts lack redacted counterpart (F-017). `declare_step_contract`
  step added per F-002 (figure-gate auto-waiver).
* **`methodology/method_comparison.yaml`** — engineering / systems
  benchmark addendum step added (warm-up runs vs folds, CPU governor
  control, paired Wilcoxon on heavy-tailed timings, log-log scaling
  plots, language-stdlib baselines, requirements-traceability binding)
  (F-010).
* **`guidance/analysis_plan.yaml`** — `classify_step_intent` step added
  at step-create time; visualise-step literature exemption via
  `literature.inherits_from` documented (F-001, F-004).
* **`literature/literature_per_step.yaml`** — verdict enum extended
  to AGREES | DISAGREES | EXTENDS | **IMPORTED_AS_CITED** |
  **SPECIALIZES** | DEFERRED. Verdict-selection guide added.
  Visualise-step inheritance contract documented (F-003, F-004).
* **`research_os_humanities/protocols/textual/close_reading.yaml`** —
  `declare_step_contract` step added (apparatus contract waives
  generic completeness gate); `tool_humanities_apparatus_audit`
  cross-link (F-002, F-020).
* **`research_os_theory_math/protocols/proof/proof_verification_workflow.yaml`** —
  `step_intent: proof` contract declaration (F-002).

### Improved (error messages + tool surface)

* **`tool_dashboard_create`** — `mode` enum (explore / story /
  executive / teaching) enumerated in TOOLS.md; composition with
  `audience=` documented; story-mode dependency on `dashboard_story.md`
  surfaced (F-011).
* **`tool_step_complete`** — first-class TOOLS.md entry with gate
  sequence, return shape, and alias-superset relationship to
  `tool_path_finalize` (F-012).
* **`tool_engineering_requirements_matrix`** — cross-referenced from
  `method_comparison` engineering / systems-benchmark addendum (F-009).
* **`tool_redteam_review`** — row added to TOOLS.md (Audit extensions)
  clarifying `focus=` values and distinction from `quick_paper_review`
  and `peer_review_response` (F-015).

### Improved (onboarding flow)

* `docs/START.md` — extra `inputs/` subfolders table after the
  file-drop section; pointer to validated first-prompts table in
  USE_CASES.md; theory + qualitative + humanities first prompts
  (F-021, F-022).
* `docs/AI_GUIDE.md` — `discover/` clarified as shortcut-tool-only
  intent_class (no FS folder, stops fresh agents grepping src/);
  `inputs/` directory conventions table; `chat_split_recommended`
  heuristic per `model_profile`; full domain-packs section (F-014,
  F-022, C-extras).
* `docs/RESEARCHER_GUIDE.md` — extra-subfolders table after file-layout
  diagram; inline citation_style + venue_template comments flagging
  humanities/math gaps and workarounds; Appendix A common figure
  recipes (F-016, F-022).
* `docs/FAQ.md` — text-corpus-vs-transcripts file placement;
  theory-math support discoverability; humanities pack support +
  monograph citation gotcha; qualitative end-to-end chain +
  saturation-not-power-analysis (F-022, C-extras).

### Fixed (edge cases)

* **Per-step audits now intent-aware** — F-001 + F-002 ship the
  `step_intent` contract; figure-required hard-fail auto-waives for
  plan / ground / proof / apparatus / synth steps. Drove 5/5 scenarios'
  per-step-audit over-fire to zero.
* **Literature gate verdict enum gap closed** — F-003 extends enum
  with IMPORTED_AS_CITED + SPECIALIZES, closing theory's 9-HIGH
  literature-gate verdict-mismatch cluster. F-004 documents the
  visualise-step exemption via `literature.inherits_from`.
* **`qualitative_research.next_protocol` mis-route fixed** — F-006
  one-line YAML fix.
* **`next_protocol` semantic ambiguity resolved** — F-007 backfills
  `next_protocol_kind` on all 148 protocols.
* **`citation_style` enum widened** — F-018 adds mla,
  chicago_author_date, chicago_notes_bib, amsplain, siam (mirrored
  in `CONFIG_TEMPLATE` + `VENUE_TEMPLATES` + `VENUE_CITATION_STYLE`
  with researcher-facing → Typst hyphenated CSL translator).

### Fixed (per-domain composition gaps)

* **Qualitative** — pre-coding PII redaction protocol now exists
  upstream of coding (was: only quote-level audit AFTER coding, too
  late for HIPAA/IRB/GDPR). Most material protective gap closed (F-017).
* **Humanities** — `citation_style` MLA / Chicago + `humanities_essay.typ`
  + `chicago_thesis.typ` Typst templates shipped; `humanities_apparatus_audit`
  cross-linked from `close_reading` (F-018, F-020). Two HIGH frictions
  removed.
* **Theory/math** — pack surfaced in user-facing docs (F-014); paper
  rating moved 5 → 8.
* **Engineering** — `method_comparison` gains
  engineering/systems-benchmark addendum + cross-link to
  `tool_engineering_requirements_matrix` (F-009, F-010).

### Deferred to v1.11.0

* **F-005** — Per-step audit override path documentation
  (`override_completeness_gate`, `override_literature_gate`) with
  examples in TOOLS.md + AI_GUIDE.md.
* **F-019** — WorldCat / OpenLibrary / LOC ISBN-based verifiers in
  `tool_citations_verify` (humanities monograph DOI gap). Doc-side
  workaround language landed in v1.9.4.
* **Humanities essay structure protocol** parallel to
  `theory_math/output/theory_paper_structure` — `humanities_essay.typ`
  ships but no protocol drives it.
* **`tool_audit_step_literature` descriptive/prep step waiver** —
  partial via F-003; full descriptive-step waiver still open
  (continuation of AUDIT-v1.9.2-022).
* **D-01 .. D-07** — pack-aware `tool_audit_prose`, theory dashboard
  schema, LLM-assisted qualitative coding tool, informal-markdown
  proof parser for `tool_theory_math_dep_graph`,
  `chat_split_recommended` heuristic exposure, router decomposition
  algorithm exposure, `single_coder` branch in
  `coding_scheme_development`.

### Validation metrics

* **Average usability rating**: **7.8 / 10** (vs 6.6 / 10 initial baseline; +1.2)
* **HIGH-severity friction events**: **1** (vs 12 initial; −11)
* **Onboarding HIGH friction (first 5 turns)**: **0** (vs 2 initial)
* **Scenarios reaching `paper.pdf` step**: 5 / 5
* **Scenarios reaching `dashboard.html` step**: 5 / 5 (was 5 / 5 with 1 partial)
* **Top scenario movement**: theory/math 5 → 8 (+3) on F-014 + F-001/F-002 + F-003

Targets met: HIGH ≤ 5 (1) ✓; onboarding HIGH = 0 ✓. Target missed:
average ≥ 8.5 (got 7.8); concentrated in S2 humanities where the
missing `humanities_essay_structure` protocol and the still-empirical
descriptive/prep literature-verdict gap account for the 0.7-point gap.

### Bumped — protocols

148 protocol YAMLs (base + 5 packs) gained `next_protocol_kind` field
via scripted backfill (inferred: `null` → terminal, self-id →
iterate_back, otherwise → forward_default). Embeddings rebuilt
(151 protocols + 212 tools, BAAI/bge-small-en-v1.5, dim=384).

---

## [1.9.3] — Audit followup: 33 of 35 v1.9.2 findings resolved (2026-06-05)

MINOR release. Closes the v1.9.2 audit work-list: 4 CRITICAL +
~29 HIGH/MEDIUM findings fixed across src, protocols, packs, docs,
tests, and config schema. 10 findings deferred to v1.9.4 / v1.11.0
per the audit body's own target column. No public-API tool removed.
No new tools added.

Full detail: [`docs/CHANGELOG_DETAILED_v1.9.3.md`](docs/CHANGELOG_DETAILED_v1.9.3.md).
Audit followup appendix: [`docs/AUDIT_v1.9.2.md`](docs/AUDIT_v1.9.2.md)
(see "Resolved in v1.9.3" section).

Release gates: preflight 22/22 (new check:
`Router index mtime tracks protocols`); pytest 896 passed (was 872;
+24 v1.9.3 tests); ruff clean.

### Headline fixes

* **Config-path bug (the v1.5.1 silent failure)** — three readers
  (`resolve_gate_strictness`, `project_tier_strictness`,
  `_read_model_profile`) now consult `inputs/researcher_config.yaml`
  with a root-level fallback for legacy projects. `project_tier`
  now propagates as default `gate_strictness` when unset.
  [AUDIT-v1.9.2-001, 011, 071]
* **`override_discussion_coverage` end-to-end** — schema +
  handler + `log_override` wiring; mirrors
  `tool_audit_dashboard_content`. [AUDIT-v1.9.2-002]
* **`override_no_pdfs` writes `override_log.md`** — closes the
  audit-trail gap that would have bitten a biology synthesis
  attempt. [AUDIT-v1.9.2-018]
* **Humanities figure-mandatory wall removed** — `step_completeness`
  audit now accepts `apparatus.md` / `transcriptions/` /
  `citation_chains.md` / `close_reading.md` as focal artefacts when
  the project is detected as humanities (via config keys OR
  filesystem markers). [AUDIT-v1.9.2-003]
* **Master audit lists all 6 gates** — `tool_audit_quality_full`
  description + `audit_and_validation.yaml` step doc now mention
  `grounding_verify` (previously silently invoked but undocumented).
  [AUDIT-v1.9.2-020]
* **Router DESeq2 / scRNA-seq triggers** — explicit triggers added
  under `guidance/analysis_plan`; stops `bayesian_analysis` from
  miscarrying biology-classic phrasings.
  [AUDIT-v1.9.2-028]
* **Typst PDF reachable from `tool_plan_advance`** —
  `synthesis_paper` decomposition appends
  `tool_paper_compile_typst` (conditional on
  `writing_preferences.pdf_compile_engine == typst`).
  [AUDIT-v1.9.2-029]
* **REDCap cross-sectional detection** — 12-row participant tracking
  CSV with `record_id` + sibling dictionary / `*_complete` sentinel
  now detects cleanly. [AUDIT-v1.9.2-012]
* **Qualitative detector picks up .txt / .md transcripts** at ≥3
  speaker turns (was ≥5). [AUDIT-v1.9.2-013]
* **κ thresholds unified** — Landis & Koch 1977 standard;
  LIGHT 0.60 / NORMAL 0.70 / STRICT 0.80 framework documented in
  `inter_rater_reliability` as single source of truth.
  [AUDIT-v1.9.2-034]

### Coherence

* **`docs/TOOLS.md`** 131/212 → **212/212** tool names mentioned;
  added 14 sub-tables under "Infrastructure + power-user tools."
  [AUDIT-v1.9.2-042]
* **`docs/PROTOCOLS.md`** now ships a full 114-protocol catalogue,
  auto-generated by new `scripts/regen_protocols_doc.py`.
  [AUDIT-v1.9.2-010]
* **`docs/RESEARCHER_GUIDE.md`** §8 config schema synced to
  `templates/researcher_config.yaml` 1:1; runtime safety knobs +
  `research_goal.*` extension fields documented. Source-tree
  diagram regenerated. [AUDIT-v1.9.2-009, 048, 056, 057]
* **`docs/AI_GUIDE.md`** visualization table 6 → 14 protocols.
  [AUDIT-v1.9.2-058]
* **`researcher.affiliation` → `institution`** — canonical key
  resolved; `synthesis/latex.py` falls back for legacy configs.
  [AUDIT-v1.9.2-045]

### Config schema

* **`CONFIG_TEMPLATE` pinned to `templates/researcher_config.yaml`**
  byte-for-byte; new `test_config_template_matches_template_file`
  prevents future drift. [AUDIT-v1.9.2-068]
* **`sys_config_validate` enum membership** — per-field checks for
  8 enum fields. [AUDIT-v1.9.2-072]
* **`coaching` autonomy_level** aliased to `supervised`
  (display preserved). [AUDIT-v1.9.2-046]

### Dead code

* 4 orphaned Typst vector-figure helpers [AUDIT-v1.9.2-037]
* 4 unused exception classes [AUDIT-v1.9.2-038]
* 14 helpers / 1 constant across 8 files [AUDIT-v1.9.2-051]
* 20 unused imports auto-fixed after F401 ignore was moved off
  global → per-file [AUDIT-v1.9.2-054]

### Tests

* +24 net new tests across 7 v1.9.3 test files (872 → 896 total).
* 2 fixture canned_responses rewritten against current step IDs.

### Bulk version bump

* All **114 core protocols** + 5 pack manifests + 36 pack protocols
  now on version `1.9.3`. [AUDIT-v1.9.2-043, 044]

### Preflight

* New warn-only check: `Router index mtime tracks protocols`
  (preflight now 22 checks, was 21). [AUDIT-v1.9.2-069]

### Deferred (per audit triage)

* v1.9.4: AUDIT-022, 023, 024, 060, 065, 074
* v1.11.0: AUDIT-026, 047, 063, 073

---

## [1.9.2] — Discovery sprint: comprehensive 10-lens system audit (2026-06-05)

PATCH release. After 8 minor releases (v1.4.0 → v1.9.1) shipping tools,
protocols, audits, refactors, vendored assets, and deprecations, the
system needed an end-to-end audit before further feature work
(v1.10.0 slides+poster, v2.0.0 deprecation cleanup). v1.9.2 ships the
findings doc + only the most trivial fixes; substance is deferred to
v1.9.3.

### Added

* **`docs/AUDIT_v1.9.2.md`** — comprehensive audit synthesis
  (~12,000 words) aggregating 75 findings across 10 lenses: 5 CRITICAL,
  27 HIGH, 29 MEDIUM, 22 LOW. Includes per-finding IDs (AUDIT-v1.9.2-001
  through 075), reproduction steps, suggested fixes, target-version
  routing, and a 35-item v1.9.3 work-list (~28 agent-hours).
* **`docs/audit_v1.9.2/`** — per-lens raw findings:
  - `lens_01_biology_stress.md` — full RNA-seq workflow trace
  - `lens_02_humanities_stress.md` — DH/literary-analysis composition
  - `lens_03_qualitative_stress.md` — 12-participant interview study
  - `lens_04_tool_protocol_consistency.md` — tool↔protocol↔server wiring
  - `lens_05_protocol_graph.md` — recommendation graph topology
  - `lens_06_docs_accuracy.md` — doc currency + cross-ref integrity
  - `lens_07_config_schema.md` — researcher_config field health
  - `lens_08_test_coverage.md` — coverage + brittleness audit
  - `lens_09_dead_code.md` — vulture + orphan-module sweep
  - `lens_10_audit_gates.md` — audit-of-audits consistency
* **`docs/PROTOCOL_GRAPH.mermaid`** — recommendation graph (Mermaid)
  rendered from `next_protocol` + `see_also` edges across all 114
  protocols.

### Fixed (trivial only — substantive bugs deferred to v1.9.3)

* Stale protocol/tool counts corrected across 8 user-facing docs:
  `README.md`, `START.md`, `AI_GUIDE.md`, `PROTOCOLS.md`, `TOOLS.md`,
  `FAQ.md`, `RESEARCHER_GUIDE.md`, `ROADMAP.md`, `CONTRIBUTING.md`
  (113 → 114 protocols, 146 → 212 tools, 438 → 872 tests).
* `sys_help` topic descriptions: methodology count (29 → 42),
  synthesis count (14 → 18), `sys_active_tools` description
  (143 → 212 tools).
* Stale `tool_audit_master` references (renamed to
  `tool_audit_quality_full` earlier): fixed in `docs/ROADMAP.md` and
  `src/research_os/tools/actions/audit/step_literature.py` docstring.
* `src/research_os/protocols/_router_index.yaml`: removed accidental
  "re-running by re-running" duplication in provenance_completeness
  decomposition purpose.
* `src/research_os/tools/actions/state/path.py`: removed unreachable
  `return out` after the real return (dead code, no behavior change).
* `src/research_os_humanities/detector.py`: docstring extension list
  corrected (`.pdf` → `.tex` to match actual filter).
* `.gitignore`: added `.claude/` and `.coverage` (dev artefacts).

### Deferred to v1.9.3 (next release — bug fix + coherence sweep)

35 work-items totalling ~28 agent-hours. Highlights:

* CRITICAL: `gate_strictness` / `project_tier` / reliability
  `model_profile` are read from the wrong path — v1.5.1 features
  silently inert in real projects (lens 07).
* CRITICAL: `override_discussion_coverage` documented but handler
  discards args and function takes no override (lens 10).
* CRITICAL: Step-completeness gate hard-requires a PNG/SVG focal
  figure per step — structurally blocks every humanities project from
  reaching synthesis (lens 02).
* CRITICAL: Seven tools referenced by `digital_humanities_workflow` +
  `scholarly_edition` do not exist; humanities pack unrunnable as
  written (lens 02).
* CRITICAL: `project_tier` never propagates to
  `resolve_gate_strictness`; throwaway/sketch/production tags do
  nothing (lens 10).
* HIGH: `tool_audit_quality_full` runs 6 gates but description
  advertises 5; `grounding_verify` is invisible (lens 10).
* HIGH: `override_no_pdfs` bypass does not write to
  `override_log.md`; audit trail invisible (lens 10).
* HIGH: `RESEARCHER_GUIDE.md` config schema is 5 fields behind
  template (lens 06).
* HIGH: `PROTOCOLS.md` silently omits 34 of 114 protocols including
  8 of 14 visualization protocols and 4 newest synthesis protocols
  (lens 06).
* MEDIUM: Router miscarries "fit a DESeq2 differential expression
  model" to `methodology/bayesian_analysis` (lens 01).
* MEDIUM: `synthesis_paper` decomposition omits
  `tool_paper_compile_typst` — small-model agents never produce a PDF
  (lens 01).

Subsystem health snapshot: protocol_graph, tool_wiring, tests,
dead_code, biology_core_path → **green**; documentation,
qualitative_pack → **yellow**; researcher_config_schema,
audit_gate_machinery, humanities_pack → **red**.

### Surface

No protocol or tool surface changes. No new dependencies (dev tools
`pytest-cov` and `vulture` used in-session but not added to runtime
requirements). 114 protocols, 212 tools, 872 tests — identical to
v1.9.1.

---

## [1.9.1] — Interactive dashboard rebuild + per-figure interactive enforcement + story mode (2026-06-05)

MINOR release. The dashboard becomes a real single-page web app.
Three themes land together because they share the same renderer and
vendored JS toolchain:

* **Theme 17 — Interactive dashboard rebuild.** New
  `dashboard_v2` renderer at
  `src/research_os/tools/actions/synthesis/dashboard_v2.py`. Produces
  a self-contained single-page app: header + collapsible sidebar nav
  + full-text MiniSearch index + URL-hash-persisted filter chips +
  reactive `<ro-table>` (sort / filter / CSV export) + per-figure
  `<ro-figure-toggle>` (static PNG ↔ interactive HTML companion via
  iframe) + Vega-Lite brushing + lazy-rendered Plotly / Mermaid /
  vis-network components + print stylesheet. Eleven vanilla custom
  elements; no React / Vue / Svelte. Offline-only: every JS bundle
  is vendored under `src/research_os/assets/js/` and inlined at
  render time — no `<script src=https://…>` ever ships in the
  output.
* **Theme 20 — Per-figure interactive companion enforcement.**
  `tool_audit_figure_interactivity` walks every figure under
  `workspace/<step>/outputs/figures/`. Scatter / volcano / UMAP with
  > 200 marks, > 50×50 heatmaps, networks, and > 1000-point time
  series all need a sibling `<stem>.html` companion. In normal
  strictness the gate auto-generates a Vega-Lite or vis-network
  HTML next to the static figure (tagged with
  `<meta name="ro-auto-generated">`); in strict mode missing
  companions BLOCK; in light mode they WARN. Per-figure researcher
  override: drop `<!-- ro:interactive-not-applicable, reason: … -->`
  into the figure's `.caption.md`.
* **Theme 21 — Dashboard story mode + explore mode.** Two reading
  modes share the same dashboard. Story is a single-column,
  serif-font, narrative scroll (Distill.pub-inspired) generated
  from each step's plain-language summary + key figure + adversarial
  verdicts surfaced as block-quote callouts. Explore keeps today's
  search + filter + figure-toggle interaction. Mode toggle persists
  in `localStorage` and is shareable via `#mode=story` /
  `#mode=explore`.

### Added — dashboard v2 renderer

* `src/research_os/tools/actions/synthesis/dashboard_v2.py` —
  `render_dashboard_v2(root, default_mode, search_enabled,
  print_optimized)` + `bundled_js` (concatenates the JS bundles
  this project actually needs, conditional on whether
  `*.plotly.json`, `*.mermaid`, or `*.graphml` files exist in the
  workspace; no Mermaid bytes for projects that don't use it).
* Eleven vanilla custom elements inlined as `CUSTOM_ELEMENTS_JS`:
  `<ro-mode-toggle>`, `<ro-sidebar>`, `<ro-search>`, `<ro-filter>`,
  `<ro-figure-toggle>`, `<ro-table>`, `<ro-brush-link>`, `<ro-vega>`,
  `<ro-plotly>`, `<ro-mermaid>`, `<ro-jump-to>`. Heavy components
  (Vega-Lite, Plotly, Mermaid) defer render via
  `IntersectionObserver` so off-screen figures don't tax the first
  paint.
* `tool_dashboard_create` gains `dashboard_legacy` (default false →
  v2), `dashboard_default_mode` (explore | story),
  `dashboard_search_enabled`, and `dashboard_print_optimized`. The
  v1 long-scroll renderer stays available as a fallback.

### Added — figure interactivity gate (Theme 20)

* `src/research_os/tools/actions/audit/figure_interactivity.py` —
  `audit_figure_interactivity(root, strictness, autogen)` walks
  every static figure under `workspace/<step>/outputs/figures/`,
  detects the figure kind via naming patterns + companion data
  files, and reports blockers / warnings / passes / overrides.
  Writes `workspace/logs/figure_interactivity_audit.md`.
* `figure_interactive_autogen(fig, root)` writes an offline-capable
  Vega-Lite (scatter / volcano / UMAP / heatmap / time-series) or
  vis-network (graphml) HTML companion next to a flagged figure.
  Idempotent — returns `status="exists"` when a companion is
  already there.
* `tool_audit_figure_interactivity` + `tool_figure_interactive_autogen`
  registered in the MCP surface.

### Added — story mode (Theme 21)

* `src/research_os/tools/actions/synthesis/dashboard_story.py` —
  `dashboard_story_generate(root)` builds
  `synthesis/dashboard_story.md` from the spec abstract + each
  step's plain-language summary + key figure + adversarial verdicts
  parsed from `findings_vs_literature.md` (DISAGREES / EXTENDS /
  CONTRADICTS / MIXED rendered as block-quote callouts).
  `dashboard_story_edit(root, edits, mode)` reads or patches the
  generated markdown (`patch` mode applies one or more
  `<<<<replace>>>>old\n----with----\nnew\n<<<<end>>>>` blocks
  atomically; `overwrite` mode replaces the whole file).
  `dashboard_story_quality_bar(root)` enforces three soft rules:
  reading time 5-20 min, figure in the first 1000 words, at least
  one adversarial-grounding callout.
* `tool_dashboard_story_generate`, `tool_dashboard_story_edit`,
  `tool_dashboard_story_quality_bar` registered in the MCP surface.

### Added — vendored JS bundles

* `src/research_os/assets/js/` ships seven minified JS bundles
  (MiniSearch 7.1.2, Vega 5.30.0, Vega-Lite 5.21.0, Vega-Embed
  6.26.0, Plotly basic 2.35.2, Mermaid 9.4.3, vis-network 9.1.9)
  plus their upstream LICENSE files under `licenses/` and a
  top-level `NOTICE.md` listing each library, version, SPDX
  identifier, and upstream URL. Total vendored weight ~5.2 MB.
* `MANIFEST.json` lists each bundle + intended purpose; the loader
  in `dashboard_v2` reads filenames from disk so swapping versions
  doesn't require code changes.

### Added — optional extras

* `interactive_figures = ["pyvis>=0.3"]` for projects that prefer
  the Python-side pyvis API over the inlined vis-network bundle.
* `story_math = []` reserved as a marker for future MathJax /
  KaTeX integration in story mode.

### Bumped — protocols

* `synthesis/synthesis_dashboard` → 1.9.1: new
  `ensure_interactive_companions` + `build_story_mode_source`
  steps before `build_dashboard`; documents the new
  `dashboard_default_mode` / `dashboard_legacy` knobs on
  `tool_dashboard_create`.
* `visualization/interactive_figure_design` → 1.9.1: documents
  `tool_audit_figure_interactivity` + `tool_figure_interactive_autogen`
  + the `<!-- ro:interactive-not-applicable -->` override syntax.
* Router index → version 14 (new tool refs).

### Tests

* 67 new tests across three files:
  `tests/unit/test_v191_dashboard_v2.py` (28),
  `tests/unit/test_v191_figure_interactivity.py` (21),
  `tests/unit/test_v191_story_mode.py` (18). Covers HTML render
  shape, offline-only constraint enforcement, bundle conditional
  loading, custom-element registration, full audit-gate state
  machine, autogen output validity, story patch roundtrip, and
  quality-bar rules.

---

## [1.9.0] — Typst PDF compilation + dashboard content gates + synthesis preview + content depth (2026-06-04)

MINOR release. First phase of the synthesis output overhaul: paper.md
now compiles to a venue-correct PDF via Typst (10 venue templates),
the dashboard audit now checks CONTENT instead of just structure
(numeric grounding, accessibility, palette consistency, reviewer-skim
simulation), a cheap synthesis preview lets the researcher inspect
the predicted shape before drafting, and a content-depth audit BLOCKs
on stub-shaped IMRAD sections (no numbers in the abstract, no
statistics in the results, no limitations paragraph in the discussion,
no per-step coverage in methods). LaTeX path (`tool_latex_compile`)
is preserved for venues that require .tex submission.

### Added — Typst PDF path

- `src/research_os/tools/actions/synthesis/typst.py` — `md_to_typst`,
  `citations_md_to_hayagriva`, `compile_typst`, `paper_compile_typst`.
- `tool_paper_compile_typst` — synthesis/paper.md → paper.typ →
  paper.pdf via Typst with venue-correct formatting. Returns
  `pdf_path`, `page_count`, `citation_count`, `typst_warnings`,
  parsed `typst_errors` with line numbers.
- 10 venue templates under `src/research_os/data/typst/` (bundled
  in the wheel) and `templates/typst/` (source checkout): `nature`,
  `science`, `nejm`, `cell`, `ieee_conf`, `neurips`, `acl`, `plos`,
  `generic_two_column`, `generic_thesis`. Per-venue citation style
  (Nature / IEEE / Vancouver / APA) wired through Hayagriva.
- `writing_preferences.venue_template` + `writing_preferences.pdf_compile_engine`
  added to the `researcher_config.yaml` template.
- `[typst_compile]` extra (no Python deps; opt-in marker).
- `docs/VENUE_TEMPLATES.md` documents every venue, the Markdown →
  Typst translation rules, and how to add a new template.

### Added — Dashboard content gates

- `src/research_os/tools/actions/audit/dashboard_content.py` — seven
  sub-checks: numeric grounding (±1% tolerance vs workspace tables +
  citations), figure-to-text proximity, per-section substantiveness,
  WCAG 2.2 AA accessibility (contrast, alt text, heading hierarchy,
  button labels), print stylesheet sanity, color-palette consistency
  (Okabe-Ito / viridis / PuOr), reviewer-skim simulator.
- `tool_audit_dashboard_content` — wrapper; ungrounded numbers and
  missing-abstract-numbers are BLOCKERs, everything else WARNs.
  Supports `override_dashboard_content_gate` + `override_rationale`
  logged to `workspace/logs/override_log.md`.
- `tool_dashboard_reviewer_sim` — standalone "would a 5-min skim
  get the finding?" check.
- `[print_audit]` + `[contrast_audit]` opt-in extras.

### Added — Synthesis preview

- `src/research_os/tools/actions/synthesis/preview.py` — cheap
  deterministic dry-run; reads the same sources as `tool_synthesize`
  but does NOT draft prose.
- `tool_synthesis_preview(target, venue, mode)` — returns
  `predicted_word_count_per_section`, `predicted_total_word_count`,
  `predicted_page_count` or `slide_count`,
  `predicted_figures_embedded`, `predicted_citations`,
  `predicted_steps_drawn_from`, `detected_gaps`,
  `estimated_render_time_seconds`. `mode='diff'` compares against
  the existing deliverable on disk.

### Added — Content depth audits

- `src/research_os/tools/actions/audit/content_depth.py` —
  per-IMRAD-section audits beyond word counts: abstract needs ≥ 1
  number + ≥ 1 method + ≥ 1 conclusion verb, introduction needs
  ≥ 3 cited prior works + an explicit "in this study, we" pivot,
  methods must cover ≥ 80% of workspace steps (< 50% BLOCKs),
  results needs ≥ 1 statistic per primary finding, discussion needs
  a limitations paragraph + future-work direction, every cited key
  must appear in the bibliography.
- `tool_section_substantiveness` — runs all of the above; promotes
  to BLOCKER when ≥ 2 steps are uncovered in BOTH methods AND
  results.
- `tool_audit_cliches` — standalone scan for AI-cliché phrases
  ("in this study, we investigate", "future work should explore",
  "it is important to note that", etc.) with per-cliché replacement
  hints.

### Added — reference projects + tests

- `tests/fixtures/projects/paper_nature_minimal/` — exercises the
  full Typst PDF path under the Nature template.
- `tests/fixtures/projects/paper_thin_content/` — same shape with
  intentionally stub-shaped IMRAD sections; verifies the content
  depth audit fires on cliché-shaped content.
- 77 new unit tests covering: every Markdown → Typst construct,
  Hayagriva citation conversion, end-to-end PDF compile for all 10
  venues (parametrised, gated on `typst` CLI availability), every
  dashboard content gate, synthesis preview predictions + diff
  mode, each per-section content depth audit, each cliché pattern.

### Improved

- `docs/TOOLS.md` — added entries for the 6 new tools.
- `tool.hatch.build.targets.wheel.force-include` ships the bundled
  Typst templates inside the wheel.

### Bumped

- `1.8.0 → 1.9.0` (pyproject.toml, `__version__`, CITATION.cff).
- Embeddings rebuilt to cover 207 tools + 150 protocols.

---

## [1.8.0] — 6 infrastructure adapters + multi-language tools.md extractor (2026-06-04)

MINOR release. Adds a new entry-point group `research_os.adapter` for pluggable
detectors + provenance extractors for the tools a project uses *around* its
code (HPC schedulers, workflow engines, analysis platforms, data systems).
Six adapters ship bundled with the core wheel. Also extends the tools.md
extractor from Python-only to multi-language with adapter-contributed
regex patterns, so a step's `tools.md` finally captures R libraries, HPC
modules, Snakemake rules, Nextflow processes, etc. Distinct from the
v1.7.0 `research_os.protocol_pack` group: packs add protocols; adapters
add provenance extractors. They share the loader pattern but have separate
registries.

### Added — adapter framework

- `src/research_os/adapters/__init__.py`, `base.py`, `loader.py`, `runner.py`.
- `AdapterRegistration` dataclass + `register_adapter()` convenience constructor
  with namespace validation + regex compile-time check.
- Discovery via `research_os.adapter` entry-point group + in-tree bundled list.
- Per-adapter error isolation: bad adapters log to
  `workspace/logs/adapter_errors.log` and are skipped without blocking startup
  or other adapters.
- Three new core MCP tools: `sys_adapters_installed` (diagnostic),
  `tool_adapter_extract` (run one), `tool_adapters_list` (status of all),
  `tool_adapters_run_all` (run every detected).

### Added — 6 bundled adapters

| Adapter | Detects | Extracts |
|---|---|---|
| `slurm` | `#SBATCH`/`#PBS` directives + inline `sbatch`/`qsub` | partition, time, nodes, cpus, mem, GPU, dependencies, modules |
| `snakemake` | `Snakefile` / `*.smk` | rules: name, inputs, outputs, shell preview, conda, container, threads |
| `nextflow` | `*.nf` / `nextflow.config` / `main.nf` | process blocks, containers, resources, executor profiles |
| `cytoscape` | `*.cys` session archives | per-network: nodes, edges, attribute schemas, layout, visual styles |
| `redcap` | data-dictionary CSV OR exports with `record_id` + `redcap_event_name` | fields (name/type/validation/identifier), longitudinal vs cross-sectional, sample N, PHI warnings |
| `synapse` | `.synapseConfig` / `synapseclient` imports / `synXXXXXXXX` refs | referenced entity IDs with source script + line + nearby comment |

### Added — 8 adapter-contributed tools

`tool_slurm_job_status`, `tool_slurm_estimate_cost`,
`tool_snakemake_dryrun`, `tool_snakemake_dag_render`,
`tool_nextflow_validate`, `tool_cytoscape_export_static`,
`tool_redcap_schema_describe`, `tool_synapse_entity_info`.
All gracefully degrade when their optional system deps (snakemake,
nextflow, synapseclient, matplotlib, openpyxl) are absent — returning
a `status='warning'` envelope with an install hint instead of failing.

### Added — multi-language tools.md extractor

`src/research_os/tools/actions/state/extractors.py` (new module). Per-language
extractors return `(kind, name, version)` tuples; a dispatcher routes by
file suffix; an adapter-pattern collector applies every registered adapter's
`tools_md_patterns` on top.

Languages covered: Python imports, R `library()` / `require()` / `p_load()` /
`BiocManager::install()`, R `DESCRIPTION` parsing, `renv.lock`,
Bash `module load` + `conda activate` + `source venv`,
Node `package.json` + JS/TS import / require,
Rust `Cargo.toml` + `.rs` use statements,
Julia `Project.toml` + `.jl` using / import.

`src/research_os/tools/actions/state/path.py` `_render_tools_md_section` now
delegates to `extract_from_tree`. Output format unchanged but vastly more
populated: a step's `tools.md` entry now reads like a full reproducibility
manifest ("R library: DESeq2", "HPC module: bwa/0.7.17", "Snakemake rule:
align").

### Added — 3 reference projects

- `slurm_snakemake` — RNA-seq pipeline (Snakefile + sbatch wrapper, exercises
  slurm + snakemake adapters)
- `nextflow_chipseq` — ChIP-seq DSL2 pipeline (exercises nextflow adapter)
- `redcap_longitudinal` — 3-event observational cohort (exercises redcap adapter)

CI stress matrix: **8 → 11 projects** × mock model on every PR.

### Added — extras

`pip install research-os[slurm]`, `[snakemake]`, `[nextflow]`, `[cytoscape]`,
`[redcap]`, `[synapse]` reserved as no-op extras (adapters ship bundled).
`pip install research-os[all_adapters]` installs all six.

### Added — preflight + tests

Two new preflight checks: **Bundled adapters discovered** + **Adapter regex
patterns compile**. Preflight: 19/19 → **21/21** green.

43 new tests under `tests/unit/test_v180_adapters_extractors.py` covering:
framework validation, all 6 adapters detect + extract, optional tools
dispatch, multi-language extractor coverage, 3 new reference projects
stress-run at 100% success, adapter cross-detection on real fixtures.

### Added — docs

- `docs/ADAPTERS.md` (new) — overview + write-your-own-adapter quickstart.

### Bumped

- `version 1.7.1 → 1.8.0` in `pyproject.toml`, `src/research_os/__init__.py`, `CITATION.cff`.
- Embeddings rebuilt (now 150 protocol docs + 201 tool docs).

### Counts

- Adapters: 0 → **6** (slurm, snakemake, nextflow, cytoscape, redcap, synapse).
- Tools surface: 189 → **201** (+3 core adapter tools + 9 optional pack tools).
- Reference projects: 8 → **11** (+3 infra-focused).
- Preflight: 19 → **21** checks.
- Pytest: 685 → **728** passes.

### Compatibility

No breaking changes. Every v1.6.x / v1.7.x tool name, protocol name, alias,
redirect stub, plugin API, stress-runner contract continues to work. The
adapter framework is a NEW namespace (`research_os.adapter`) separate from
the protocol-pack namespace (`research_os.protocol_pack`); they don't
cross-contaminate.

---

## [1.7.1] — 3 more domain packs: theory_math + wet_lab + engineering (2026-06-04)

MINOR release. Three new bundled domain packs (theory_math, wet_lab,
engineering) ship using the v1.7.0 plugin infrastructure unchanged.
5 domain packs total now bundled with the core wheel. No breaking
changes; the plugin API, namespace conventions, and stress-runner
contract from v1.7.0 are stable.

### Added — theory_math pack (bundled)

- `src/research_os_theory_math/` — 8 protocols + 3 tools + domain detector + 8 router entries.
- Protocols: `proof/proof_verification_workflow`, `proof/lemma_library`, `proof/theorem_dependency_graph`, `conjecture/conjecture_tracking`, `formal/lean_integration`, `formal/coq_integration`, `output/theory_paper_structure`, `method/proof_strategy_selection`.
- Tools: `tool_theory_math_lean_check` (runs `lean --make` + parses errors), `tool_theory_math_coq_check` (runs `coqc` + parses errors), `tool_theory_math_dep_graph` (parses .lean / .v imports + theorems → Mermaid + JSON DAG).
- Domain detector: .lean / .v / .agda / .thy files, LaTeX `\begin{proof}` / `\begin{theorem}` envs, Mathlib references, theory terminology.
- Naming note: tools are `tool_theory_math_*` (matches the `tool_<pack>_` namespace rule; the brief's shorthand `tool_theory_*` would have collided with future packs starting `theory_*`).

### Added — wet_lab pack (bundled)

- `src/research_os_wet_lab/` — 8 protocols + 3 tools + domain detector + 8 router entries.
- Protocols: `protocol/sop_versioning`, `protocol/reagent_lot_tracking`, `protocol/plate_map_provenance`, `protocol/instrument_run_log`, `protocol/sample_lineage`, `method/wet_lab_experiment_design`, `audit/wet_lab_reproducibility_audit`, `output/methods_section_wet_lab`.
- Tools: `tool_wet_lab_plate_map_render` (96/384-well layout → PNG + SVG + ASCII fallback), `tool_wet_lab_reagent_query` (per-supplier portal link + reagent YAML stub; no live API calls), `tool_wet_lab_sample_lineage_export` (parent → splits → readouts as Mermaid + JSON).
- Domain detector: instrument output files (.fcs / .qpcr / .czi / .raw / .tiff), catalog-number patterns, FACS / qPCR / ELISA / Western terminology, `inputs/protocols/` subdirectory.

### Added — engineering pack (bundled)

- `src/research_os_engineering/` — 7 protocols + 3 tools + domain detector + 7 router entries.
- Protocols: `design/design_iteration`, `design/requirements_traceability`, `safety/fmea_protocol`, `safety/fault_tree_analysis`, `test/test_failure_causation`, `test/build_test_fix_loop`, `output/engineering_report_structure`.
- Tools: `tool_engineering_fmea_render` (Failure Mode and Effects Analysis table → CSV + Markdown + optional Excel; auto-computes RPN; flags RPN ≥ 100), `tool_engineering_fault_tree_render` (AND / OR gates + basic events → Mermaid), `tool_engineering_requirements_matrix` (bidirectional SRS ↔ SDD ↔ test cases ↔ results → Markdown + optional Excel; flags orphan requirements + orphan tests).
- Domain detector: CAD files (.stp / .iges / .sldprt / .dwg / .dxf), simulation outputs (.odb / .raw), control-system code (.plc / .st), SRS / SDD / REQ / FR / TC IDs, V&V terminology.

### Added — stress-matrix fixtures

- 3 new reference projects under `tests/fixtures/projects/`: `theory_math_short_proof` (2-page theorem + lemma library + dependency graph), `wet_lab_qpcr_run` (single qPCR experiment with plate map + reagent tracking + instrument run log), `engineering_fmea_simple` (5-item FMEA + 3 requirements traced to test cases).
- CI stress matrix updated: 5 → 8 reference projects, each running against the mock model on every PR.
- `docs/RELIABILITY.md` auto-regenerates with the 3 new fixtures added to the per-project + per-protocol tables.

### Added — extras

- `pip install research-os[theory_math]`, `[wet_lab]`, `[engineering]` reserved as no-op extras (packs ship bundled).
- `pip install research-os[all_packs]` convenience meta-extra → installs every domain pack.

### Added — tests

- 50 new tests under `tests/unit/test_v171_three_packs.py`: all 5 packs register, 23 new pack protocols load, 9 new pack tools register + dispatch, 3 domain detectors trigger on their signature inputs, 3 reference projects parse + stress-run at 100% success against mock model, preflight checks pass with 5 packs.

### Bumped

- `version 1.7.0 → 1.7.1` in `pyproject.toml`, `src/research_os/__init__.py`, `CITATION.cff`.
- All 114 core protocol YAMLs bumped 1.7.0 → 1.7.1.
- All 36 bundled-pack protocol YAMLs ship at 1.7.1 (humanities + qualitative pack protocols bumped along with the new theory_math + wet_lab + engineering protocols).
- `_router_index.yaml` version 12 → 13.
- Embeddings rebuilt (now 150 protocol docs + 189 tool docs).

### Counts

- Bundled packs: 2 → 5 (humanities, qualitative, theory_math, wet_lab, engineering).
- Tools surface: 180 → 189 (+9 new pack tools).
- Protocols: 127 → 150 (+8 theory_math, +8 wet_lab, +7 engineering).
- Stress matrix: 5 → 8 reference projects × 1 model = 8 stress jobs per PR.
- Preflight: 19/19 green.
- Pytest: 635 → 685 passes.

### Compatibility

No breaking changes. Every v1.6.x and v1.7.0 tool name, protocol name, alias, redirect stub, plugin API surface, and stress-runner contract continues to work. The 5 bundled packs use the v1.7.0 plugin infrastructure unchanged.

---

## [1.7.0] — Plugin system + 2 launch domain packs + multi-model CI stress matrix (2026-06-04)

MINOR release. Implements ROADMAP Themes 4 and 10. Adds a plugin
entry-point group so third parties can ship protocol packs without
forking core; bundles two launch packs (humanities, qualitative)
that break Research-OS out of its biology/clinical bias; lands a
stress runner + mock-model CI matrix + auto-generated public
reliability surface. No breaking changes — every existing tool,
protocol, and alias keeps working.

### Added — Theme 4A: plugin system

- New entry-point group `research_os.protocol_pack`. External packs register via `pyproject.toml` and Research-OS auto-discovers them on server startup.
- `src/research_os/plugins/pack_api.py` — stable author surface: `PackRegistration`, `PackTool`, `@register_tool` decorator, `captured_tools(__name__)`.
- `src/research_os/plugins/loader.py` — discovery + namespace validation + merge into core registries.
- Namespace conventions enforced by the loader: protocols `<pack>/<category>/<name>`, tools `tool_<pack>_<name>`, router entries `<pack>/...`. Collisions fail loudly.
- Errors are isolated per pack — a bad pack writes its traceback to `workspace/logs/pack_errors.log` and is skipped without blocking server startup or other packs.
- New tool `sys_packs_installed` — list installed packs (name, version, description, tool count, router entries, registration errors).
- Pack-aware protocol loader: `<pack>/...` ids resolve through each pack's `protocols_dir`; bare ids fall through to core then packs.
- Router-index merge: `_load_index` includes every pack's contributed `router_entries` at runtime.
- Two new preflight checks: **Bundled packs discovered** + **Pack protocols load**. Preflight: 17 → 19 checks.
- `docs/PLUGIN_AUTHORING.md` (new) — full guide for pack authors.

### Added — Theme 4B: humanities pack (bundled)

- `src/research_os_humanities/` — 8 protocols + 3 tools + domain detector + 8 router entries.
- Protocols: `archival/archival_research`, `archival/source_provenance`, `textual/close_reading`, `textual/distant_reading`, `method/hermeneutic_method`, `method/digital_humanities_workflow`, `citation/citation_chains`, `output/scholarly_edition`.
- Tools: `tool_humanities_archive_lookup` (Internet Archive / HathiTrust / DPLA / Europeana / Gallica / LoC query planner), `tool_humanities_transcribe` (OCR + correction template), `tool_humanities_citation_chain` (chain-of-custody for quotations).
- Domain detector: TEI/XML files + literary/theological/historical terminology + prose-only corpora.

### Added — Theme 4C: qualitative pack (bundled)

- `src/research_os_qualitative/` — 5 protocols + 2 tools + domain detector + 5 router entries. Extends (does not duplicate) the 6 qualitative protocols already in core.
- Protocols: `coding/coding_scheme_iteration` (open → axial → selective with per-round κ), `validity/member_checking`, `method/grounded_theory_iteration`, `method/thematic_analysis_braun_clarke` (six-phase parametrization + 2019 reflexive correction), `output/qualitative_report_format` (COREQ for interviews, SRQR for general qualitative).
- Tools: `tool_qualitative_codebook_diff` (versioned codebook diff + per-code Cohen's κ), `tool_qualitative_quote_provenance` (quote → participant + transcript + line registry).
- Domain detector: speaker-turn patterns, qualitative-tool artefacts (NVivo / Atlas.ti / MAXQDA / Dedoose), IRB references, small-N demographics.

### Added — Theme 10: stress-test matrix

- `src/research_os/testing/stress_runner.py` — model-agnostic reference-project runner. Accepts any `model_call(messages) → str` callable; CI uses `mock_model_call` which replays canned responses from the project's manifest.
- 5 reference projects under `tests/fixtures/projects/`: `biology_genomics_mini`, `humanities_ms_review`, `qualitative_interviews`, `quick_plot_throwaway`, `mid_pipeline_handoff`. Each ships with a frozen `inputs/` tree, `manifest.yaml` (expected protocols / gates / artifacts / budgets / canned responses), and `cleanup.sh`.
- New CI workflow `.github/workflows/stress.yml` — runs every reference project against the mock model on every PR, uploads per-project JSON results, regenerates `docs/RELIABILITY.md` nightly.
- `docs/RELIABILITY.md` (auto-generated) — public reliability surface. Per-project × per-model success rates, per-protocol breakdown, verbatim failure notes.

### Added — extras

- `pip install research-os[humanities]` and `pip install research-os[qualitative]` reserved as no-op extras (packs ship bundled in this release; the extras stay stable for the future split into separate PyPI packages).

### Added — tests

- 38 new tests under `tests/unit/test_v170_plugins_packs_stress.py` covering: namespace validation, decorator capture, bundled-pack discovery, pack tool dispatch, pack protocol loading, both domain detectors, manifest parsing, mock-model dispatch, all three primary reference projects, RELIABILITY.md rendering, and the two new preflight checks.

### Bumped

- `version 1.6.1 → 1.7.0` in `pyproject.toml`, `src/research_os/__init__.py`, `CITATION.cff`.
- All 114 core protocol YAMLs bumped 1.6.1 → 1.7.0 (consistency across the surface; bundled-pack protocols ship at 1.7.0 from day 1).
- `_router_index.yaml` version 11 → 12.
- Embeddings rebuilt (now 127 protocol docs + 180 tool docs).

### Counts

- Tools surface: 174 → 180 (+5 pack tools, +1 `sys_packs_installed`).
- Protocols: 114 → 127 (+8 humanities, +5 qualitative).
- Preflight: 17 → 19 checks (all green).
- Pytest: 597 → 635 passes.

---

## [1.6.1] — Surface consolidation (Theme 6): cluster tool merges + redirect-stub protocols + deprecation telemetry (2026-06-04)

Refactor release. Implements ROADMAP Theme 6 (surface consolidation):
five tool clusters merge behind one canonical entry each, two
synthesis protocols collapse into a single parametrized form, and a
new deprecation telemetry pipeline (alias / redirect log +
`tool_deprecations_summary`) gives projects an audit trail before the
next MAJOR removes the back-compat layer. Every old name continues
to work end-to-end — the dispatcher injects the implied
`operation` / `kind` / `source` / `mode` / `scope` parameter and logs
the hit. See [docs/MIGRATION.md](docs/MIGRATION.md) for the full
old-name → new-invocation table.

### Added — consolidated tools

- `tool_search(query, source='auto'|'semantic_scholar'|'pubmed'|'crossref'|'arxiv'|'web', limit?)` — replaces the five per-provider search tools. `source='auto'` (default) picks providers from the query domain (biomedical → S2 + PubMed; ML/methods → S2 + arXiv; social → Crossref + S2; geoscience → Crossref + arXiv; generic → web).
- `tool_plan(operation='turn'|'advance'|'clear')` — replaces `tool_plan_turn` / `tool_plan_advance` / `tool_plan_clear`. `tool_plan_step_grounded` stays standalone.
- `sys_path(operation='create'|'abandon'|'list', ...)` — replaces `sys_path_create` / `sys_path_abandon` / `sys_path_list`.
- `tool_ground(mode='explicit'|'from_context', claim, ...)` — replaces `tool_grounding_register` + `tool_ground_from_context`.
- `tool_verify(scope='claim'|'project', ...)` — replaces `tool_claim_verify` + `tool_grounding_verify`.
- `tool_lessons(operation='record'|'consult', ...)` — replaces `tool_lessons_record` + `tool_lessons_consult`.
- `mem_log(kind='methods'|'decision'|'hypothesis'|'analysis', ...)` — replaces `mem_methods_append` / `mem_decision_log` / `mem_hypothesis_update` / `mem_analysis_log`.
- `tool_deprecations_summary` — aggregates counts from `.os_state/deprecations.log` (alias hits + redirect-stub loads) by `kind` / `source` / `target`. Run before upgrading to the next MAJOR.

### Added — protocol consolidation

- `synthesis/printable.yaml` — new parametrized protocol covering both poster (`format='poster'`) and handout / one-pager (`format='handout'` / `'one_pager'`) variants. Quality bars, audience profiles, and steps branch on the format parameter.

### Added — infrastructure

- Protocol loader honours `redirect_to: <target>` + `redirect_params: {...}`. The loader recursively resolves the target, attaches `_redirected_from` + `_redirect_params` to the result for AI context, and logs every redirect to `.os_state/deprecations.log`. Cycles are detected across the whole chain.
- Dispatcher logs every deprecated-alias invocation to `.os_state/deprecations.log` with `kind='tool_alias'`. A new `_ALIAS_PARAM_INJECTION` table injects the back-compat parameter so legacy call shapes keep working without the caller supplying the consolidation argument.
- Preflight adds two new checks: **Alias table complete** (every `_ALIASES` entry resolves to a registered handler; every `_DEPRECATED_ALIASES` entry has a param-injection row) and **Redirect-stub targets resolve** (every YAML with `redirect_to:` points at a real protocol; no stub carries both `redirect_to:` and `steps:`).
- Preflight: 15 → 17 checks. All green.
- `docs/MIGRATION.md` (new) — the complete migration table.

### Improved

- `_router_index.yaml` (version 10 → 11): adds `synthesis/printable` entry; marks `synthesis/synthesis_handout` + `synthesis/synthesis_poster` as redirects in their summaries; updates the handout decomposition to point at the consolidated target.
- 44 new tests in `tests/unit/test_v161_consolidation.py` exercise alias completeness, param-injection coverage, end-to-end old-name behaviour, deprecation logging, redirect resolution, cycle detection, and the new preflight checks. Pytest 553 → 597 passes.

### Migration table

| Cluster        | Old name                          | New invocation                                                          |
|----------------|-----------------------------------|-------------------------------------------------------------------------|
| Search         | `tool_search_semantic_scholar`    | `tool_search(query=..., source='semantic_scholar')`                     |
| Search         | `tool_search_pubmed`              | `tool_search(query=..., source='pubmed')`                               |
| Search         | `tool_search_crossref`            | `tool_search(query=..., source='crossref')`                             |
| Search         | `tool_search_arxiv`               | `tool_search(query=..., source='arxiv')`                                |
| Search         | `tool_search_web`                 | `tool_search(query=..., source='web')`                                  |
| Plan           | `tool_plan_turn`                  | `tool_plan(operation='turn')`                                           |
| Plan           | `tool_plan_advance`               | `tool_plan(operation='advance')`                                        |
| Plan           | `tool_plan_clear`                 | `tool_plan(operation='clear')`                                          |
| Path           | `sys_path_create`                 | `sys_path(operation='create', name=..., hypothesis=...)`                |
| Path           | `sys_path_abandon`                | `sys_path(operation='abandon', path_name=..., rationale=...)`           |
| Path           | `sys_path_list`                   | `sys_path(operation='list')`                                            |
| Ground         | `tool_grounding_register`         | `tool_ground(mode='explicit', claim=..., sources=[...])`                |
| Ground         | `tool_ground_from_context`        | `tool_ground(mode='from_context', claim=..., context_paths=[...])`      |
| Verify         | `tool_claim_verify`               | `tool_verify(scope='claim', claim=..., verifications=[...])`            |
| Verify         | `tool_grounding_verify`           | `tool_verify(scope='project')`                                          |
| Lessons        | `tool_lessons_record`             | `tool_lessons(operation='record', outcome=..., reflection=...)`         |
| Lessons        | `tool_lessons_consult`            | `tool_lessons(operation='consult', task=...)`                           |
| Memory         | `mem_methods_append`              | `mem_log(kind='methods', method=..., ...)`                              |
| Memory         | `mem_decision_log`                | `mem_log(kind='decision', context=..., selected=..., rationale=...)`    |
| Memory         | `mem_hypothesis_update`           | `mem_log(kind='hypothesis', hypothesis_id=..., status=...)`             |
| Memory         | `mem_analysis_log`                | `mem_log(kind='analysis', entry=...)`                                   |
| Protocol       | `synthesis/synthesis_handout`     | `synthesis/printable` (`redirect_params: {format: handout}`)            |
| Protocol       | `synthesis/synthesis_poster`      | `synthesis/printable` (`redirect_params: {format: poster}`)             |

**Compatibility:** old names continue to work for the lifetime of
the current MAJOR. They are scheduled for removal in the next MAJOR.
Run `tool_deprecations_summary` to audit your project's exposure
before then.

### Bumped

- `version 1.6.0 → 1.6.1` in `pyproject.toml`, `src/research_os/__init__.py`, `CITATION.cff`.
- All 114 protocol YAMLs bumped 1.6.0 → 1.6.1 (semantic-routing embeddings rebuilt to track).
- `_router_index.yaml` version 10 → 11.

### Counts

- Tools surface: 166 → 174 (+8 new consolidated tools; old names retained as aliases for back-compat).
- Protocols: 113 → 114 (+1 consolidated `synthesis/printable`; old handout + poster retained as redirect stubs).
- Active surface after consolidation (excluding deprecated aliases / redirect stubs): ~89 distinct tool entry points + ~112 distinct protocol entry points.

---

## [1.6.0] — Model-friendly surface: lean variants, coaching mode, dry-run, tool bundling (2026-06-05)

MINOR release. Implements ROADMAP Themes 2, 7, 13, 15. Makes
Research-OS comfortable on small models (lean variants), pedagogical
for new researchers (coaching mode), reviewable before commit
(dry-run), and call-efficient at end-of-step (bundling). The
consolidation refactor (Theme 6) and new domain packs (Theme 4) are
deferred to later releases.

### Added — Theme 2: lean protocol variants

- `sys_protocol_get(format='lean')` — auto-distils every protocol to
  ≤3 steps + ≤200-char step descriptions + drops optional sub-steps.
  When a protocol declares an explicit `lean_variant:` block at root
  level, that block is served verbatim.
- Pick by `model_profile`: `small` → `lean`, `medium` → `summary`,
  `large` → `summary` (drill in with `step` or `full` as needed).
  AGENTS.md template updated with the matrix.

### Added — Theme 13: dry-run mode

- `sys_protocol_get(format='dryrun')` — returns the protocol's full
  step sequence with predicted tool calls (parsed from each step's
  description body) without executing anything. No files written;
  no state mutated.
- `tool_dry_run(protocol_name, simulated_args?)` — wrapper; useful
  in `supervised` / `coaching` autonomy modes to preview a heavy
  pipeline before committing.

### Added — Theme 7: coaching mode

- `researcher_config.interaction.autonomy_level` accepts a new value
  `coaching` (alongside `manual` / `supervised` / `autopilot`). In
  coaching mode the AI doesn't auto-execute; surfaces
  `pedagogical_prelude` (if present) as a question, explains WHY
  each gate exists before offering the fix, and reads
  `tool_mistake_replay` at session start.
- `tool_mistake_replay(limit?=5)` — reads
  `workspace/.os_state/reliability.jsonl` (gate-fire / tool-error /
  override events) + `workspace/logs/override_log.md`, groups by
  `(protocol, event_type)`, returns top recurring patterns with
  examples. The coaching artifact for self-aware practice.
- Template `researcher_config.yaml` documents `coaching` and the
  pedagogical posture.

### Added — Theme 15: tool bundling

- `tool_step_complete(step_id, override_literature_gate?, override_rationale?)`
  — bundles `tool_path_finalize` + `tool_audit_step_completeness` +
  `tool_audit_step_literature` + `tool_step_revision_options` into
  one call. Returns merged `{stages: {finalize, completeness,
  literature, revision}, overall_status}`. Cuts 4 tool calls → 1;
  eliminates small-model drift between calls. AI still surfaces the
  revision options verbatim per the anti-one-shot doctrine.

### Changed

- Every protocol YAML `version:` bumped `1.5.x` → `1.6.0`.
- `sys_protocol_get` input schema declares `additionalProperties:
  false` and `enum`s the five valid `format` values. Tightens JSON
  schema validation on the MCP layer.
- New tool schemas (`tool_dry_run`, `tool_step_complete`,
  `tool_mistake_replay`) all declare `additionalProperties: false`.

### Tool count

163 → 166. Three new tools (`tool_dry_run`, `tool_step_complete`,
`tool_mistake_replay`).

### Validation

- `python scripts/preflight.py` — 15/15
- `python -m pytest -q` — 553 passed (14 new v1.6.0 regression tests)
- `ruff check src/ tests/ scripts/` — clean
- Embeddings rebuilt against the 166-tool surface.

### Deferred (out of scope this release)

- Theme 6 (146→90 tool consolidation) — needs migration aliases +
  back-compat tests; later release.
- Theme 4 (domain packs) — later release.
- Themes 16-25 (synthesis output formats) — later releases.

---

## [1.5.3] — Token-waste hygiene PATCH: strip historical version commentary from live doctrine (2026-06-05)

PATCH release. Implements ROADMAP Theme 26: live-doctrine vs
historical-commentary separation. Strips inline `v1.X.Y` references,
"as of vN", "previously this clobbered, now we …", and
"promoted from WARN to BLOCK in vN" narrative from protocol bodies,
MCP tool descriptions, and tool-action code comments. Doctrine is now
timeless; version history stays in CHANGELOG + git log + `version:`
/ `last_reviewed:` fields.

### Changed

- 13 protocol YAMLs cleaned (audit/, guidance/, literature/,
  synthesis/, visualization/, writing/). The `version:` field is
  unchanged (PATCH; doctrine unchanged). `last_reviewed:` bumped to
  `'2026-06-04'` on every touched protocol.
- `src/research_os/server.py` — 48 tool-description / section-header
  strings stripped of version commentary. Every `sys_tool_describe`
  + every routing call now sees cleaner descriptions.
- `src/research_os/tools/actions/**/*.py` — 100+ inline comments +
  module docstrings cleaned. Load-bearing "why this is non-obvious"
  comments preserved; "vN added this" narration removed.
- `src/research_os/project_ops.py` + `wizard.py` — cleaned.

### Added

- `scripts/lint_no_version_chatter.py` — regex linter over the live
  surfaces. Flags `v\d+\.\d+(?:\.\d+)?` references plus the common
  "previously this / was the bug / promoted from WARN to BLOCK in vN"
  phrasings. Modes: `--strict` (fail on any hit), `--diff` (fail only
  on hits in files modified vs HEAD), `--quiet` (summary only).
- Preflight check #15: "No historical version commentary in live
  doctrine" — invokes the linter and fails the build if any hit
  remains. Preflight count: 14 → 15.
- `docs/PROTOCOL_DOCTRINE.md` — new "No version commentary in live
  bodies" section codifying the rule, the rationale, and the
  enforcement mechanism.

### Token savings

- Net **−4.4 KB** across 43 modified files (`+443 / −460` line
  count; `+31,120 / −35,514` bytes).
- ~80 chatter-laden lines stripped from the protocol routing surface
  (every routing call now pays less context).
- Embeddings rebuilt against the cleaner descriptions.

### Validation

- `python scripts/preflight.py` — 15/15
- `python -m pytest -q` — all pass
- `ruff check src/ tests/ scripts/` — clean
- No tool count change; no protocol count change; no behavioral change.

### Why a PATCH, not MINOR

Pure refactor — no new tools, no new protocols, no new config knobs,
no behavior change. Existing projects upgrade transparently and pay
fewer tokens per session.

---

## [1.5.2] — Fix v1.5.1 stress-audit blockers that missed the v1.5.1 race (2026-06-05)

PATCH release. Ships the three critical fixes the v1.5.1 stress audit
surfaced after the v1.5.1 release PR had already merged.

### Fixed

- **`templates/researcher_config.yaml`** — adds the `gate_strictness`
  and `project_tier` fields. v1.5.1 wired these in code but missed
  the template, which meant fresh `research-os init` users got
  zero exposure to the new features. Adoption is now actually
  possible.
- **`src/research_os/tools/actions/state/certifications.py`** — a
  transient YAML parse failure used to silently wipe the
  certifications database (load returned an empty dict, next save
  destroyed the audit trail). v1.5.2 distinguishes missing-file
  from corrupted-file via a new `_CertParseError` exception and
  refuses to save over a corrupted file. `self_certify`,
  `list_certifications`, and `has_active_certification` all surface
  the parse error instead of swallowing it.
- **`src/research_os/tools/actions/state/quick_mode.py` —
  `promote_to_step`:**
  - **Path-traversal guard.** Refuses scratch paths that resolve
    outside the project root (`..` or absolute paths).
  - **Step number regex.** v1.5.1 parsed `name[:2]` to compute
    `next_num`; projects with 100+ steps collided. v1.5.2 parses
    the leading-digit run with `^(\d+)_` regex.

### Validation

- `python scripts/preflight.py` — 14/14
- `python -m pytest -q` — 528 passed
- `ruff check src/ tests/ scripts/` — clean
- No tool count change; v1.5.1 surface preserved.

### Why this is a separate PATCH

These fixes were committed to `feat/v1.5.1` AFTER PR #37
(feat/v1.5.1 → dev) had already squash-merged but BEFORE I could
re-push them. The release PR (dev → main) merged on the v1.5.1
commit that didn't include the fixes, then dev was auto-deleted on
merge so the fix branch couldn't catch up. Standard "v1.5.0 race"
pattern surfacing again — v1.5.2 closes it.

---

## [1.5.1] — Adaptive UX: friction scales with rigor + quick mode for throwaway work (2026-06-04)

MINOR release. Stops the AI from being overkill on rigorous researchers
and throwaway work. Two themes from `docs/ROADMAP.md`:

- **Theme 3 — Adaptive friction.** Audit gates scale strictness with
  measured project rigor. A well-set project (substantive methods.md,
  citation density, git, preregistration, commented scripts) earns
  `light` — most blockers become notes. A bare sketch gets `strict`
  — full enforcement. Researcher can override (config or self-certify).
- **Theme 5 — Quick mode.** Explicit throwaway / sanity-check intent
  short-circuits the protocol load entirely. Outputs land in
  `workspace/scratch/`; no audit gates fire. If the result earns its
  keep, `tool_promote_to_step` wraps it in proper provenance
  retroactively.

### Added — Theme 3: adaptive friction

- **`tool_rigor_signals_scan`** — infers trust_score 0-100 across 6
  dimensions (methods.md substantiveness, citation density + PDF
  count, version-control state, preregistration artifact, script
  comment ratio, prior step_summary.yaml quality). Recommends
  strictness (light when ≥75, normal when ≥50, strict when <50).
- **`tool_resolve_gate_strictness`** — resolves effective strictness
  from `researcher_config.gate_strictness` (light | normal | strict |
  auto) + the trust_score. `auto` (the default) follows the score.
- **`tool_self_certify`** — researcher with deep expertise self-certifies
  equivalent work done outside RO. Persisted to
  `workspace/researcher_certifications.yaml`. Allowed domains:
  literature_loop, stack_plan, preregistration, sensitivity_analysis,
  code_review, reproducibility.
- **`tool_list_certifications`** — list active certs.
- **Per-step skip annotations** — `<!-- ro:skip lit_loop, reason: ... -->`
  in `conclusions.md` honoured by audits via
  `step_has_skip_annotation`.

### Added — Theme 5: quick mode

- **`tool_quick_route`** — detects throwaway / sanity-check /
  exploratory intent ("just make me a plot", "quick look", "sanity
  check", "throwaway viz", "quick check", "scratch") and returns a
  route with `complexity='quick'` + `recommended_tool='tool_scratch_write'`.
  Wired into `tool_route` as a pre-step — fires before protocol
  matching.
- **`tool_promote_to_step`** — retroactively wraps a `workspace/scratch/`
  artifact in proper provenance: new numbered step folder, copies the
  file to outputs/figures/ (or step root), emits `.prov.json` sidecar,
  writes minimal conclusions.md + step_summary.yaml.
- **`tool_project_tier_strictness`** — maps
  `researcher_config.project_tier` (throwaway | sketch | production)
  → default gate_strictness (light | normal | strict).

### Improved

- **`researcher_config.yaml` adds two fields** — `gate_strictness`
  (light | normal | strict | auto, default auto) and `project_tier`
  (throwaway | sketch | production, default production). Both optional;
  defaults preserve v1.5.0 behaviour.
- **`tool_route` short-circuits on quick intent** — wired at the top of
  the hierarchical router so quick prompts never load a protocol.

### Fixed — v1.5.0 stress-audit findings rolled forward

PR #36 ("fix(v1.5.0): address 6 stress-audit findings before tag")
didn't merge before v1.5.0 was tagged. The fixes are carried here.

- **`tool_audit_synthesis` override pairing.** `override_no_pdfs=true`
  with an empty `override_rationale` silently bypassed the
  default-deny gate. Now both are required; passing only the boolean
  returns a distinct blocker explaining the rationale is required.
- **`tool_audit_coherence` numbered-list filter.** v1.5.0 only skipped
  items starting with `1.`; items 2-N fell through and produced
  phantom orphan paragraphs. Now matches any digit prefix.
- **`tool_audit_coherence` code-block handling.** v1.5.0 only skipped
  the triple-backtick fence line, not the code body. Now tracks
  `in_code` state so fenced bodies are excluded.
- **`tool_discussion_coverage_audit` single-keyword claims.** v1.5.0
  threshold `max(2, n//2)` made short claims like "BMI rises"
  permanently uncovered. Now requires all-of-N when n ≤ 2. Also
  switched substring match to word-boundary regex (opposite
  false-positive: 'expr' hit 'expression').
- **`tool_path_finalize` first-gate literature check.** v1.5.0
  documented `tool_audit_step_literature` as a hard-stop but never
  wired the call. v1.5.1 wires it: finalize BLOCKs when the step's
  `findings_vs_literature.md` is missing unless
  `override_literature_gate=true` + `override_rationale=...` are
  supplied.

### Validation

- `python scripts/preflight.py` — 14/14
- `python -m pytest -q` — 527 passed (508 v1.5.0 baseline + 19 new
  v1.5.1 regressions, including a router-integration test that
  exercises the full quick-route path end-to-end)
- `ruff check src/ tests/ scripts/` — clean
- Tool count: 156 → 163. Protocol count unchanged at 113.
- Every protocol YAML bumped to `version: '1.5.1'`.

### Migration

Drop-in upgrade from v1.5.0. Two new (optional) config fields. If you
want v1.5.0 behaviour exactly: set `gate_strictness: normal` and
`project_tier: production` in `researcher_config.yaml`. Default
(`auto` + `production`) gives strictly-enforced gates on bare projects
that scale down as the project accumulates rigor signals — which is
what you want unless you intentionally prefer constant strictness.

---

## [1.5.0] — Close v1.4.0 audit gaps + reliability + paywall memory + stale-state + intake re-entry (2026-06-04)

MINOR release. Closes every audit gap surfaced in the v1.4.0 stress test
and adds four telemetry-free local utilities: reliability log, paywall
memory, stale-state detection, intake re-entry detection.

### Added — Theme 1: close v1.4.0 audit gaps

- **`tool_writing_discussion_from_verdicts`** — walks every step's
  `literature/findings_vs_literature.md`, finds DISAGREES + EXTENDS
  verdicts with a Discussion implication, and emits one paragraph per
  verdict into `synthesis/discussion.md` inside HTML-comment markers
  (idempotent — re-runs replace the auto-block; hand-edits outside the
  markers are preserved). Closes the v1.4.0 gap where verdicts never
  reached the Discussion.
- **`tool_discussion_coverage_audit`** — companion BLOCK gate. Every
  non-AGREES verdict in any step's `findings_vs_literature.md` must
  have a matching paragraph in `synthesis/discussion.md` (≥50%
  key-word overlap). Hard-wired into `writing_discussion.validate` —
  there is no override flag; coverage of contested literature is the
  entire point of the Discussion.
- **`tool_audit_synthesis` default-deny when `papers_downloaded == 0`**.
  Synthesis blocks when zero PDFs exist across all
  literature-required steps (`inputs/literature/` also empty). Override
  path: `override_no_pdfs=true` + `override_rationale=...` for
  structurally-unavailable literature (closed field, novel
  measurement).
- **`literature/literature_per_step` is now pipeline-mandatory in
  `analysis_plan`**. v1.4.0 routed it via trigger; v1.5.0 hard-wires
  it as the first gate of `finalize_step`. Steps that are pure data
  engineering set `literature_required: false` in
  `step_summary.yaml` to skip.
- **Missing `scratch/stack_plan.md` — promoted from WARN to BLOCKER**
  in `tool_audit_step_completeness`. Override is by writing the file
  with a one-line rationale, not by flag — the cost of writing the
  rationale down is small and the gap matters at synthesis time.

### Added — Theme 9: telemetry-free local reliability log

- **`tool_reliability_log_event`** — append one JSONL line per
  significant occurrence (gate fire, recovery, abandon, tool error,
  protocol start/complete, override used, stale state, paywall skipped)
  to `workspace/.os_state/reliability.jsonl`. No project content, no
  PII — payloads are redacted (strings >80 chars truncated; nested
  dicts walked). Never phones home.
- **`tool_reliability_report`** — produce a redacted markdown summary
  at `workspace/logs/reliability_report.md` the researcher can paste
  into a GitHub issue when filing a regression report.

### Added — Theme 11: stale-state detection + cross-step coherence

- **`tool_state_freshness_check`** — auto-called by `sys_boot`.
  Surfaces a "stale state — reconfirm?" prompt when (a)
  `workspace/state.json` mtime > 30 days, (b)
  `workspace/citations.md` older than newest
  `inputs/literature/*.pdf`, or (c) per-step `.prov.json` sidecars
  point to scripts that no longer exist. Returns is_stale + signals +
  prompt_for_ai for the AI to surface.
- **`tool_audit_coherence`** — cross-step coherence audit. Scores
  every paragraph in `synthesis/paper.md` against every step's
  `conclusions.md` via Jaccard shingle overlap (no embedding model
  required). Paragraphs scoring < 0.05 in Results / Discussion /
  Intro / Conclusion are flagged orphan — catches the failure mode
  where prose carried over from a prior chat about an abandoned
  step. Writes `workspace/logs/coherence_audit.md`.

### Added — Theme 12: paywall + permanent-error memory

- **`workspace/.os_state/tool_failures.jsonl`** logs URL/DOI tried +
  error + timestamp + tool.
- **`tool_failure_record` / `tool_failure_check` / `tool_failure_list`**
  expose the cache to protocols.
- **`tool_literature_download` and `tool_literature_search_and_save`**
  now pre-check the cache before retrying. Paywall / 404 / 403 errors
  auto-mark `permanent=true` so the cache survives across chats.

### Added — Theme 14: intake re-entry detection

- **`tool_intake_freshness`** — returns `recommended_depth: full |
  refresh-only | skip` based on `inputs/intake.md` substance + age
  (default fresh window 90 days). Skip when substantive AND edited in
  the last 90 days; refresh-only when substantive but older. Also
  flags whether ≥1 numbered step has `conclusions.md` so
  `mid_pipeline_entry` becomes the default routing.
- **`guidance/project_startup`** now calls `tool_intake_freshness` as
  its first substantive step (skips autofill when fresh, routes to
  `mid_pipeline_entry` when steps already exist).

### Improved

- **`sys_boot`** now returns a `freshness` block (is_stale + signals +
  prompt_for_ai) so the AI surfaces drift signals on the first turn.
- **`session_resume`** explicitly calls `tool_state_freshness_check`
  before the resume brief.
- **Orphan tool sweep** — every v1.5.0 tool is referenced from at
  least one protocol; preflight verifies tool refs resolve.

### Validation

- `python scripts/preflight.py` — 14/14
- `python -m pytest -q` — 508 passed (492 baseline + 9 new in
  `tests/unit/test_v150.py`; one existing audit test updated for the
  v1.5.0 stack_plan WARN→BLOCK semantics)
- `ruff check src/ tests/ scripts/` — clean
- Tool count: 146 → 156. Protocol count unchanged at 113.

---

## [1.4.3] — Roadmap published (2026-06-04)

PATCH release. Docs-only — no code or behaviour change. Publishes
`docs/ROADMAP.md` so the v1.5.0 → v2.0.0 plan is on `main` and
available to future contributor / maintainer sessions without
relying on conversation history.

### Added

- **`docs/ROADMAP.md`.** 25-theme plan from v1.5.0 (close v1.4.0
  audit gaps + reliability log + paywall memory) through v2.0.0
  (consolidation cut). Includes per-theme MCP-capability framing
  (what the MCP CAN and CANNOT do), per-release effort estimate,
  and the suggested release sequence table.

### Validation

- `python scripts/preflight.py` — 14/14
- `python -m pytest -q` — 492 passed
- `ruff check src/ tests/ scripts/` — clean
- No code changes; docs-only.

---

## [1.4.2] — README PyPI badge cache-bust (2026-06-04)

PATCH release. README-only — no code or behaviour change. Forces image
proxies (GitHub `camo.githubusercontent.com` + PyPI's README image
cache) to refresh the PyPI version badge, which was still showing
`v1.3.3` for some viewers after v1.4.0 / v1.4.1 shipped.

### Fixed

- **README PyPI badge.** Added `&cacheSeconds=300` to the shields.io
  badge URL (`img.shields.io/pypi/v/research-os.svg`). Tells shields.io
  to refresh every 5 minutes instead of using the default longer
  cache. The new URL also breaks GitHub's stale camo proxy cache (a
  new src URL forces a re-proxy) and the new sdist upload regenerates
  PyPI's rendered README. Both viewers should now see the correct
  current version within minutes of the next release.
- **Note on reality:** the shields.io URL itself was always returning
  the correct version (confirmed via `curl`); only the downstream
  image proxies were serving stale frames. There was never a packaging
  / release-pipeline bug — purely a CDN/proxy cache issue.

### Validation

- No tests touched. preflight 14/14, pytest 492 passed, ruff clean.

### Migration

None — README-only release.

---

## [1.4.1] — Docs sync to v1.4.0 surfaces (2026-06-04)

PATCH release. Docs-only — no code or behaviour change. Closes the gap
between the v1.4.0 release notes and what user-facing docs actually say,
so a fresh reader landing on README / RESEARCHER_GUIDE / USE_CASES sees
the literature loop + language doctrine documented, not just mentioned in
CHANGELOG.

### Fixed

- **Count refs across 8 docs.** `110 protocols` → `113 protocols`,
  `149 MCP tools` → `146 MCP tools` in README.md, FAQ.md, PROTOCOLS.md,
  START.md, AI_GUIDE.md, RESEARCHER_GUIDE.md, TOOLS.md, CONTRIBUTING.md.
- **PROTOCOLS.md category table.** Updated stale per-category counts
  (methodology 29 → 42, synthesis 14 → 17, visualization 6 → 14,
  literature 4 → 5) and total (88 → 113). Added inline v1.4.0 callouts
  per category.
- **TOOLS.md audit section.** Added `tool_audit_step_completeness`
  + new `tool_audit_step_literature` entries with v1.4.0 behaviour
  notes (BLOCK on missing `.summary.md`, WARN on missing
  `stack_plan.md`, BLOCK on missing `findings_vs_literature.md`).
- **RESEARCHER_GUIDE.md.** Surface `literature_per_step`,
  `pick_tool_stack`, and `mixed_language_orchestration` in the
  category inventory with one-line descriptions.
- **AI_GUIDE.md.** Category table now flags which categories grew
  in v1.4.0 + names the new protocols.
- **USE_CASES.md.** New "What's new in v1.4.0" section + 3 new
  rows in the "By output type" table (literature_per_step,
  pick_tool_stack, mixed_language_orchestration).

### Validation

- preflight 14/14, pytest 492 passed, ruff clean — no functional
  changes; tests run for safety only.
- All count references now reflect the authoritative counts from
  `len(TOOL_DEFINITIONS)` (146) and the protocol YAML inventory (113).

### Migration

None — docs-only release.

---

## [1.4.0] — Literature loop + language/tool-stack doctrine + summary fill-rate fix (2026-06-04)

Rolls v1.3.4 fixes + four new pillars driven by user feedback after the 22-turn stress test:
(a) summary.md still empty in places,
(b) literature must be downloaded + cited per step (not just method-grounding at start),
(c) language + tool-set must be chosen carefully (and mixable),
(d) cited-literature must validate or guide each analysis step.

**Stats:** 113 protocols (all bumped to 1.4.0), 146 MCP tools, **491 tests pass** (+10 v1.4.0 regression). Preflight 14/14, ruff clean.

### Added — per-step literature loop

- **NEW protocol** `literature/literature_per_step.yaml` — invoked from `analysis_plan` after `document_conclusions`. Walk: extract top-5 claims from `conclusions.md` → search Semantic Scholar / PubMed / Crossref per claim → download top-3 PDFs into `workspace/<step>/literature/` → write `findings_vs_literature.md` with one `## Claim:` block per finding (Verdict: AGREES | DISAGREES | EXTENDS | DEFERRED + Evidence + Discussion implication) → register `tool_grounding_register` per non-deferred claim → CoVe-verify top-3 with `tool_claim_verify` → update `step_summary.yaml` with a structured `literature:` roll-up.
- **NEW tool** `tool_audit_step_literature` — per-step gate before `tool_path_finalize`. BLOCKS when `findings_vs_literature.md` is missing, any claim lacks a verdict, any DISAGREES verdict lacks a Discussion implication block, all-DEFERRED step has no PDFs in `workspace/<step>/literature/`, or `step_summary.yaml.literature.claims_grounded == 0` without `literature_required: false`. Writes `workspace/logs/step_literature_audit.md`.
- **Extended `audit_synthesis`** (was already v1.3.4 aggregation): now also aggregates per-step `literature_deferred` lists and `literature.claims_grounded == 0` across the workspace and BLOCKS final assembly. Override path: `override_completeness_gate=true` + `override_rationale=…`.
- **Wired 4 grounding tools** into existing protocols (they were orphan in v1.3.x):
  - `tool_ground_from_context` — `guidance/project_startup` registers the PI brief / context files as the upstream grounding anchor.
  - `tool_grounding_register` — `literature_per_step` calls per non-deferred claim.
  - `tool_claim_verify` — `writing/writing_core` + `literature_per_step` call on top-3 load-bearing claims.
  - `tool_grounding_verify` — `analysis_plan.lightweight_step_audit` + `audit/pre_submission_checklist.claim_grounding_audit` run as project-wide gates.

### Added — language + tool-stack doctrine

- **NEW protocol** `methodology/pick_tool_stack.yaml` — sister to `figure_guidelines.pick_library` but at the ANALYSIS level. Domain-to-library matrix: bulk RNA-seq → R Bioconductor (DESeq2/edgeR/limma), scRNA-seq → Python scanpy, Cox PH → R survival/survminer, WGCNA → R, PPI → Python networkx, geospatial → Python geopandas, psychometrics → R psych/lavaan. Steps: enumerate candidates → query field practice via PubMed/Semantic Scholar → check env compatibility → decide on mixing → record in `workspace/<step>/scratch/stack_plan.md`. Routed via `tool_route` triggers ("pick language", "deseq2 or pydeseq2", "seurat or scanpy", …).
- **NEW protocol** `methodology/mixed_language_orchestration.yaml` — explicit doctrine for Python ↔ R ↔ Bash composition WITHIN a single step. Hand-off-file contracts, serialization matrix (TSV / Parquet / .mtx / RDS / pickle / JSON / BED), per-language `pipeline.yaml` tags, schema assertions at consumer entry, per-language env snapshots, tools.md coverage.
- **researcher_config.yaml `tool_stack` block** — new fields: `preferred_languages: [python, R]`, `allow_mixed_language_steps: bool`, `field_practice_overrides_preference: bool`, `cite_field_practice_when_choosing: bool`.
- **Wired `tool_thought_log`, `tool_lessons_record`, `tool_lessons_consult`, `tool_plan_step_grounded`** into `analysis_plan` (consult before step / log decision at decide_next / record reflection after step).
- **Wired `tool_thought_trace`** into `pre_submission_checklist` (replay decision chains during reviewer-response prep).

### Fixed — summary.md fill-rate

- `figures.py::caption_synthesise` — when conclusions.md `## Findings` is prose (no bullets), now sentence-splits the prose + drops markdown table rows + uses the first ≥20-char sentence as "Why it matters." Same root-cause fix as v1.3.4's `path.py::_bullet_lines`, ported to the figure-sidecar code path. Empty "Why it matters" was the dominant cause of stub summary.md files in the stress test.
- `audit.py` — missing `.summary.md` now BLOCKS (was WARN in v1.3.x). Matches `visualization_workflow.yaml`'s stated doctrine ("Any figure WITHOUT .caption.md AND .summary.md is a BLOCKER") that the audit was contradicting.

### Orphan tool resolution (Pillar 4)

The 43-tool orphan-sweep deferred in v1.3.4 was approached additively: wire what's useful, defer removal to v2.0.0. All 9 grounded-reasoning tools (`thought_log`, `thought_trace`, `grounding_register`, `ground_from_context`, `claim_verify`, `grounding_verify`, `lessons_record`, `lessons_consult`, `plan_step_grounded`) now have at least one protocol reference. The remaining ~34 unused tools will be evaluated per-tool in v1.5.0 (wire-or-remove); removal of any non-aliased tool is MAJOR (v2.0.0).

### Validation

- preflight 14/14, pytest 491 passed (+10 v1.4.0 regression tests covering: `audit_step_literature` missing/disagrees-without-discussion/complete-loop/skipped-data-eng-step, `audit_synthesis` literature_deferred BLOCK, `caption_synthesise` prose fallback, `audit` missing-summary BLOCK escalation), ruff clean
- 113 protocols (3 new, all bumped to 1.4.0), 146 MCP tools (1 new), embeddings rebuilt
- pyproject.toml + __init__.py + CITATION.cff + 110 existing protocol YAMLs all bumped together
- `_router_index.yaml` bumped 9 → 10; 3 new entries (`literature/literature_per_step`, `methodology/pick_tool_stack`, `methodology/mixed_language_orchestration`)

### Stress-test driven additions (post 3-agent audit)

After the in-conversation 8-turn verification + 3 parallel audit agents (PI cold review + RO-creator judge + improvement-priorities verifier) converged:

- **`audit/step_literature.py`** — closed a silent-skip loophole: a step whose `conclusions.md` exists but whose `## Findings` section is < 40 chars previously returned `info["skipped"]` and was exempt from the literature gate. This let regenerated step-summary stubs (`findings: []`, truncated headline) opt out of the loop entirely. v1.4.0 now BLOCKS on stub-Findings + non-stub-conclusions; the AI must either repopulate Findings OR explicitly tag `literature_required: false`.
- **`audit/audit.py`** — `audit_step_completeness` now WARNS when a step has scripts but no `scratch/stack_plan.md` (the `methodology/pick_tool_stack` artefact). Promotes to BLOCKER in v1.5.0.
- **`analysis_plan.scope_step`** — added explicit pointer to `methodology/pick_tool_stack` when the step's method choice is non-trivial. Cheap wiring fix; addresses the audit finding that `pick_tool_stack` was orphan in the common path.

### Deferred to v1.5.0 / v2.0.0

Audit-surfaced gaps that ARE real but too large for a v1.4.0 patch:

- **v1.5.0: ingest `findings_vs_literature.md` into `writing/writing_core` Discussion synthesis.** Audit converged-on issue A — DISAGREES verdicts currently never reach the manuscript prose; the sidecar is a write-only side-channel. Fix: `writing/writing_core` discussion-drafting step must read every step's `findings_vs_literature.md` and produce one Discussion paragraph per non-AGREES verdict, citing the contested literature.
- **v1.5.0: default-deny synthesis when `papers_downloaded == 0` across all literature-required steps.** Audit converged-on issue C — `tool_audit_step_literature` only blocks when ALL claims are DEFERRED with no PDFs; mixed AGREES + 0 PDFs sails through, leaving the loop confabulation-anchored.
- **v1.5.0: inject `literature_per_step` into `analysis_plan` decomposition (mandatory between findings-write and `path_finalize`).** Audit converged-on issue D — currently trigger-routed, not pipeline-mandatory; coverage gap (2 of 10 steps had files in the baseline).
- **v1.5.0: promote stack_plan.md from WARN to BLOCK** + auto-invoke `pick_tool_stack` from `methodology/methodology_selection.pick_tools` when the method choice spans language boundaries.
- **v1.5.0: evaluate the ~34 remaining orphan tools** (9 grounding tools now wired); wire-or-recommend-removal per tool.
- **v2.0.0 (MAJOR): tool removal pass** — recommended-for-removal tools dropped.

### Migration notes (v1.3.x → v1.4.0)

- **Backwards-compatible additions.** Existing projects work unchanged; the literature loop is opt-in via `analysis_plan.ground_findings_in_literature` (only fires when AI invokes the new sub-protocol) AND via the new audit gate (which only blocks when run; existing `tool_path_finalize` callers don't auto-invoke it yet — opt in by calling `tool_audit_step_literature` before finalize OR `override_literature_gate=true`).
- **One enforcement tightening:** missing `.summary.md` now BLOCKS at `audit_step_completeness`. Projects with stub summaries that v1.3.x silently warned-but-passed will fail audit at v1.4.0. Resolve by calling `tool_figure_caption_synthesise` per figure OR rerunning `tool_path_finalize`.
- The `tool_stack` block in `researcher_config.yaml` is OPTIONAL; defaults preserve v1.3.x behaviour (`preferred_languages: ["python", "R"]`, `field_practice_overrides_preference: true`).

---

## [1.3.4] — 22-turn stress-test fixes: synthesis audit aggregation + pending-citation block + sub-section regex + dashboard embed_figures (2026-06-04)

Patch driven by a 22-turn agent stress test against a multi-modal Alzheimer's progression project (10 analysis steps including WGCNA + Cox PH + cross-cohort validation). Three audit agents (PI cold review + RO-creator judge + improvement priorities) converged on the same gaps. v1.3.4 closes the P0/P1 set.

**Stats:** 110 protocols (all bumped to 1.3.4), 145 MCP tools, **481 tests pass** (+4 v1.3.4 regression). Preflight 14/14, ruff clean.

### Fixed — `audit_synthesis` is no longer structural-only

The 22-turn test exposed that v1.3.3's audit could pass a 5,529-word paper with 10 per-step "literature grounding deferred" warnings silently — it never opened any `step_summary.yaml`. v1.3.4:

* Aggregates `warnings:` from every `workspace/<step>/step_summary.yaml`.
* `recurring_blockers[]` surfaces signatures that recur across ≥3 steps OR match literature-deferred / pending-verification patterns.
* HARD BLOCKER on `pending verification` citations: `workspace/citations.md` scanned; any unverified count > 0 escalates the audit to `status='error'`. Override via `override_completeness_gate=true + override_rationale=...`.
* New report fields: `propagated_step_warnings`, `recurring_blockers`, `unverified_citations`, `citation_count_pandoc`, `citation_count_authoryear`.

### Fixed — `_section` regex no longer truncates at `###` / `####` sub-headers

`audit.py:134` IMRAD word-count regex was `(?=^##|\Z)` — `###` matched the terminator and clobbered all sub-section content from the parent count. v1.3.4 changes to `(?=^##\s|\Z)`. Turn 22 of the stress test had to demote `### N.M` sub-headers to bold so the audit would count properly; that workaround is no longer needed.

### Fixed — `_bullet_lines` falls back to sentence-split for prose / table Findings

When `## Findings` was prose-led or table-led (no `-`/`*`/`+` bullets), the v1.3.3 extractor returned `[]` and `step_summary.yaml.findings` was silently empty. Turn 8 (step 04 WGCNA) and turn 12 (step 06 hubs) both wrote table-led Findings — both ended up with empty findings in their sidecars, breaking the v1.3.3 "synthesis composes by deterministic merge" promise. v1.3.4 falls back to sentence-split on the prose body, strips markdown table rows.

### Fixed — `audit_synthesis` also counts author-year prose citations

v1.3.3 regex was `\[@key\]|\\cite{key}` only. A paper written in `(Mostafavi et al. 2018)` Markdown style got a misleading `citation_count: 0`. v1.3.4 adds an author-year pattern; report exposes BOTH `citation_count_pandoc` and `citation_count_authoryear`; `citation_count` is the sum.

### Added — `render_dashboard(embed_figures="auto" | "inline" | "relative")`

22-turn test produced a 5 MB `dashboard.html` (95% base64 image data). v1.3.4:

* `"auto"` (default): inline if ≤3 figures AND ≤1 MB total, else `"relative"`.
* `"relative"`: emit `<img src="../workspace/<step>/outputs/figures/<file>.png">` — HTML drops from ~5 MB to ~80 KB, git diffs stay readable, browsers cache figures across regenerations.
* `"inline"`: preserves the legacy base64 single-file behavior — right for `sys_export_share_archive` / email attachments.

Also: `figures_embedded` count now derived from the RENDERED HTML (counts `data:image/` + `<img src="...">`), not from the spec — under-reported by 90%+ on auto-derived dashboards.

### Fixed — STATE.md grammar (truncated "We test whether <q> and " fragment)

22-turn test's research question was compound ("Which gene co-expression modules...and which DEGs are cell-line-specific vs shared?"). The fallback hypothesis template lowercased + prefixed → "We test whether which gene...and " (mid-clause dangle). v1.3.4 detects compound questions (commas + "and"/"or", multiple "?"s, or length >160) and uses a quoted form: `Central question: "<original>"`. Simple questions still get the `"We test whether ..."` rewrite with trailing-conjunction stripping.

### Fixed — `tools.md` regex no longer extracts English stopwords as packages

22-turn test had `tools.md` containing `` `the` — third-party / domain package ``. v1.3.4:

* Tightened regex anchors at line-start (no leading whitespace) so import-like prose in docstrings doesn't match.
* Captured module name must be ≥3 chars.
* New `ENGLISH_STOPWORDS` filter on top of `STDLIB_SKIP`.
* When NO third-party imports are detected, writes an explicit `_(No third-party packages detected ...)_` note so the section marker is created — fixes the idempotency bug where stdlib-only steps wrote NO entry, then got skipped on every subsequent finalize. The 22-turn test had steps 02/06/08/09/10 missing despite being finalized.

### Validation

* preflight 14/14 · pytest 481 passed (+4 new regression tests) · ruff clean
* All 4 v1.3.4 regression tests cover: step-warning aggregation → BLOCKER; pending-verification BLOCKER; author-year citation counter; `###` sub-section word count preservation.

### Deferred to v1.4.0 (MAJOR, deprecation pass)

* Orphan tool sweep — 43 of 145 tools are never referenced from any protocol or shortcut. Includes the entire "grounded reasoning" cluster (`tool_thought_log`/`_trace`, `tool_grounding_register`, `tool_ground_from_context`, `tool_claim_verify`, `tool_lessons_record`/`_consult`, `tool_plan_step_grounded`) — 7 tools, zero protocol uptake. Removing requires MAJOR bump per maintainer rules.
* `_router_index.yaml` decomposition stress: only 51 unique tools referenced; protocol YAMLs collectively reference 111. The gap suggests the router itself under-uses the surface.

---

## [1.3.3] — Anti-one-shot enforcement + step_summary.yaml + synthesis quality gates + dashboard paper-as-interactive (2026-06-03)

The deepest fix in the 1.3.x cycle. AI agents tend to "complete" long
plans as fast as possible — context fills, the AI stops introspecting,
and the output is a sketch. The v1.3.2 e2e exposed this: a 10-step
analysis produced a 900-word paper that used 10 of 17 workspace
figures. v1.3.3 forces mandatory pauses + concrete revision options
+ real quality gates so the AI cannot one-shot through a quality output.

**Stats:** 110 protocols, **145 MCP tools** (+1: `tool_step_revision_options`).
**477 tests pass** (+4 v1.3.3 regression tests). Preflight 14/14. Ruff clean.

### Added — `tool_step_revision_options` (the anti-one-shot gate)

New tool the AI calls AFTER `tool_path_finalize`. Returns:
* `would_benefit_from_revision: bool` — composite heuristic
* `risk_signals: [...]` — e.g. "citations claimed but zero `tool_search_*` calls logged"
* `suggested_revisions: [...]` — specific fixes ("Findings is only 120 chars — should be ≥300 with explicit numbers + figure refs")
* `alternative_paths: [...]` — stratified / sensitivity / method-comparison branches the researcher could fork via `branch_of=<step>`
* `handoff_recommended: bool` — true when ≥5 steps have been finalized this conversation
* `n_finalized_steps_this_project: int`

The AI MUST present these VERBATIM to the researcher and WAIT for their choice (`proceed | revise | branch | handoff`). Refuses to auto-scaffold the next step unless `autonomy_level == 'autopilot'` AND `would_benefit_from_revision is False`.

### Added — `analysis_plan.present_to_researcher` mandatory pause step

New mandatory step in `guidance/analysis_plan` that runs IMMEDIATELY after `finalize_step`. Calls `tool_step_revision_options`, formats the output as a 4-choice question, and explicitly forbids auto-scaffolding the next step in the same turn. New ONE-SHOT GUARD: if the AI calls `sys_path_create` immediately after `tool_path_finalize` without calling `tool_step_revision_options` first, the routing log flags this as a protocol violation.

### Added — `step_summary.yaml` sidecar at finalize

Structured machine-readable mirror of `conclusions.md` the synthesis pipeline consumes deterministically (no NLP parsing). Fields: `headline`, `methods_block`, `plain_language_summary`, `findings: [...]`, `decision`, `limitations: [...]`, `references_to_ground: [...]`, `figures: [{name, path, caption_path, summary_path, audit}]`, `tables: [...]`, `reports: [...]`, `warnings: [...]`.

### Added — `synthesis_paper` multi-turn enforcement doctrine

The protocol description now enforces ONE section per researcher prompt (turn 1: outline → turn 2: methods → turn 3: results → … → turn 10: cover letter). The AI refuses to chain >1 section per turn. A real paper deserves the deliberative pace + the context window stays healthy.

### Added — quality-bar gates on `tool_audit_synthesis`

`audit_synthesis` now computes per-section word counts vs MIN_BAR (abstract 150 / introduction 300 / methods 400 / results 400 / discussion 300; total ≥1500) AND `figure_coverage_ratio = figures_used / figures_available_in_workspace` (target ≥0.8). Emits `gate_blockers: [...]` with specific revision instructions per gap. Escalates to `status='error'` (BLOCKER) ONLY when total ≥500 words — stub-shaped papers get the same gaps as warnings so the AI sees where to expand but isn't blocked on a sketch.

### Added — per-step retrospective at finalize (Anticipated reviewer questions)

`tool_path_finalize` auto-appends `## Anticipated reviewer questions` to conclusions.md (idempotent). Content-aware questions based on methods + limitations + figure/table counts (e.g. "On n=12, how reliable are dispersion estimates?"). Self-critique scaffold so the AI sees its weaknesses before synthesis.

### Added — dashboard.py paper-as-interactive rewrite

`_figure_block` now emits, per figure: clickable static image (lightbox via `<a target='_blank'>`), technical caption, **`.summary.md` plain-English sidecar in `<aside class='figsummary'>`**, and **interactive HTML companion in `<details><summary>↗ Open interactive companion</summary><iframe ...></iframe></details>`** when one exists. Plus CSS for the new blocks. The dashboard now actually implements what the v1.3.1 protocol described.

### Added — long-context handoff hint in `sys_boot`

`sys_boot` response now includes `handoff_recommended: bool` (true when ≥5 finalized steps) + a `handoff_hint` string the AI surfaces to the researcher. Prevents the "AI one-shots step 6, 7, 8 in lossy context" failure mode.

### Validation

* preflight 14/14 · pytest 477 passed · ruff clean
* 4 new regression tests: `test_step_revision_options_flags_placeholder_conclusions`, `test_step_revision_options_clean_step_passes`, `test_finalize_emits_step_summary_yaml`, `test_finalize_appends_anticipated_reviewer_questions`

---

## [1.3.2] — Multi-language env hardening + richer intake + comment-preserving config + exploratory hardening (2026-06-03)

Post-v1.3.1 patch focused on three explicit researcher asks +
exploratory hardening surfaced by the e2e test bed.

**Stats:** 110 protocols, 149 MCP tools. 473 tests pass.
Preflight 14/14, ruff clean.

### Added — multi-language environment hardening

* `_detect_languages_in_use` now reads BOTH `workspace/` scripts AND
  `inputs/raw_data/` file types. FASTQ/BAM/VCF → `domain_hint:bioinformatics`;
  H5AD/loom → `single_cell`; NIfTI/DICOM → `neuroimaging`; shp/geojson →
  `geospatial`; sav/sas7bdat/dta → `survey`; edf/bdf → `eeg`; mat →
  `matlab_interop`. Also detects Rust (`Cargo.toml`), Go (`go.mod`),
  Node (`package.json`).
* `sys_env_snapshot` returns a `domain_hints` field + writes a
  `environment/language_recommendations.md` listing the canonical
  package stack per detected hint (e.g. bioinformatics →
  Bioconductor/DESeq2/edgeR if R is present, pysam/biopython if
  Python-only).
* When ≥2 non-shell languages detected, auto-generates
  `environment/Dockerfile.suggested` (Python + R + Julia + Quarto
  base layers as needed). Researcher reviews and renames to
  `Dockerfile` when ready.

### Added — richer `docs/research_overview.md`

`tool_intake_autofill` now writes a multi-section overview instead
of just question + hypotheses:

* Project + domain header with "_Why this domain_" rationale
* Research question
* Background (auto-extracted snippet from `inputs/context/*.md`)
* Hypotheses (with explicit fallback prompt when none inferable)
* Input data inventory table (file path, size, row count for
  CSV/TSV)
* Planned analyses placeholder + back-links to existing numbered
  steps
* Literature-to-find checklist from extracted named-paper
  references — checkbox-style for trackable progress

### Added — comment-preserving `researcher_config.yaml` writer

`config.py` now uses `ruamel.yaml` (added to core deps) for
round-trip YAML. The rich inline help comments in `CONFIG_TEMPLATE`
survive every override write — previously every `cli.py init` /
wizard / `sys_config_set` call stripped them via PyYAML. Falls back
to PyYAML with a logged warning if `ruamel.yaml` isn't installed.

### Added — researcher_config consultation in session handoff

`sys_session_handoff` now prepends a "Researcher config (consult
before acting)" section to the handoff doc summarising autonomy /
quality_gate_policy / ambiguity_posture / model_profile /
shared_server / writing_preferences / output types / target venue /
researcher identity / API keys configured. A fresh AI session
reading the handoff doc sees these without a separate
`sys_config_get` call.

### Added — `analysis_plan.ground_methods` is now a HARD GATE

(Continued from v1.3.1 round 2; explicitly named here for the
release notes.) Replaced prose with 4-action sequence; anti-pattern
"We use X because it's standard" rejected; correct form names
paper + DOI + saved PDF + why.

### Added — anti-hallucination grounding warning at finalize

(Continued from v1.3.1 round 2.) `tool_path_finalize` scans
`workspace/logs/searches.log` and warns when `conclusions.md` cites
references but zero `tool_search_*` calls were ever logged.

### Hardened — exploratory fixes

* **`slugify`**: caps at 40 chars + explicit defence against
  `..` / `/` path-traversal sequences (in addition to the existing
  regex strip).
* **`_load_active_plan`**: auto-archives plans older than 7 days
  (with `status: in_progress`) into `.os_state/handoffs/` so a
  stale abandoned plan doesn't keep being surfaced as the
  "active next-action" by `sys_boot`.
* **`_update_workflow_mermaid`**: silently no-ops when `root` isn't
  a Research-OS project (no `.os_state/`). v1.3.1 confirmed the
  pollution-prevention pattern via raise-on-write in
  `create_numbered_experiment`; this generalises to every other
  writer.
* **`branch_of` validation**: confirmed `create_numbered_experiment`
  raises `ValueError` with a clear message when `branch_of` names
  a step that doesn't exist on disk (was already correct; verified
  + documented).

### Maintainer

* Added `TODO.md` (gitignored) for deferred work: project_ops folder
  refactor, `tool_pi_review`, `tool_synthesis_curate_figures`,
  `tool_protocol_freshness_check`, `methodology/small_n_studies`
  protocol, `tool_figure_html_smoke_test`, Bloom-filter author
  check, DOI/PMID extractor, `tool_step_initial_inspect`,
  decision-verb-shape audit gate, length-based stub check.

---

## [1.3.1] — PI-level e2e gap-closure: finalize completes the picture + grounding + aesthetics + paper PDF + dashboard-as-paper (2026-06-03)

### Round 2 — additional gap-closures the same day

After the round-1 fixes shipped, the researcher surfaced a deeper
set of gaps the same day. Round 2 closes the next layer:

**FIXED — workspace-pollution guard.** `_update_workflow_mermaid`
now refuses to write into ``root/workspace/`` unless ``root`` is a
valid Research-OS project (``.os_state/`` present). A v1.3.0
misconfigured caller had silently written
`workspace/workflow.mermaid` into the Research-OS source repo;
guard prevents this class of bug across every writer.

**ADDED — anti-hallucination grounding warning at finalize.**
`tool_path_finalize` now scans `workspace/logs/searches.log` and
warns when `conclusions.md` cites references but ZERO
`tool_search_*` calls have been logged for the project. The
citations may be coming from training memory rather than
verifiable lookups; the warning makes that visible at every step
finalize so the AI / researcher can run actual searches before
submission. Surfaces as a BLOCKER at pre-submission audit.

**STRENGTHENED — `analysis_plan` `ground_methods` is now a HARD
GATE.** Replaced "you SHOULD search literature" prose with explicit
4-action sequence:
  (1) surface candidate methods online (`tool_research_method` +
      parallel `tool_search_semantic_scholar` + `tool_search_pubmed`
      + `tool_search_web` "best <method> 2024 2025"),
  (2) ground each decision in a SPECIFIC paper saved into the
      step's literature folder via `tool_literature_search_and_save`,
  (3) compare findings to current literature (flag divergence
      from recent published numbers),
  (4) record the decision-with-citation chain via
      `mem_methods_append` + `mem_decision_log` + `mem_hypothesis_update`.
Anti-pattern explicitly named:
  "We use DESeq2 because it's standard" → ungrounded; rejected.
  "We use DESeq2 (Love, Huber, Anders 2014, doi:10.1186/...) because
   the n=8 design benefits from empirical-Bayes shrinkage..." → correct.

**ADDED — `figure_guidelines` publication-aesthetics block.**
Past the existing pitfall catalog: a `publication_aesthetics`
section spelling out the moves that lift figures from "default
ggplot output" to publication-grade:
  - pick a stylesheet (SciencePlots / theme_classic / latimes), patch
    rcParams once in a project-wide `viz_style.py`
  - pin a font stack (Inter / Helvetica Neue / Source Sans / Roboto
    / Liberation Sans → DejaVu Sans fallback)
  - set `figsize` from the destination (single-column = 3.5", two-
    column = 7.2", 16:9 slide = 13.3×7.5") BEFORE adjusting fonts
  - annotate the data, not the chart (inline callouts > caption-only)
  - color palettes beyond Okabe-Ito (`glasbey` via `colorcet` for
    >8 categories; `cmocean` for continuous; `TwoSlopeNorm` for
    diverging-with-emphasis)
  - iconography for categorical encodings (inline labels > legend)
Plus references the AI should consult online before unfamiliar chart
kinds: Wong 2011 (Okabe-Ito), Wilke 2019 (Fundamentals of Data Viz),
Tufte 2001, Cleveland & McGill 1984, Heer & Bostock 2010, Healy 2018,
Frank Harrell BBR.

**OVERHAULED — `synthesis_paper` `compile_pdf` step.** Was
optional; now DEFAULT for any serious draft. Decision tree maps
the venue/output to LaTeX (journal class files) vs Typst (modern
preprint / thesis / general manuscript) vs poster vs dashboard.
Typst conversion is explicitly supported with proper preamble,
inline figure embedding, and CSL bibliography style. paper.md is
the WORKING DRAFT; paper.pdf is the deliverable. Markdown alone
is not a publication artefact.

**OVERHAULED — `synthesis_dashboard` reframed as paper-as-interactive.**
Was a metrics-overview screenshot gallery. Now: the paper, told as
an interactive guided walk-through. Section order mirrors the paper
1:1 (TL;DR/abstract → intro → methods → findings → discussion →
limitations → reproducibility → references). Every figure ships
with BOTH its `.caption.md` AND its `.summary.md` inline (the
paper has only the caption; the dashboard adds the accessible
summary — that's what makes it "guided"). Findings ordered by
HYPOTHESIS, not by step number. Inline "Why?" expanders next to
methods sentences reveal the conclusions.md `## Methods (full
detail)` block + linked citation. Hover/lightbox opens the full
SVG. Visual coherence with the paper PDF (same font, palette,
spacing).

**VALIDATION (round 2):** preflight 14/14, pytest 473 passed
(round 1 already brought this up), ruff clean.

### Round 1 — initial gap-closures (earlier same day)

Patch release after a 10-step PI-level genomics e2e (Himes 2014
airway-DE replication with 6 cell lines × 2 conditions × 2 sequencing
batches; produced a 12-section paper.md + abstract.md + dashboard.html
+ 17 PNG/SVG figures + 1 interactive Plotly companion). Three parallel
sub-agents (PI-walks-in-cold audit / Research-OS-system judge /
improvement-priorities engineer) surfaced 21 + 18 + 12 specific gaps;
v1.3.1 closes the P0/P1 set.

**Stats:** 110 protocols, 149 MCP tools. **473 tests** pass (was 467;
+6 regressions for the new finalize behaviors + the named-paper false-
match guard). Preflight 14/14, ruff clean.

### Fixed — `tool_path_finalize` now actually completes the picture

Six finalize-time behaviors were either missing or wired to the wrong
target. The e2e exposed each. All six fixed:

* **Env auto-snapshot lands in the PROJECT-GLOBAL folder.**
  v1.3.0 added the auto-snapshot but called `env_snapshot(root)` with
  no `scope=`, which lands in the most-recent active step's folder
  rather than `environment/requirements.txt` at project root.
  v1.3.1 passes `scope='project'` so the project-global file actually
  populates with pinned versions (the e2e's was a comment-only template
  through all 10 finalizes).
* **`workspace/citations.md` scrapes `## References to ground` from
  every step's `conclusions.md`.** Previously the project bibliography
  only assembled from `inputs/literature_index.yaml` + per-step
  `*.meta.yaml` sidecars, which the AI typically doesn't write. Now the
  citations file actually fills in (the e2e's went from empty → 20+
  scoped entries across the 10 steps).
* **Per-step `literature/key_papers.md` auto-populates** from the same
  `## References to ground` section. Was a seed template the AI never
  filled in across all 10 e2e steps.
* **`mem_decision_log` mirrors the `## Decision` verb at finalize.**
  Across all 10 e2e steps the decision-log was empty even though
  every `conclusions.md` had a clean `## Decision\nPROCEED ...` block.
  Finalize now extracts the verb (PROCEED / BRANCH / DEAD-END / HOLD /
  ABANDON), validates it, and calls `log_decision`. Idempotent on the
  marker `step=<id>; verb=<V>`.
* **Step status flips `active → completed`.** Previously even a fully
  finalized step kept `status: active` in the ledger, so STATE.md
  showed `→` instead of `✓` until the next `sys_path_create` flipped
  it as a side effect. Finalize now updates the ledger directly and
  re-renders STATE.md.
* **`workspace/tools.md` filters stdlib noise** (pathlib, sys,
  warnings, json, re, …). v1.3.0's auto-import scan listed every
  imported module; v1.3.1 keeps only the third-party / domain stack
  (statsmodels, pandas, plotly, scipy, …).

### Fixed — `visualization/interactive_figure_design` was unroutable

The new v1.3.0 protocol was registered with `intent_class: visualize`
+ `sub_intent: interactive_figure` — neither exists in the router's
`hierarchy:` block, so semantic + trigger routing both silently
ignored it. Re-mapped to `intent_class: synthesize` +
`sub_intent: interactive` (the closest valid hierarchy node).

### Fixed — `audit_figure_quality` SVG label-overlap heuristic now sees matplotlib output

The v1.3.0 regex expected `<text x= y= >...</text>`. matplotlib's
`savefig(*.svg)` actually emits
`<g transform="translate(X Y)"><text>...</text></g>` — the v1.3.0
regex missed every matplotlib SVG. Added a second pattern that parses
the `transform="translate(...)"` wrapper, so the heuristic now fires
on the figures most AI agents actually produce.

### Fixed — `_extract_named_papers` false-matches

Patched in the round-3 work but solidified here with regression test
(`tests/tools/test_intake.py::test_extract_named_papers_excludes_months_and_journals`).
Stop-list now covers month abbreviations + names + days + common
journal-name first-words (Biology, Cell, Nature, Science, PNAS, Genet,
Genome, Methods, Genetics, Lancet, BMJ, JAMA, Cancer, Brain, Heart,
Kidney, Blood). The "Himes BE, et al PLOS ONE 2014" pattern still
matches; "Nov 2014" / "Biology 2014" do not.

### Fixed — AGENTS.md template no longer references `tool_figure_create`

`templates/AGENTS.md` rule #10 still recommended the removed v1.3.0
tool. Rewrote to point at `visualization/figure_guidelines` +
`tool_figure_palette` + `tool_audit_figure_full` +
`visualization/interactive_figure_design`.

### Added — `sys_path_create` inputSchema exposes the finalize-gate bypass

The v1.3.0 finalize gate (refuse step N+1 while step N is placeholder)
worked but was undiscoverable — the bypass field wasn't in the public
schema, so the AI couldn't ask for it. v1.3.1 adds
`allow_unfinalized_predecessor` + `override_rationale` + `from_step`
to the inputSchema. When the AI bypasses, the rationale is logged to
`workspace/logs/override_log.md` and surfaced at pre-submission audit.

### Added — `figure_guidelines` pitfalls catalog: 3 new entries from the e2e

* `legend_missing_shape_or_color_key` — when color + shape both encode
  variables but only one has a legend (e2e step 04 PCA).
* `invisible_legend_swatches` — white-fill `mpatches.Patch` with thin
  black edge becomes invisible at small sizes (e2e step 01).
* `bar_chart_with_zero_range_artifact` — three bars at 305/340/395
  look identical when y starts at 0; annotate values or crop axis
  (e2e step 06).

### Added — `interactive_figure_design` gains "ship offline-capable HTML" step

Plotly's default `include_plotlyjs=True` embeds the CDN URL. For
reviewers behind firewalls or archival readers, the file must use
`include_plotlyjs='inline'`. Protocol now lists the offline-capable
variant per library (Plotly / Bokeh / Altair).

### Changed — Docs counts refreshed

`docs/{TOOLS,PROTOCOLS,README,START,RESEARCHER_GUIDE}.md` +
`CONTRIBUTING.md` now say **149 MCP tools** + **110 protocols** to
match the actual count. (v1.3.0 docs claimed 143-145 tools + 88-100
protocols depending on file.)

### Changed — Every protocol YAML bumped to `version: 1.3.1`

Per maintainer guidance (any release that touches a finalize-time
behavior is a behavior change visible to every protocol). 110
protocols updated.

### Migration

None. All v1.3.0 callers continue to work. The new finalize behaviors
fire automatically; the new `sys_path_create` schema fields are
optional. If a v1.3.0 project's `workspace/citations.md` or per-step
`literature/key_papers.md` is stale, re-run
`tool_path_finalize` on each step to back-fill.

---

## [1.3.0] — Guidance-not-code doctrine + cross-project profile + step-gate enforcement (2026-06-03)

Three audit rounds against a graduate-level genomics e2e (Himes 2014
airway RNA-seq differential expression) + a parallel
"PI-walks-into-the-project-cold" sub-agent audit. Each round surfaced
architectural gaps that needed protocol + scaffold fixes rather than
patches.

**Stats:** 110 protocols (+1 new: `visualization/interactive_figure_design`).
144 MCP tools (-1: `tool_figure_create` removed, see Migration). 467
tests pass (was 453; +14 regressions across the rounds). Preflight 14/14,
ruff clean.

### Migration — `tool_figure_create` removed (guidance, not code)

The doctrine: **Research-OS is a guidance system, not a chart library.**
The AI writes its own matplotlib / ggplot2 / Altair / plotnine / d3 /
plotly script tailored to its dataset and field — guided by
`visualization/figure_guidelines`. Tools support that workflow with
audit + sidecar + palette utilities, not premade chart code.

* `tool_figure_create` is gone. Old callers receive a friendly
  deprecation message via the `_REMOVED_TOOLS` dispatcher entry that
  points at the protocol.
* The 30+ `_render_*` chart-kind dispatchers in
  `tools/actions/viz/figures.py` are gone with it. The module is now
  ~400 lines of palette + caption-sidecar + audit utilities.
* `tests/unit/test_viz_renderers.py` removed.
* `tool_figure_palette`, `tool_figure_caption_synthesise`, and
  `tool_audit_figure_full` are unchanged.
* All 21 protocol YAMLs that referenced `tool_figure_create` were
  updated to point at `visualization/figure_guidelines` instead.

### Added — `visualization/interactive_figure_design` protocol

Per-figure interactivity (hover, brush, zoom, lasso) as a companion to
the static PNG/SVG — NOT a dashboard, not a paper figure.
Library-by-data-type table (plotly / Altair / mpld3 / pyvis / igv.js /
cellxgene / glimma), interaction-design checklist, mandatory static
fallback. Router-indexed at `intent_class=visualize,
sub_intent=interactive_figure`.

### Added — `workspace/tools.md` (4th project-scope log)

Joins `methods.md` / `analysis.md` / `citations.md` as an append-only
project log. Tracks which Research-OS tools, 3rd-party packages, and
external services each step depended on — so a reviewer can audit
reproducibility without re-deriving the stack from scripts.
`tool_path_finalize` auto-appends a per-step section from
`conclusions.md` (Tools/Software/Methods) plus a fallback that scans
`scripts/` for top-level imports.

### Added — Project-root `README.md` from init

The GitHub / repo-browser-cold-open front page (distinct from
`GETTING_STARTED.md`, which targets the researcher actively driving
this project). Pre-fills the project name + research question +
domain when set via the wizard. Includes a "Reproducing the analysis"
block so a fresh clone can be re-run without inside knowledge.

### Added — Cross-project researcher profile

`~/.config/research-os/profile.yaml` (XDG-compliant) seeds the wizard
with the researcher's saved name / email / institution / ORCID +
api_keys + writing_preferences. The wizard's Step 6b asks once; future
projects auto-populate. Per-project `inputs/researcher_config.yaml`
always wins on conflict. Chmod 600 (api keys may be present).

### Added — Eager `inputs/{raw_data,literature,context}/` with seeded READMEs

`GETTING_STARTED.md` told researchers to drop files at these paths but
the directories were lazy and didn't exist yet (`cp foo.csv
inputs/raw_data/` failed without `mkdir -p`). Now eager + each ships a
one-paragraph README explaining what belongs there.

### Added — Step-finalization enforcement gate

`create_numbered_experiment` now refuses to scaffold step N+1 while
step N is still in placeholder form (README has stub markers,
conclusions.md is template). Audit surfaced the failure mode: the AI
moved from step 01 to step 02 without finalizing step 01, leaving
`workspace/analysis.md` missing the step 01 entry. The MCP
`sys_path_create` handler accepts
`allow_unfinalized_predecessor=true` (with rationale logged to
override_log) for legitimate data-plumbing-only steps.

### Added — `data/project_inputs` symlink on every step

Steps with `from_step` symlinked `data/input` to the previous step's
`data/output/`, which is empty when the upstream step wrote to
`outputs/` (figures/tables/reports) rather than `data/output/`.
Audit surfaced: step 02 inherited an empty data/input. Every step now
also gets a `data/project_inputs` symlink pointing back at the
project's `inputs/raw_data/` as a fallback.

### Added — `create_numbered_experiment` validates root

Refuses to scaffold if `root/.os_state/` is missing. Audit surfaced
a real bug: a misconfigured caller had silently created a step
folder in the Research-OS source repo. No more silent cwd pollution.

### Added — Online-research step in `guidance/project_startup`

Before declaring startup complete, the AI MUST run at least one
`tool_search_*` / `tool_research_method` pass on the research
question + named-paper references the PI brief surfaced. Search log
goes to `workspace/logs/search_log.md`. Closes the "AI relies on
pre-training memory instead of current literature" gap.

### Added — `intake_autofill` smarter extraction

* Natural-language hypothesis detection — when an explicit
  H1/H2/H3 list is absent, picks out sentences like "We
  hypothesise…", "X is associated with Y", "replicates the…",
  "differs across…".
* Named-paper extraction — PI brief references like "Himes 2014",
  "the GTEx airway atlas" surface as `named_paper_references` +
  concrete `next_actions` ("run `tool_literature_search_and_save
  query=…`").
* Fallback hypothesis from research_question when nothing else found
  ("We test whether …").

### Added — Multi-script chronological naming (`01a_`, `01b_`, `01c_`)

`guidance/analysis_plan.yaml` `write_atomic_scripts` step now
explicitly recommends letter-suffix naming for sub-tasks meant to
run in a fixed sequence — `01a_load_counts_v1.py` /
`01b_library_size_qc_v1.py` / `01c_pca_v1.py`. The descriptive-only
naming stays available for true DAGs with non-linear dependencies.

### Added — `figure_guidelines` pitfall catalog expansion

New pitfalls added from the e2e:

* `label_overlap_on_scatter_or_volcano` — use ggrepel / adjustText.
* `y_axis_clipped_by_extreme_values` — cap p-values at 1e-30, annotate.
* `filtered_but_labeled_points` — don't plot a label at coordinates
  the point doesn't truly occupy (e.g. IL6 + CCL2 below low-count
  filter showing at y=0 with full labels).
* `heatmap_columns_not_grouped_by_annotation` — sort columns BEFORE
  plotting; the eye can't see treatment blocks if conditions
  alternate.
* `heatmap_title_overlapping_annotation_strip` — use gridspec, not
  `add_patch` at negative y-coords.
* `font_size_too_small_at_paper_scale` — set figsize to final print
  slot.
* New `pick_library` step: research the right plotting stack for the
  data type FIRST (RNA-seq → ggplot2 + EnhancedVolcano; single-cell
  → scanpy; GWAS → qqman; not always matplotlib).

### Added — `audit_figure_quality` SVG label-overlap heuristic

When the figure is SVG, scans `<text>` elements for nominal
bounding-box collisions and surfaces ~N suspected overlaps as
warnings. PNG-only figures get a "ship the SVG too" warning so the
deeper audit can run.

### Added — `tool_path_finalize` auto-snapshots env

If a step produced outputs (figures/tables/reports) but
`environment/requirements.txt` is still the comment-only template,
finalize calls `sys_env_snapshot` automatically. Closes "env folder
is generic, not project-specific" gap from the e2e audit.

### Added — `plain_english_summary` detection from `conclusions.md`

Previously only checked `context/notes.md` — but the AI wrote the
summary inside `conclusions.md` (the natural place), so finalize
flagged it as missing. Now scans both, plus accepts several heading
variants ("Plain-language summary", "Plain-English summary", "TL;DR",
"Lay summary").

### Removed — `.os_state/state_ledger.yaml` duplicate

The yaml mirror of `state_ledger.json` was redundant — STATE.md at
project root + the JSON ledger cover both human + machine reading.
`.os_state/` is now 3 files instead of 4 (manifest.json,
state_ledger.json, state_ledger.lock; active_plan.json appears only
during live planning).

### Changed — Every protocol YAML bumped to `version: 1.3.0`

Per maintainer guidance (MINOR bump = bump every protocol). 108
protocols updated.

### Changed — Researcher-facing docs counts

`docs/{START,FAQ,README,AI_GUIDE,RESEARCHER_GUIDE}.md` updated:
"100 protocols" → "110 protocols", "six visualization protocols" →
"14 visualization protocols".

### Fixed

* `_has_user_inputs` no longer counts the seeded
  `inputs/{raw_data,literature,context}/README.md` as user content
  (would have re-triggered intake regen on cold init).
* `_REMOVED_TOOLS` dispatcher entry routes `tool_figure_create`
  callers to a clear migration message instead of "Unknown tool".
* `_router_index.yaml` decomposition entries that contained
  `tool_figure_create` were cleaned up (would otherwise emit
  "unknown tool 'an AI-authored plotting script'" preflight errors
  after the bulk sed).
* `_write_project_root_readme` f-string escaping fixed
  (`{figures,tables,reports}` was interpreted as a format spec).

### Validation — full graduate-level e2e analysis

After the structural changes below, an end-to-end research project
(Pygoscelis penguin bill morphometrics, n = 334) was driven through
Research-OS as the AI client would: 3 numbered steps (baseline EDA →
two-way ANOVA + Tukey + Kruskal-Wallis sensitivity → allometric
regression), each with its own `pipeline.yaml` + 2–4 atomic scripts +
4/2/2 publication-grade figures + 3/4/2 tables + 2/2/1 reports +
substantive `conclusions.md` (~120 lines each). The synthesis paper
weighs in at ~1,400 words. Every per-step finalize updated
`workspace/analysis.md`, `workspace/methods.md`, and
`workspace/citations.md` without manual intervention. The e2e run
surfaced six follow-on bugs (see below) — all fixed in this same
release with regression tests pinning each one.

### Added — `sys_env_snapshot` accepts a target scope

`sys_env_snapshot` previously only wrote into the most-recent active
numbered step (a hidden global), which made it impossible to snapshot
the project-wide environment, or a specific step that wasn't the
latest. v1.3.0 adds:

* `step_id="NN_slug"` — snapshot into `workspace/NN_slug/environment/`.
* `scope="project"` — snapshot into the project-global `environment/`
  folder (newly eager-scaffolded — see below).
* Omit both → legacy behavior (most-recent step, or project-global
  when no numbered steps exist yet).

### Added — `tool_path_finalize` now updates the project-scope logs

`finalize_path` was purely observational (rewrote per-step READMEs
from on-disk state). v1.3.0 extends it to refresh the project-scope
append-only logs the AI was supposed to be touching manually but
typically forgot:

* `workspace/analysis.md` ← step-finalized heading + headline from
  Findings + output counts + decision count (idempotent on the
  step-named marker).
* `workspace/methods.md` ← if `conclusions.md` has a `## Methods
  (full detail)` (or `## Methods`) section, mirrored under a
  step-tagged subsection.
* `workspace/citations.md` ← regenerated from project-level
  `inputs/literature_index.yaml` + every per-step
  `literature/.meta.yaml` sidecar.

`finalize_path` also returns a `warnings` list surfacing:
* stub `Findings` / `Decision` / `Plain-language summary` sections in
  `conclusions.md`,
* missing environment snapshot when the step produced outputs.

These are nudges, not blockers — the AI can override with a
`mem_decision_log` rationale if the omission was deliberate.

### Improved — init scaffolding (`research-os init`)

* **`CONTRIBUTORS.md` is no longer created at init.** The previous
  default produced an opaque audit file in every fresh project that
  confused new researchers and was outdated the moment they added an
  IDE. It's now opt-in — written on the first `research-os ide
  add|remove` (or explicit share action). Behavior in tests:
  `tests/unit/test_core.py::test_scaffold_creates_complete_workspace`
  now asserts it does NOT exist after a cold scaffold.
* **`environment/` is now eager + scaffolded.** Previously a LAZY_DIR
  (folder absent until something wrote into it). Researchers reported
  not knowing whether the project even had a reproducibility story.
  v1.3.0 ships:
  * `environment/requirements.txt` — pip stub with a header pointing
    at `sys_env_snapshot` and per-step alternatives.
  * `environment/README.md` — explains the global vs per-step split
    and the Dockerfile / conda / R / Julia hooks.

### Improved — `guidance/analysis_plan.yaml` doctrine

Two protocol steps were rewritten to match the new tool behaviors and
to make per-step file hygiene less optional:

* `snapshot_step_environment` — used to say "SKIP in the common case";
  now says "call every step that ran code". Variants spell out
  `step_id=` vs `scope="project"`. Reproducibility is treated as the
  default deal, not an opt-in.
* `finalize_step` — the description now lists everything `finalize_path`
  does, including the new project-scope log refresh + warning surface,
  so the AI knows the call is the canonical end-of-step ritual rather
  than just "rewrite some READMEs".

### Improved — visualization defaults (publication-grade)

Quick hits in `tools/actions/viz/figures.py`:
* **Chart-kind-aware gridlines.** Scatter / forest / dot_whisker /
  raincloud / slope / alluvial / consort_flow / funnel / calibration
  now render with NO gridlines (they competed with the marks). Bar /
  line / hist / box / violin / heatmap keep a faint horizontal grid
  to help the eye land on values.
* **Lighter sample-size annotation.** The boxed `n = ...` corner
  label became a plain light-grey text — same information, less
  visual weight.
* **Title padding.** `ax.set_title(..., pad=8)` so titles no longer
  collide with top spines or top-most tick labels.

### Fixed — six follow-on bugs surfaced by the e2e analysis

1. **`intake_autofill` misclassified the penguin dataset as
   "economics".** No `biology` / `ecology` domain existed in
   `DOMAIN_HINTS`. Added a `biology_ecology` bucket with the columns
   and keywords actual ecology / morphometric datasets carry
   (`species`, `sex`, `island`, `bill_*`, `body_mass_g`,
   `Pygoscelis`, `dimorphism`, `allometric`, etc.). Also dropped
   `year` from the `economics` columns since it false-positives every
   longitudinal study.
2. **`intake_autofill` overwrote researcher-supplied `--domain` /
   `--question`.** Init-time wizard input was being clobbered by
   weaker auto-inferences. v1.3.0 respects existing
   `state.domain` / `state.research_question` unless they're
   placeholders.
3. **`_propose_hypotheses` regex missed markdown bullets-with-bold.**
   Advisor notes commonly use `- **H1** — text` or
   `- **H2**: text` but the regex required a bare `H1: text`. New
   regex handles list markers, bold/italic emphasis, and `:`/`-`/`—`
   separators.
4. **`finalize_path` headline extraction was eating `**` opening
   markers.** `lstrip("-* ")` consumed the bullet's leading `**`,
   leaving the trailing `**` orphaned and surviving emphasis-strip.
   Replaced with a precise list-marker strip so the regex finds both
   ends of the bold pair. Side-fix: continuation lines under the
   first bullet are now joined (the headline used to truncate
   mid-sentence).
5. **`finalize_path` Outputs section listed sidecars as figures.**
   The figure inventory walked every file under `outputs/figures/`
   including `.caption.md`, `.summary.md`, and `.svg` companions —
   producing READMEs with "16 figures" when the step had 4 real
   PNGs. New `_figure_table_inventory` filters by extension and
   dedups the SVG companion when a PNG sibling exists.
6. **`create_numbered_experiment(from_step=X)` deep-copied X's
   whole step** (scripts, outputs, environment, everything) via
   `shutil.copytree`. The intent of `from_step` is "wire data/input
   from X's data/output"; the deep copy bloated workspaces, polluted
   per-step provenance, and broke `tool_path_finalize`'s artefact
   inventory. v1.3.0 strips it to symlink-only.

Also surfaced + auto-fixed by the new finalize doctrine: the
README's `## Input data` section was previously left as the
`*(list inputs used)*` stub. v1.3.0's
`_input_inventory_for_readme` populates it from `data/input/`
symlinks + `pipeline.yaml`-referenced raw inputs.

### Added — regression tests (+11 = 5 initial + 6 e2e)

Initial pass:
* `tests/tools/test_iteration.py`
  * `test_finalize_appends_step_entry_to_analysis_md`
  * `test_finalize_mirrors_methods_section_into_methods_md`
  * `test_finalize_warns_on_stub_findings`
  * `test_env_snapshot_step_id_param`
  * `test_env_snapshot_project_scope`
* `tests/unit/test_core.py::test_scaffold_creates_complete_workspace`
  updated: asserts `environment/` IS scaffolded, `CONTRIBUTORS.md`
  is NOT.

E2e pass (one per bug above):
* `tests/tools/test_iteration.py`
  * `test_finalize_headline_strips_markdown_bold`
  * `test_finalize_input_data_section_backfilled`
  * `test_finalize_figure_inventory_filters_sidecars`
  * `test_from_step_does_not_copy_outputs`
  * `test_intake_biology_domain_recognised`
  * `test_intake_extracts_markdown_hypotheses`

### Bumped

* `research-os` package: 1.2.2 → 1.3.0
* `CITATION.cff` version + date
* Embeddings rebuilt against the updated protocol bodies.

### Deferred (logged for v1.4.0)

* **Router slim refactor.** `_router_index.yaml` still holds the
  centralized trigger + decomposition + hierarchy + shortcut
  metadata. Audit confirmed it's correctly used server-side
  (so it does NOT cost AI tokens directly), but it has grown large
  (~76 KB) and per-protocol metadata would be cleaner in each
  protocol's own YAML frontmatter, with a build-time aggregation
  step. Scoped for v1.4.0 to avoid churn during a patch cycle.

### Test + quality status

```
preflight  : 14 / 14 ✓
pytest     : 464 / 464 ✓  (was 453 in v1.2.2)
ruff       : clean ✓
```

---

## [1.2.2] — Session-pattern phrasing + output coverage + routing patches (2026-06-03)

A bug-fix audit. **No protocol or tool removals.** 453 tests pass
(was 447; +6 regression tests for the fixes below). Same 109
protocols + 145 MCP tools.

### Fixed — session-pattern phrasing (the headline bug)

Docs and templates described the session sequence as `1. sys_boot →
2. (await researcher's message) → 3. tool_route`, suggesting the AI
fires `sys_boot` *before* a message arrives. An AI client cannot
call any tool until a researcher message triggers its turn — the
ordering as written was logically impossible. Rewritten throughout
to say: every turn is triggered by a researcher message, and on the
first turn the AI fires `sys_boot` as its 1st MCP call and
`tool_route(prompt=their verbatim message)` as its 2nd, back-to-back.

Files corrected:
* `docs/AI_GUIDE.md`, `docs/RESEARCHER_GUIDE.md`, `docs/PROTOCOLS.md`
* `templates/AGENTS.md`, `templates/CLAUDE.md`,
  `templates/.windsurfrules`, `templates/.continuerules`,
  `templates/.claude/rules/research-os.md`,
  `templates/.antigravity/rules/research-os.md`,
  `templates/.cursor/rules/research-os.mdc`
* `src/research_os/protocols/guidance/session_boot.yaml` — removed
  the contradictory `await_first_message` step; renamed the
  remaining flow so `boot` is explicitly "your first MCP call AFTER
  the researcher's message arrives" and `route_first_message` is the
  second call.
* `src/research_os/server.py` — `sys_help`'s `session_start` text +
  `routing` decision-tree + the `sys_help` tool description.

### Fixed — routing gaps surfaced by stress-testing

Stress-tested the router with 10 researcher personas (terse PI,
chatty grad, hesitant beginner, jargon-heavy senior, vague /
cross-disciplinary, kitchen-sink ambitious, pivot mid-session,
collaboration / handoff, recovery, edge / adversarial). Findings
fixed:

* **`baseline EDA` didn't route.** `_router_index.yaml` listed
  `"exploratory data analysis"` and `"do an eda"` as triggers for
  `guidance/analysis_plan` but not the natural-voice variants
  documented in `RESEARCHER_GUIDE.md` Section 4.2 as the canonical
  first-analysis prompt. Added `baseline eda`, `do a baseline`,
  `baseline analysis`, `eda on my`, `eda pass`, `first analysis`,
  `first experiment`.
* **"I just dropped a paper" had no shortcut.** Added a
  `context_intake` entry to `shortcut_intents` with the natural
  phrasings researchers actually use ("integrate this paper", "pi
  sent me a paper", "new paper in literature", …) → `tool_context_intake`.
* **Punctuation broke shortcut matching.** `_match_shortcut` did
  exact space-bounded substring matching, so "the workspace looks
  broken, fix it" didn't match the `broken` trigger because of the
  trailing comma. `route_request` now strips `,.;:!?` from the
  prompt before normalising — sub-string triggers match across
  punctuation now.
* **`workspace_repair` + `step_iterate` shortcuts gained natural
  variants** (`workspace looks broken`, `repair the workspace`,
  `recolor figure`, `tighten the cutoff`, `iterate on figure`, …).
* **Semantic path mis-handled complex multi-step prompts.** When the
  semantic router picked a narrow leaf protocol (e.g.
  `writing/writing_methods`) for a prompt the heuristic flagged
  complex, it would set `complexity="high"` without persisting an
  `active_plan` (because the leaf has no decomposition). Fixed in
  two ways:
  * If a stronger top-3 trigger-router candidate has its own
    decomposition, the semantic path defers to it — multi-protocol
    prompts now reach `guidance/analysis_plan` (or similar parent
    with a real plan) as before.
  * Otherwise the response keeps the semantic primary but downgrades
    `complexity` to `low` so the response shape is internally
    consistent (no plan promised when none was persisted).
* Bumped router index `version: 6 → 7` and rebuilt embeddings
  (`_embeddings.npz`, dim=384, 109 protocols + 145 tools).

### Improved — analysis-step doctrine (length + when to split + outputs)

`guidance/analysis_plan.yaml`:
* New **"STEPS CAN GROW"** note in `scope_step`: a step can be long
  when the researcher wants depth on one coherent goal — there is no
  artificial cap.
* New **"WHEN TO SUGGEST A NEW STEP"** block in `create_step_folder`
  with operational heuristics (covering ≥2 unrelated hypotheses,
  scope drift past the ≤2-sentence charter, estimator-family change,
  sub-population restriction added mid-stream, hard-to-caption with
  ONE focal figure) plus AUTONOMY-aware behaviour: surface to the
  researcher in supervised mode, call `tool_branch_recommendation`
  in autopilot. **Never force a new step** — long focused steps are
  preferable to step-fragmentation.
* **Output coverage** rewritten in `write_atomic_scripts`. Reports +
  tables + figures are now equal first-class outputs (was: reports
  + figures required, tables advisory). Each script defaults to
  emitting all three unless the step is genuinely non-numeric.

`visualization/figure_guidelines.yaml`:
* New top-level section `figure_family_when_step_has_a_model`. For
  any step that fits a statistical or ML model, generate the
  publication-quality FAMILY (diagnostic + summary + comparison) by
  default — not just the single focal chart. Domain-specific
  recommendations baked in (Cox → KM + Schoenfeld + cumulative
  hazard; Bayesian → trace + posterior + posterior predictive; ML
  classifier → ROC + PR + calibration + confusion; meta-analysis →
  forest + funnel + L'Abbé; etc.). Skip only when the researcher
  explicitly asks for "just the headline figure".
* Added pointers to the v1.2.1 deep-figure specialist protocols
  (`uncertainty_visualization`, `distribution_comparison`,
  `network_visualization`, `geospatial_visualization`,
  `animation_design`, `interactive_dashboard_design`,
  `showcase_visualization`) so the AI reaches for them automatically
  when the focal chart is non-trivial.

### Fixed — audit gap on numeric findings without a table

`src/research_os/tools/actions/audit/audit.py` →
`_step_completeness` now emits a non-blocking WARNING when a step
has a figure + numeric findings (≥2 numeric / statistical signals
in `## Findings`) but no CSV / TSV / parquet in `outputs/tables/`.
Reviewers and `tool_synthesize` expect a machine-readable companion
to every chart (coefficient table for a model, metric matrix for a
comparison). Threshold is soft — qualitative steps with no numeric
content are exempt automatically.

### Added — regression tests (+6)

* `tests/tools/test_router.py`
  * `test_route_punctuation_does_not_block_shortcut`
  * `test_route_baseline_eda_prompt_resolves`
  * `test_route_context_intake_shortcut`
  * `test_semantic_leaf_no_decomposition_downgrades_complexity`
* `tests/tools/test_iteration.py`
  * `test_step_completeness_warns_on_numeric_findings_without_table`
  * `test_step_completeness_quiet_when_table_exists`

### Bumped

* `research-os` package: 1.2.1 → 1.2.2
* `_router_index.yaml`: 6 → 7
* `CITATION.cff` version + date
* Embeddings rebuilt against the updated index + protocol bodies.

### Test + quality status

```
preflight  : 14 / 14 ✓
pytest     : 453 / 453 ✓  (was 447 in v1.2.1)
ruff       : clean ✓
```

---

## [1.2.1] — Showcase-tier visualization + tool / MCP integration + 100% routing (2026-06-02)

Patch release bundling everything in the never-tagged v1.2.0 work
plus a substantial follow-up tranche. **Supersedes v1.2.0** (never
published to PyPI). **No breaking changes** relative to v1.1.1.

**Stats:** **109 protocols** (was 88 at v1.1.1) · **145 MCP tools** ·
**438 tests passing** · **preflight 14/14** · **100% routing top-1**
on the 74-prompt canonical benchmark · **98.5% combined** on the
134-prompt fixture (canonical + stress paraphrases + viz prompts).

### Added — 4 novel protocols for top-tier work

* **`visualization/interactive_dashboard_design`** — next tier beyond
  the offline-HTML `synthesis_dashboard`. Audience / deployment /
  device sizing → stack picker (Observable Framework, Streamlit,
  Shiny, Dash, Panel, Quarto+shinylive, React+D3/Vega-Lite,
  kepler.gl, deck.gl) → interactive vocabulary (filter, brush-and-
  link, drill-down, parameterised view, temporal scrub) → versioned
  data layer → polish pass → reproducible deploy + cite-able URL.
  Quality bar: Tableau-tier is the floor, not the ceiling.

* **`visualization/showcase_visualization`** — for HCI / VIS / data-
  art / journal-cover / journalism-grade work where the visual IS
  the contribution. Layered read (3-second / 30-second / 3-minute
  test), chart-form picker with precedent citations, top-tier
  stack defaults (D3, Three.js + react-three-fiber, Observable +
  Plot, Vega-Lite, Pixi.js, Lottie / Rive), typography + palette
  pass, external design review, archival packaging at 3 sizes.
  Quality bar: Distill.pub article, NYT graphics, Pudding feature.

* **`methodology/external_tool_setup`** — guides researchers through
  installing top-tier external stacks (Node + npm for Observable /
  D3, Quarto, Docker, R + tidyverse, Julia, system libraries for
  geospatial, ffmpeg, LaTeX, hosted-service CLIs). Per-OS install
  commands paired with verification commands. Auto-install is OFF
  by default; the protocol proposes a setup script the researcher
  reviews + runs.

* **`methodology/mcp_ecosystem_integration`** — compose other MCP
  servers (Postgres, BigQuery, Slack, GitHub, Notion, Figma, Linear,
  Brave Search, Tavily, filesystem) alongside Research OS in the
  same IDE session. Vetting (provenance / license / auth model /
  data egress / maintenance), tool-name collision check, install +
  IDE config wiring, smoke test, README documentation. Research OS
  never installs other servers — produces the plan the researcher
  executes.

### Added — 5 new visualization protocols (originally v1.2.0)

* **`visualization/network_visualization`** — DAGs, citation
  networks, knowledge graphs. Layout algorithm picker, visual
  encoding budget, hairball detector, reproducible coords. Now
  routes upward to interactive_dashboard_design /
  showcase_visualization for next-tier output.
* **`visualization/geospatial_visualization`** — choropleth, points,
  raster, flow. Equal-area projection enforcement, classification
  break pre-specification, top-tier interactive stack (pydeck /
  deck.gl / kepler.gl / Mapbox GL) listed alongside the static
  baseline.
* **`visualization/animation_design`** — time-series / model
  behaviour / talks. Static-fallback mandatory; small-multiples
  vs animation justification; top-tier web stack (D3 transitions,
  Three.js, Lottie, Vega-Lite signals) for showcase animations.
* **`visualization/uncertainty_visualization`** — intervals, fans,
  ensembles, posteriors, calibration. Now references Vega-Lite,
  Observable Plot, bokeh / holoviews for interactive uncertainty
  exploration alongside matplotlib + arviz.
* **`visualization/distribution_comparison`** — raincloud, halfeye,
  ridgeline, beeswarm — beyond bar + error bar. Interactive
  options (Vega-Lite, Observable Plot, bokeh with linked
  brushing) added.

### Added — 12 high-impact methodology + synthesis protocols (originally v1.2.0)

Pre-data-collection qualitative + survey:
* **`methodology/interview_guide_design`** — paradigm selection,
  topic mapping, sensitive-topic ordering, pilot revision triggers,
  IRB alignment.
* **`methodology/coding_scheme_development`** — inductive / deductive
  / hybrid, per-code definition + inclusion / exclusion / canonical
  example, calibration rounds, freeze + amendment workflow.
* **`methodology/inter_rater_reliability`** — statistic choice
  (Cohen's κ / Fleiss' κ / Krippendorff's α / ICC / weighted κ),
  pre-specified threshold + field justification, remediation.
* **`methodology/survey_design`** — instrument review, construct
  definition, cognitive interviewing, pilot for psychometric
  staging, translation.

Statistical reasoning gaps:
* **`methodology/multiple_comparisons`** — family enumeration, FWER
  vs FDR, correction method with dependence-structure rationale.
* **`methodology/bootstrapping_design`** — resampling-scheme picker,
  interval-method picker (percentile / basic / studentised / BCa /
  ABC), B with MC-error sizing.
* **`methodology/uncertainty_quantification`** — calibrated
  predictive uncertainty (conformal / temperature / quantile /
  deep ensemble / MC dropout / Bayesian NN); reliability +
  sharpness + proper scoring rules.

Applied ML + safety + grants:
* **`methodology/fairness_audit`** — group / intersectional fairness
  audit; decision-context characterisation, criterion choice with
  impossibility trade-offs, mitigation, model card, monitoring.
* **`methodology/data_management_plan`** — NIH DMSP / NSF / Wellcome
  / ERC compliance with FAIR alignment.

Pre-submission + venue:
* **`synthesis/journal_selection`** — comparison across scope /
  evidence / format / timeline / cost / open-science fit; legitimacy
  vetting (predatory checks).
* **`synthesis/manuscript_outline`** — outline + storyboard before
  drafting; figures-first narrative; load-bearing-claims audit.
* **`synthesis/defense_prep`** — dissertation defense / job talk Q&A
  prep; weak-claim audit; question bank across framing / method /
  evidence / limitations / reproducibility / big-picture.

### Headline: semantic protocol + tool routing (originally v1.2.0)

`tool_route` is now a **hybrid semantic + trigger router**, hitting
**100% top-1 accuracy** on the 74-prompt canonical benchmark and
**98.5%** across 134 prompts (canonical + paraphrase stress + viz).

1. **Local embedding search** — BAAI/bge-small-en-v1.5 via
   `fastembed` (ONNX, no network, no LLM API keys, optional
   `[semantic]` extra ~150 MiB). Each protocol embedded once at
   build time; ships in `protocols/_embeddings.npz` (347 KiB).
   At request time we embed only the prompt and cosine-rank against
   the in-memory matrix.
2. **Length-weighted trigger boost with force-include** — exact-
   phrase matches on a protocol's triggers add a per-protocol
   boost sized by the LONGEST matched trigger. Triggered protocols
   are force-included in the candidate pool even when their
   pre-boost cosine falls outside the semantic top-N (fixed a
   silent bug where the most deterministic phrases could be
   missed).
3. **Parent-intent tiebreak** — when top-1 and top-2 share their
   parent `intent_class`, picking either is acceptable so top-1
   wins instead of triggering `ask_user`. Ambiguity is reserved
   for cross-intent cases.
4. **Conditional narrow-spread + capped triggers in embedding doc** —
   narrow-spread suppression is OFF when top-1 already scores high
   (we found a real topic, just adjacent topics share vocabulary).
   Build-time doc composition caps triggers per protocol so
   richly-triggered protocols don't dominate.
5. **Trigger-router fallback** — if `fastembed` isn't installed OR
   semantic confidence is low / none, the original hierarchical
   trigger-substring router serves the request. Nothing breaks
   for users without the `[semantic]` extra.

The AI gets ranked candidates with `method` (`"semantic" | "trigger"`)
and `confidence` (`"high" | "medium" | "low" | "none"`) every turn.

#### New MCP tools

* **`tool_semantic_route(prompt, top_k)`** — direct semantic search
  over protocols. Returns ranked candidates with cosine scores +
  the confidence verdict. Inspect alternatives without taking
  `tool_route`'s primary pick.
* **`sys_semantic_tool_search(query, top_k)`** — semantic search
  over the 145 tool definitions. Find tools by what they DO
  ("compute kappa for inter-rater agreement on transcript codes" →
  returns the matching tool list) when `sys_active_tools` is too
  narrow.

#### Token-usage win

Per turn, the semantic router saves an estimated **~20–30% of routing-
related tokens** vs the trigger-only path — driven by fewer wrong-
protocol loads (~250–290 tok saved per turn) and fewer ambiguity
roundtrips (~400–600 tok per saved clarify-and-re-route). The
`tool_route` reply itself is ~120 tok bigger (adds ranked candidates
+ method + confidence) but is net-positive because the AI almost
never picks the wrong protocol and re-loads.

### Changed — AI is now formally away from the router index

The router index `_router_index.yaml` (~1,700 lines) is now declared
**maintainer-only**:

* Header comment marks it private implementation detail; AI clients
  route through `tool_route` which reads it server-side.
* `AGENTS.md` adds an explicit "Never load `_router_index.yaml`
  directly" rule.
* `sys_protocol_list` description deprioritised: now says "prefer
  `tool_route` / `tool_semantic_route` — semantic routing scales as
  the catalog grows." The AI is steered away from raw catalog
  dumping toward semantic retrieval — important now that the
  catalog crosses 100 protocols.

### Changed — researcher_config simplification

* **Removed**: `model_tuning` block (five knobs that duplicated
  `model_profile`); `research_question` / `domain` / `hypotheses`
  top-level fields (AI-inferred; now in `inputs/intake.md` +
  `docs/research_overview.md` + `.os_state/state.json`);
  `researcher.field` / `researcher.expertise_level` / 
  `research_goal.reporting_standard` (all AI-inferred).
* **Reordered** to lead with what a researcher actually fills:
  `researcher` (name / institution / orcid / email) →
  `project_name` → `research_goal` → `interaction` →
  `model_profile` → `writing_preferences` → `runtime` →
  `api_keys`.
* `tool_intake_autofill` now reports `state_fields_updated`
  (was `config_fields_updated`).
* `regenerate_intake` sources domain / question / hypotheses from
  state (override > state > placeholder), not config.

### Improved — per-IDE + cross-model

* **Fixed BLOCKING Cursor rules bug**: `.cursor/rules/research-os.mdc`
  documented the obsolete `sys_config_get + sys_state_get +
  sys_protocol_next` bootstrap. Now uses canonical
  `sys_boot + tool_route + tool_plan_turn`.
* Per-model-tier guidance in `model_profile` comments with named
  classes (Haiku 4.5, Sonnet 4.5/4.6, Opus 4.x, GPT-4o-mini /
  4o / 5, Gemini Flash / Pro / 3, Llama 3.3 / 4) mapped to small
  / medium / large profiles.
* Wizard model-tier prompt — `research-os init` asks which AI model
  class is in use and writes `model_profile` accordingly.

### Improved — doctrine sweep (partial)

* `methodology/cox_ph_diagnostics` (`1.1.0 → 1.2.0`) — removed
  `editorial_voice.mode: prescription`, hardcoded `p<0.05`,
  library-specific function calls, canned 4-strategy menu.
* `methodology/bayesian_analysis` (`1.1.0 → 1.2.0`) — replaced
  algorithm-default and hardcoded MCMC thresholds with field-
  convention pointers + Vehtari et al. (2021) citation.

### Internal

* New `src/research_os/tools/actions/semantic.py` (~280 lines) —
  runtime semantic router with force-include trigger boost +
  parent-intent tiebreak + conditional narrow-spread + length-
  weighted trigger boost.
* New `scripts/build_embeddings.py` — deterministic source-hash;
  `--check` mode for stale detection.
* New preflight gate: `check_embeddings_fresh`.
* `numpy >= 1.23` is core; `fastembed >= 0.4` is the `[semantic]`
  extra.
* Router index version 3 → 6 (12 new sub-intents, 21 new
  protocol entries, header rewritten as maintainer-only).
* 109 protocols + 145 tools fully indexed in semantic embeddings.

### Migration

None required.

* **Without `[semantic]`** — `tool_route` uses the hierarchical
  trigger router exactly as before. The new tools return
  `status: "unavailable"` with an install hint.
* **With `[semantic]`** — `tool_route` automatically picks the
  semantic path on confident prompts and falls back to triggers
  otherwise. AI clients see a superset of the previous response
  shape (adds `method` + `confidence` + ranked candidates).
* Existing `researcher_config.yaml` files keep working — the
  removed fields are silently ignored.

### Stats

* **88 → 109 protocols** (+21 net new)
* **143 → 145 tools** (+2 semantic; nothing removed)
* **Preflight: 13 → 14 gates** (+ embedding freshness)
* **Tests: ~418 → 438 passing**
* **Router index version: 3 → 6**
* **Embedding bundle: 347 KiB** (BGE-small-en-v1.5; 384-dim
  float32; pre-built for 109 protocols + 145 tools)
* **Routing accuracy: 100% top-1 / 100% top-3** on the 74-prompt
  canonical benchmark; **98.5% combined** on the 134-prompt
  paraphrase + jargon + viz fixture.

---

## [1.2.0] — Never tagged

Its work landed in [1.2.1] above (consolidated and extended).

## [1.1.1] — Repo + docs polish (2026-06-02)

A maintenance release focused on **GitHub repo infrastructure** and a
**user-first README rewrite**. No protocol or tool changes; same 88
protocols, same 143 MCP tools, same 418-test pass.

### Added — repo infrastructure

* **`SECURITY.md`** — vulnerability reporting policy, supported-version
  table, scope clarification (in-scope vs out-of-scope).
* **`CODE_OF_CONDUCT.md`** — Contributor Covenant v2.1, with private
  reporting address + scaled-response policy.
* **`.github/PULL_REQUEST_TEMPLATE.md`** — type checklist, protocol /
  tool sub-checklists, test plan, breaking-change section.
* **`.github/dependabot.yml`** — weekly bumps for GitHub Actions + Python
  deps, grouped minor/patch updates, opinionated about `mcp` majors.
* **`.github/workflows/codeql.yml`** — CodeQL static security analysis on
  push, PR, and weekly schedule.
* **`.github/workflows/release.yml`** — auto-creates a GitHub Release on
  every `v*` tag with the matching CHANGELOG section as the body. Runs
  in parallel with `publish.yml` (PyPI).
* **`docs/RELEASING.md`** — maintainer release runbook (versioning,
  branch model, patch / minor / major / hotfix flows, pre- and
  post-release checklists, yank procedure).

### Improved — docs

* **README rewrite — user-first.** Reframed around what the project IS,
  what it DOES, what you SEE, and HOW to use it — with navigation links
  to the deep docs instead of inlining everything. Tool / protocol
  counts and architecture details are now one click away in
  `RESEARCHER_GUIDE.md` and `PROTOCOLS.md`. New top-of-README quick-link
  bar (Quick start · Use cases · Full guide · FAQ).
* **`CONTRIBUTING.md`** — adds the `main` / `dev` / `feat-*` / `fix-*` /
  `hotfix-*` branch model + PR flow, points maintainers at the new
  `docs/RELEASING.md`. Counts synced (143 tools, 88 protocols, 418 tests).
* **`README.md` badge bar** — PyPI version + Python versions + license +
  tests-status badges via shields.io (auto-updating, no more stale
  hardcoded version badge).

### Improved — CI

* **`test.yml` runs on `dev` branch too.** Previously only `main` push +
  PR to `main` triggered CI; now `dev` does too, so PRs into `dev` get
  the same green-or-red signal before they reach `main`.

### Bumped

* `research-os` package: 1.1.0 → 1.1.1
* `CITATION.cff` version

### Test + quality status

* 418 tests pass (unchanged surface).
* Preflight 13/13.
* Ruff clean.
* 88 protocols, 143 MCP tools (no surface changes).

---

## [1.1.0] — Guidance refinement (2026-06-02)

A non-breaking refinement focused on **how the AI navigates Research-OS
when the researcher's intent isn't a clean match** — open-ended asks,
cross-disciplinary projects, cold starts after a long handoff, ambiguity
at any router level. No tool surface changes; the MCP server still ships
the same 143 tools.

418 tests green (up from 417); preflight 13/13; one new protocol
brings the total to 88.

### Added

* **`guidance/scope_clarification` — 88th protocol.** Converts vague,
  open-ended, or cross-disciplinary asks into a workable scope BEFORE
  the AI picks a downstream protocol. Classifies ambiguity into five
  buckets (unclear intent / unformed intent / cross-disciplinary /
  wrong entrypoint / too broad), asks ONE narrowing question, then
  hands control back to `tool_route` with the narrowed prompt. Reaches
  `methodology/methodological_consultation` for "teach me" asks,
  `methodology/exploratory_data_analysis` for "find a hypothesis" asks,
  and `methodology/deep_domain_research` once per subfield for genuinely
  multi-field projects.
  ([`scope_clarification.yaml`](src/research_os/protocols/guidance/scope_clarification.yaml))

* **`discover/clarify` sub-intent.** Indexed in the router hierarchy so
  triggers like "where should I start", "i have data and ideas",
  "narrow this down for me", "this spans two fields" resolve cleanly.

* **`sys_help` topics — eight new categories.** Topics that aren't
  protocol categories but the AI needs on demand:
  - `routing` — the L1 → L2 → L3 decision tree + ambiguity rules
  - `iteration` — bug-fix versioning vs. deliberate `tool_step_iterate`
  - `overrides` — when / how to bypass a quality gate safely
  - `recovery` — what to do when stuck (broken workspace, lost project,
    dead-end mid-step, ctx exhaustion)
  - `fields` — how Research-OS stays field-agnostic; subfield pipelines
  - `depth` — depth gradient (napkin → publication) + expertise levels
  - `literature` — literature-search protocols + search-tool catalogue
  - `writing` — per-section writing protocols + attached audits
  ([`server.py`](src/research_os/server.py))

* **Router fallback now teaches.** When no trigger matches
  (`resolved_level=0`), the fallback returns the L1 menu WITH per-class
  trigger hints (`"start session", "pick up where we left off"` for the
  session class; `"draft the paper", "make a poster"` for synthesize;
  etc.) and tells the AI explicitly to prefer `sys_help(topic='categories')`
  or `sys_protocol_next` over guessing. Cuts the AI's clarification round
  from two questions to one.
  ([`router.py`](src/research_os/tools/actions/router.py))

* **Stronger routing advice.** `_route_advice_hier` now spells out:
  - For complex/L3 matches → tool_plan_turn + chat_split_recommended.
  - For shortcut-only → "summarise + wait for next ask" closure.
  - For primary protocols → call `sys_active_tools(protocol_name)` to
    scope the working tool set.
  - For ambiguous matches → "ask verbatim; do NOT load a YAML at
    format='full' to disambiguate".

### Improved

* **`protocol_completion` injected step is now actionable.** Tells the AI
  to log `status='failed'` (not 'completed') when a quality gate blocks,
  to confirm the override-log captured any bypass rationale this turn,
  to skip the trailing summary on shortcut-tool calls (the result IS the
  answer), and to prefer `tool_route` on the researcher's next message
  over the pipeline pointer when they redirect.
  ([`protocol.py`](src/research_os/tools/actions/protocol.py))

* **`sys_help` default + anti-patterns.** Added "when_uncertain"
  guidance to the lean default; expanded `anti_patterns` from 5 to 12
  to cover the gate-override silent-bypass case, the stale `_v<n>` reuse
  case, the redundant constructive-disagreement push-back case, and the
  re-route-after-the-researcher-already-picked case. `topic="docs"`
  now lists every doc with a one-line hook.
  ([`server.py`](src/research_os/server.py))

* **`session_boot` documents the no-match fallback.** When `tool_route`
  returns `resolved_level=0` AND the researcher's ask is open-ended /
  cross-disciplinary, the protocol now points at
  `guidance/scope_clarification` explicitly instead of leaving the AI to
  improvise.
  ([`session_boot.yaml`](src/research_os/protocols/guidance/session_boot.yaml))

* **`iterative_planning` enforces grounding + honours
  `ambiguity_posture`.** The option-presentation step now spells out
  that rationales must be SOURCED from grounded evidence (literature /
  audit warnings / decision log) — "AI intuition" rationales collapse
  under `constructive_disagreement`. Adds an explicit `AMBIGUITY POSTURE
  GATE` so `take_best_default` users get the runner-up surfaced too.
  ([`iterative_planning.yaml`](src/research_os/protocols/guidance/iterative_planning.yaml))

* **AGENTS.md template gains 4 quick-lookup rows.** Vague /
  cross-disciplinary asks → `scope_clarification`; tool shortlist →
  `sys_active_tools`; cold start → `sys_help(topic='routing')`;
  override how-to → `sys_help(topic='overrides')`. The Lost? hint now
  enumerates every `sys_help` topic instead of just listing categories.
  ([`AGENTS.md`](templates/AGENTS.md))

* **`AI_GUIDE.md` documents new ambiguity path.** New section "When the
  researcher's intent is unclear or cross-disciplinary" enumerates the
  five clarification buckets and explains the
  `tool_route → scope_clarification → tool_route` re-entry pattern.

### Fixed

* **`methodology/tool_discovery` next_protocol pointed at the
  pre-1.0 `methodology/research_methods`**, which was renamed to
  `methodology/methodology_selection` during 1.0.0 hardening. The
  pipeline pointer was silently dangling — preflight didn't catch it
  because the freshness check only validates `_router_index.yaml`
  references, not protocol-internal `next_protocol` fields.
  ([`tool_discovery.yaml`](src/research_os/protocols/methodology/tool_discovery.yaml))

* **`sys_active_tools` description had a stale tool count.** Said
  "all 94 tools per turn"; actually 143.
  ([`server.py`](src/research_os/server.py))

* **Tool count drift across docs.** README.md was right at 143; multiple
  reference docs lagged at 140. Synced
  `docs/README.md`, `docs/START.md`, `docs/TOOLS.md`,
  `docs/RESEARCHER_GUIDE.md` (2 places) to 143.

* **Protocol count drift across docs.** Updated 87 → 88 in
  `README.md`, `docs/README.md`, `docs/RESEARCHER_GUIDE.md`,
  `docs/AI_GUIDE.md`, `docs/FAQ.md`, `docs/PROTOCOLS.md` (table + total).

* **Version not auto-derived in wizard / logo.** Both hardcoded "1.0.0";
  now read from `research_os.__version__`. One source of truth across
  the package.

### Bumped

* `research-os` package: 1.0.0 → 1.1.0
  ([`pyproject.toml`](pyproject.toml), [`__init__.py`](src/research_os/__init__.py))
* All 88 protocol YAMLs: version 1.0.0 → 1.1.0 (no schema changes —
  scaffold doctrine + step structure preserved).
* Router index version: 2 → 3.
* `CITATION.cff` version + date.

### Test + quality status

* **418 tests pass** (up from 417 — the new
  `guidance/scope_clarification` is auto-covered by
  `tests/integration/test_all_protocols_load.py` + protocol-loader
  unit tests).
* Preflight 13/13.
* 88 protocols indexed; all router refs + tool refs resolve.
* All protocols at version 1.1.0.
* 143 MCP tools (unchanged surface).

---

## [1.0.0] — Hardening (post-review)

15-finding code-review pass fixed in-place against v1.0.0; no version
bump (no API changes). 417 tests green (up from 395), preflight 13/13.

* **Mega-script blocker no longer fires on stray figures.** The
  blocker now counts only artefacts that bear the step's number
  prefix toward `categories_hit`. A legacy step that produced one
  CSV no longer blocks `tool_synthesize` because someone dropped an
  unrelated `panel.png` into `outputs/figures/`.
  ([`audit.py`](src/research_os/tools/actions/audit/audit.py))
* **Version-coherence audit no longer cries wolf or sleeps through drift.**
  The stem-prefix derivation used a non-anchored `startswith` that
  both (a) conflated unrelated sibling scripts like `01_fit_v2.py` /
  `01_fit_extended_v3.py` (false drift) AND (b) missed
  unsuffixed-to-versioned bumps like `02_clean.py` → `02_clean_v2.py`
  (silent miss). Now exact-stem matching catches the real case in
  both directions.
  ([`iteration.py`](src/research_os/tools/actions/state/iteration.py))
* **`tool_step_iterate` is safe under concurrent IDE sessions.**
  `fcntl.flock` serialises the read-ledger → pick `n` → create
  `.versions/v<n>/` → write-ledger critical section. The archive
  dir is verified unused before mkdir so a stale `vN` can't be
  clobbered. `_bump_script_suffix` scans the folder for the
  highest existing `_v<n>` and returns `_v<n+1>`, so the rename
  advice never overwrites an existing file. Atomic ledger writes
  via temp + replace.
  ([`iteration.py`](src/research_os/tools/actions/state/iteration.py))
* **`tool_audit_version_coherence` surfaces typos and warnings.**
  An unknown `step_id` now raises `FileNotFoundError` instead of
  returning empty success. A ledger entry with empty `snapshot_dir`
  is flagged as malformed instead of silently resolving to the step
  dir. Top-level `status` escalates to `warning` when any per-step
  warning fires (stale captions etc.), not only on drift.
* **Override audit trail is honest.** `log_override` now fires only
  when the bypassed gate would have blocked — phantom entries from
  defensive `override=true` calls (or section-only synthesis where
  the full gate never ran) no longer pollute
  `workspace/logs/override_log.md`. The plan-persisted
  `override_completeness_gate` flag inside `active_plan.json` gets
  its own log entry on the deliverable step.
  ([`server.py`](src/research_os/server.py),
  [`router.py`](src/research_os/tools/actions/router.py))
* **Dashboard override actually suppresses the warning panel.**
  `override_completeness_gate=true` on `tool_dashboard_create` now
  plumbs through to `render_dashboard` via a `suppress_audit_panel`
  flag so the schema's promise (drop the warning section in the
  rendered HTML) is honoured.
  ([`dashboard.py`](src/research_os/tools/actions/synthesis/dashboard.py))
* **Cold init keeps the short intake pointer.** `scaffold_minimal_workspace`
  no longer unconditionally overwrites the new short
  `inputs/intake.md` with the legacy long-form table — it
  regenerates the full intake only when the researcher dropped
  files or passed config overrides.
  ([`project_ops.py`](src/research_os/project_ops.py))
* **`sys_file_list` on lazy dirs returns empty, not error.** Cold
  protocols that probe `inputs/raw_data`, `inputs/literature`,
  `inputs/context` no longer break on a fresh project — the handler
  returns `{files: [], empty: true, lazy_dir: true}` with a hint.
  ([`server.py`](src/research_os/server.py))
* **`interaction.quality_gate_policy` and `interaction.ambiguity_posture`
  are now live config.** `tool_synthesize` and `tool_dashboard_create`
  read the policy: `warn_only` turns blockers into warnings;
  `enforce` rejects overrides without a rationale; `allow_override`
  is the existing behaviour. New `get_interaction_policy` helper
  exposed via `state` package.
  ([`state/config.py`](src/research_os/tools/actions/state/config.py))
* **`audit/pre_submission_checklist` reads the override log.** A new
  `override_audit_review` step surfaces every entry in
  `workspace/logs/override_log.md` and folds unresolved bypasses
  into the GREEN / YELLOW / RED verdict. The audit trail is no
  longer write-only.
* **`ensure_lazy_dir` is real now.** Synthesis writers route through
  it instead of ad-hoc `mkdir`; the helper rejects paths not in
  `LAZY_DIRS` so the lazy surface can't silently grow.
  ([`project_ops.py`](src/research_os/project_ops.py))
* **sys.* output token-bloat trim.** `sys_help` default returns a
  lean orientation block + topic index (deep dives behind
  `topic=categories|anti_patterns|docs`); `sys_active_project`
  emits the orientation advice only when the project isn't
  scaffolded; `sys_state_get` omits empty `paths_summary` /
  `active_hypotheses` / `resumable_from`; `sys_protocol_get`
  format=full drops the redundant "prefer summary" reminder.
* **README rewrite.** Reframed as user/functionality-first — what it
  does, what you say, what you get, the layout you touch. Setup +
  per-IDE wiring + tool catalogues offloaded to `docs/`.

---

## [1.0.0] — Initial public release

The first public release of Research OS — an MCP-native operating system
for reproducible, grounded, citation-verified research. Built for any
researcher who can talk in plain English to an AI IDE.

### Architecture

* **MCP server is GLOBAL.** Install once with `pip install research-os`;
  the SAME `research-os start` binary serves every project. Each IDE
  request resolves the active project per-call via:
    1. `RESEARCH_OS_WORKSPACE` env var (set by the IDE MCP config to
       `${workspaceFolder}` so each IDE project gets its own context),
    2. the current working directory walked up to `.os_state/`,
    3. the current working directory as a fallback.
  No more per-workspace server pinning. `research-os init` is the only
  per-project command.
* **140 MCP tools** across three namespaces:
  - `sys_*` — system, workspace, state, files, paths, checkpoints
  - `tool_*` — research work: search, exec, audit, synthesis, intake, plan
  - `mem_*` — append-only memory: methods, citations, decisions, hypotheses
* **87 YAML protocols** the AI loads contextually, organised in nine
  categories: guidance, discover, domain, methodology, literature,
  writing, visualization, synthesis, audit, reproducibility.
* **Hierarchical L1 → L2 → L3 router** (`tool_route`) — picks the right
  protocol from a plain-English prompt in ~250 tokens. Persists a plan
  for complex / multi-step prompts. Returns an `ask_user` sentence
  instead of guessing when ambiguous.
* **AI orientation tools** — `sys_help` returns the AI's operating
  manual (routing pattern, namespaces, protocol categories,
  anti-patterns); `sys_active_project` reports which project the
  global server resolved for THIS request.

### Protocol surface (87 protocols)

**Guidance + session + flow control (15)**
* `session_boot`, `session_resume`, `chat_handoff`, `autopilot`,
  `collaboration_handoff`, `casual_exploration`, `quick_paper_review`,
  `code_review`, `peer_review_response`, `project_startup`,
  `analysis_plan`, `iterative_planning`, `dead_end_routing`,
  `hypothesis_tracking`, `glossary_update`
* `mid_pipeline_entry` — enter Research OS with work already done outside
* `constructive_disagreement` — structured AI pushback when grounded
  evidence disagrees with the researcher's direction

**Domain + methodology (24)**
* `domain_analysis`, `research_design`
* `methodology_selection`, `deep_domain_research`, `preregistration`,
  `tool_discovery`
* Per-method: `causal_inference_deep`, `machine_learning`,
  `clinical_trials`, `meta_analysis`, `survey_psychometrics`,
  `qualitative_research`, `simulation_studies`, `replication_study`,
  `ablation_study`, `pilot_study`, `mixed_methods`, `bayesian_analysis`,
  `timeseries_analysis`
* New design protocols: `exploratory_data_analysis` (real EDA +
  hypothesis generation), `method_comparison` (N-method head-to-head),
  `data_quality_audit`, `power_analysis`, `evaluation_design`
  (split / CV / metrics / paired test), `hyperparameter_search_design`
  (sweep design), `data_ethics_review` (IRB / privacy / consent /
  fairness / dual-use), `reproduction_attempt` (reproduce a published
  paper), `methodological_consultation` (teach / explain / compare
  methods without project commit)

**Literature (4)**
* `literature_search` — multi-database search, dedup, PRISMA
  accounting, forward-citation walk, predatory-venue flagging
* `systematic_review` — full PRISMA workflow
* `evidence_synthesis` — GRADE-style grading + contradiction detection
* `comparative_paper_review` — compare-and-contrast 2-N papers

**Writing (9)**
* `writing_core` — universal rules (voice, claim grounding, banned
  phrases, vague-quantifier audit, anti-bullshit detection, numbered
  claim grounding pattern)
* `writing_methods`, `writing_results`, `writing_discussion`,
  `writing_limitations`, `writing_conclusions`, `writing_citations`,
  `writing_readme`, `writing_analysis_log`, `writing_data_availability`
  (end matter: data / code availability, CRediT, funding, COI, ack)

**Visualization (6)**
* `figure_guidelines` — style + chart-chooser + per-step focal-figure
  rule, server-enforced
* `visualization_workflow` — build / polish figures without committing
  to the full analysis_plan loop
* `figure_critique` — reviewer-style critique of a single figure
* `multi_panel_composition` — compose Figure 2 = panels A / B / C / D
* `figure_narrative_arc` — order figures across paper / talk / poster
* `color_accessibility_audit` — color-blindness simulation (3 types) +
  WCAG contrast + grayscale-survivability + redundant-encoding audit

**Synthesis (14)**
* `synthesis_paper` — IMRAD paper, venue-tailored (journal / conference
  / preprint / dissertation / report)
* `synthesis_abstract` — structured / unstructured / preprint / poster /
  grant abstract
* `synthesis_poster` — billboard + classic LaTeX poster, audience
  profiles, QR code mandatory, single-headline test
* `synthesis_dashboard` — offline HTML dashboard, Playwright-tested,
  4 audience profiles, evidence traceability matrix
* `synthesis_grant` — grant narrative (R01 / NSF / Wellcome / ERC /
  DOE / industry)
* `synthesis_report` — internal / client / technical / policy report
* `synthesis_null_findings` — publishable companion for refuted /
  underpowered / abandoned findings (fights the file-drawer problem)
* `synthesis_slides` — talks (lab_meeting / conference_short /
  conference_long / defense / invited_seminar / teaching) with mandatory
  speaker notes + Q&A backup deck
* `synthesis_lay_summary` — non-expert summary (public / press / patient
  / funder / blog / social) with reading-grade cap + anchor comparisons
* `synthesis_progress_update` — short PI / advisor / lab / stand-up update
* `synthesis_handout` — single-page printable leave-behind + QR
* `synthesis_from_inputs` — synthesis when prior analyses ran OUTSIDE
  Research OS (shadow workspace step + provenance ceiling)
* `synthesis_cover_letter` — journal cover letter (fit + significance +
  reviewers + disclosures)
* `synthesis_title_workshop` — generate / iterate / pick a title
  (≥6 alternatives across archetypes, substring test, shortlist)

**Audit + reproducibility (3)**
* `audit_and_validation` — master quality audit (citations / power /
  assumptions / figures / code / per-step completeness)
* `pre_submission_checklist` — final ready-to-submit gate
  (GREEN / YELLOW / RED + punch list)
* `reproducibility` — env snapshot + seed verification + Dockerfile
  generation

### Quality guarantees

* **Real, verified citations** — every citation traces to Crossref /
  Semantic Scholar / PubMed / arXiv. Synthesis refuses hallucinations.
* **Numbered claim grounding** — every number in synthesis traces to a
  workspace artefact (`tool_audit_claims`).
* **Per-step completeness gate** — synthesis BLOCKS until every active
  step has a focal figure + caption sidecars + non-stub conclusions.
* **Pre-registration drift** — `tool_preregister_freeze` content-hashes
  the SAP before data; `tool_preregister_diff` surfaces every
  deviation at synthesis time.
* **Code quality** — `tool_audit_code_quality` blocks bare-except,
  import-*, eval / exec, hardcoded absolute paths, functions > 150 lines.
* **Prose quality** — `tool_audit_prose` flags hedging clusters, vague
  quantifiers, passive voice, causal language on observational designs.
* **Color accessibility** — Okabe-Ito / viridis / PuOr defaults;
  `visualization/color_accessibility_audit` provides deeper checks.

### Reasoning + memory

* **Grounded reasoning** — ReAct + CoVe + PROV-O + Reflexion. Every
  decision binds to evidence (papers / context / datasets / web).
* **Sub-task pipelines** — `pipeline.yaml` declares atomic nodes
  (ingest → validate → clean → fit → diagnose → visualize → report).
  Content-hash cached; edits re-run only the affected chain.
* **Provenance sidecars** — every figure / table / model emits a
  `<name>.prov.json` recording script + input hashes + parameters +
  RNG seed + library versions + wall time.
* **Lessons across sessions** — `tool_lessons_record` /
  `tool_lessons_consult` so the next attempt doesn't repeat past
  mistakes.

### Scaffold doctrine

Codified in [`docs/PROTOCOL_DOCTRINE.md`](docs/PROTOCOL_DOCTRINE.md):
every protocol names the QUESTIONS the AI must answer + the GROUNDING
it must cite. Tools, thresholds, finite method menus, and canned step
sequences are PRESCRIPTION and out of scope. Protocols are scaffolds
for reasoning, not scripts to execute.

### Operations

* **HPC ready** — SLURM submit / status / fetch. Per-step Apptainer
  recipes + reproducer `entrypoint.sh`.
* **Per-step environment locking** — `tool_step_env_lock` pins
  `requirements.txt` + `python_version.txt` (+ optional `conda.yaml`
  + per-step `Dockerfile`) inside each step.
* **Self-tested dashboards** — auto-generated Playwright suite covers
  TOC scroll-spy, theme toggle, sortable tables, lightbox figures,
  print stylesheet, ARIA snapshot, axe-core WCAG, visual regression.
* **Background tasks** — `tool_task_run` (real `Popen`) for long jobs;
  `tool_task_status` polls without blocking the chat.
* **Session resume / handoff** — `tool_session_resume` reconstructs
  intent from logs after any pause; `sys_session_handoff` snapshots a
  checkpoint + writes a fresh-AI-readable handoff doc.

### Docs (10 docs, consolidated)

* [`docs/README.md`](docs/README.md) — table of contents + pick-your-path
* [`docs/START.md`](docs/START.md) — install + first project + cheatsheet (replaces QUICKSTART + FIRST_HOUR + CHEATSHEET)
* [`docs/RESEARCHER_GUIDE.md`](docs/RESEARCHER_GUIDE.md) — full workflow walkthrough (replaces GUIDE + WALKTHROUGH + the old RESEARCHER_GUIDE)
* [`docs/USE_CASES.md`](docs/USE_CASES.md) — role × goal × output map
* [`docs/SETUP.md`](docs/SETUP.md) — install + per-IDE MCP wiring (absorbs SETUP_PROMPT)
* [`docs/FAQ.md`](docs/FAQ.md) — common questions
* [`docs/AI_GUIDE.md`](docs/AI_GUIDE.md) — orientation for the AI driving Research OS
* [`docs/PROTOCOLS.md`](docs/PROTOCOLS.md) — protocol catalogue + triggers + quality bars
* [`docs/TOOLS.md`](docs/TOOLS.md) — every MCP tool with example calls
* [`docs/PROTOCOL_DOCTRINE.md`](docs/PROTOCOL_DOCTRINE.md) — the scaffold-not-script principle

### Robustness refinements (folded into 1.0.0)

* **No empty-folder pollution.** Scaffolding now creates only directories
  guaranteed to be populated. `synthesis/`, `environment/`, and
  `inputs/{raw_data,literature,context}/` are LAZY — they materialise at
  first write via `ensure_lazy_dir(root, rel)`. A fresh `research-os init`
  surface has zero orphan `.gitkeep`-only folders. `_prune_stale_gitkeeps`
  now also removes any empty lazy-dir leftovers from pre-1.0 projects.
* **No premade boilerplate.** `docs/research_overview.md` is no longer
  written at init — it is created lazily by `tool_intake_autofill` once
  the researcher has actual context to summarise. `inputs/intake.md` is
  reduced to a one-sentence pointer.
* **Mega-script blocker.** `tool_audit_step_completeness` now BLOCKS
  (not just warns) when a step's outputs span multiple categories
  (figures + tables + reports) without a `pipeline.yaml` declaring the
  sub-task DAG. Atomic scripts per sub-task are mandatory — the
  reproducibility guarantee depends on it.
* **Deliberate iteration versioning.** New `tool_step_iterate(step_id,
  rationale=…)` snapshots a coordinated unit (scripts + outputs +
  caption / summary / prov sidecars + conclusion) into
  `.versions/v<n>/` before the researcher edits anything. The live
  filenames stay stable so cross-step references in conclusions /
  dashboards don't rot. `tool_step_iterations_list` returns the ledger.
* **Version-coherence audit.** `tool_audit_version_coherence` walks
  every step and flags drift: an output whose `.prov.json` points at a
  script no longer on disk OR at `_v<k>` when `_v<k+1>` exists OR a
  caption sidecar older than its figure. Report at
  `workspace/logs/version_coherence.md`.
* **Override discoverability + audit trail.** The previously-undeclared
  `override_completeness_gate` parameter is now in the inputSchema for
  `tool_synthesize` and `tool_dashboard_create`; `override_gate` /
  `override_rationale` are documented on `tool_plan_advance`. Every
  bypass appends to `workspace/logs/override_log.md` (the
  pre-submission audit surfaces them).
* **User-side override policy.** `researcher_config.yaml` gains
  `interaction.quality_gate_policy` (`enforce` | `allow_override` |
  `warn_only`) and `interaction.ambiguity_posture`
  (`ask_when_uncertain` | `take_best_default`). Defaults are
  conservative; the researcher tightens or loosens to taste.
* **Per-IDE rule parity.** `.windsurfrules` and `.continuerules` now
  use the same `sys_boot` + `tool_route` boot pattern as
  `AGENTS.md` / `.claude/` / `.cursor/` / `.antigravity/` —
  no more legacy `sys_config_get + sys_state_get` cost.
* **AGENTS.md escape clause.** Hard rule 11 (multi-script DAG) is
  tightened. New rule 12 separates bug-fix versioning (bump `_v<n>`)
  from deliberate iteration (`tool_step_iterate` first). A new
  "When the researcher explicitly overrides a rule" section formalises
  the bypass protocol: explicit current-message authorisation,
  `override_rationale` mandatory, logged.

### Test + quality status

* 380+ tests pass; preflight 13 / 13 checks green
* 87 protocols indexed; all router refs + tool refs resolve
* All protocols at version 1.0.0
* 143 MCP tools (140 baseline + `tool_step_iterate` +
  `tool_step_iterations_list` + `tool_audit_version_coherence`)
