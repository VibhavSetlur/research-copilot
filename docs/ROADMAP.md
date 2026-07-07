# Research OS — Roadmap & Build Log (the daemon enforcement kernel)

> **The canonical design-history + handoff document for the daemon kernel
> work.** Any agent or maintainer picking up this work reads this FIRST, top
> to bottom, before touching code. It carries the architecture, the
> invariants, the phase plan, and a running progress log so quality does not
> degrade across sessions. Update the Progress Log at the bottom of every
> working session. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the
> standalone architecture overview.

---

## 0. Why this exists (the architectural problem)

Research OS today (3.x) is a **single, reactive, stdio MCP server**. It
is excellent at what it does, but the design has a structural ceiling:

- **MCP is reactive.** A server cannot do anything until a host client
  sends a request. Long-running research work (batch-fetching hundreds
  of papers, running a multi-hour simulation, a multi-step pipeline) has
  no home — there is no master loop that owns execution independently of
  whichever chat client happens to be connected.
- **It is bound to one transport.** stdio MCP means one client at a
  time, no shared state across clients, no way for a web UI and an IDE
  to observe the same project simultaneously.
- **Chat is the only surface.** Natural-language chat is a poor place to
  review a 200-row table, a citation graph, or a multi-page draft.
- **Execution is native.** Agent-written code runs on the host. That is
  a security and reproducibility liability.

The 5.0.0 model resolves this with a **persistent headless localhost daemon
acting as an enforcement + execution + notification kernel**: one backend
that owns the master state machine and exposes read-only + bearer-auth-gated
mutating HTTP endpoints to any client (Cursor, Claude Desktop, Hermes, the
CLI) at once. Research OS calls no LLM and has no chat gateway — it is a
passive tool provider; the client does all reasoning over the MCP tools.

```
              ┌────────────────────────────────────────┐
              │           FRONTEND CLIENTS              │
              │ (Cursor, Open WebUI, Claude, CLI, etc.) │
              └───────────────────┬────────────────────┘
                                  │
           ┌──────────────────────┴──────────────────────┐
           ▼                                             ▼
 [ OpenAI/Anthropic-compat API ]                      [ MCP ]
 (Completions & Agent Tool Hooks)          (Read-Only Sidecar Telemetry)
           │                                             │
           └──────────────────────┬──────────────────────┘
                                  ▼
              ┌────────────────────────────────────────┐
              │        RESEARCH OS CORE DAEMON          │
              │  (State Engine, Ledger, Sandbox, DAG)   │
              └───────────────────┬────────────────────┘
                                  ▼
              ┌────────────────────────────────────────┐
              │           PROJECT WORKSPACE             │
              │     (inputs, workspace, synthesis)      │
              └────────────────────────────────────────┘
```

The architecture diagram above is **intent, not spec**. We have free
rein to redesign for the best possible system. The diagram says
"SQLite / Docker"; the actual engine uses a JSON `ResearchLedger` and
native+cluster execution. We keep what works and add what's missing.

---

## 1. Hard invariants (never violate, every phase)

1. **Strangler-fig, not rewrite.** The daemon WRAPS the same engine
   functions the MCP handlers already call. We never re-implement
   routing, state, or protocol logic in a parallel codebase. One engine,
   many faces.
2. **The existing stdio MCP server keeps working until the very end.**
   Every phase ships additive and opt-in. `research-os start` (stdio)
   stays functional through the entire 3.x line. We only retire legacy
   paths at the deliberate 4.0.0 cut, and even then with migration notes.
3. **The release gate is sacred.** `python scripts/preflight.py` (33/33+)
   + `python -m pytest -q` (2200+ pass) + `ruff check src/ tests/
   scripts/` clean. No push / no tag / no version bump if any fails.
4. **Branch model unchanged.** feat/<slug> → dev (squash) → dev→main
   Release PR (squash) → tag from main triggers PyPI + GH release. See
   `docs/RELEASING.md` and CLAUDE.md.
5. **No new heavy hard dependency in core.** The daemon's web stack
   (HTTP server, etc.) goes in a new optional extra `[daemon]`, never in
   `dependencies`. Core must still boot with only the stdlib + current
   deps. The daemon imports its web libs lazily and degrades with a clear
   "install research-os[daemon]" message.
6. **Graceful degradation everywhere.** Vibhav's dev server has NO
   Docker. The sandbox MUST fall back to native execution (with a loud
   audit note) when no container runtime is present. The daemon must run
   without a sandbox, without a dashboard, without provider keys — each
   layer is independently optional.
7. **Tools never do the science.** The doctrine still holds (see
   `docs/PROTOCOL_DOCTRINE.md`): tools verify recorded work, gate, route,
   and manage state/provenance. The daemon orchestrates; it does not
   compute findings.
8. **RO never calls a model.** There is no LLM gateway, no chat-completions
   proxy, no provider forwarding inside RO — that was explicitly rejected
   and the dead `daemon/gateway.py` was removed in 5.0.0. The client already
   has an IDE / AI client; RO exposes tools + protocols + journaled state for
   *that* client to reason over. Research data-source keys keep their existing
   injection path (`server/entry.py:_inject_api_keys`).

---

## 2. The version stance — 5.0.0 shipped (historical note)

**5.0.0 is the shipped baseline** — "The World-Class Architecture Overhaul."
It was reached deliberately, not rushed: a build→judge→improve loop across
the P0–P8 phase plan (schema foundation → tool consolidation → config/state
simplification → memory overhaul → token engineering → daemon core → daemon
surface → ship). The package version stayed pre-release the whole way; the
5.0.0 tag waited until the entire architecture was coherent and green.

What shipped (the daemon as an enforcement + execution + notification
kernel, NOT an LLM gateway):

- **Build phases** stood up each layer of the daemon — skeleton, core loop +
  state bridge, event bus, CAS, sandbox, and the cross-cutting concerns they
  expose (bearer auth, multi-root, streaming, observability, persistence of
  long jobs). The chat gateway that appeared in early drafts was removed:
  RO calls no LLM.
- **Judge/improve phases** (roughly Phases 10–30): for each built layer,
  step back and critique it hard — security, ergonomics, performance,
  failure modes, API quality, test depth, docs — then redesign and
  re-implement the weak parts. Do NOT lock into the first design that
  works. Every judge phase should produce a written critique (in this
  doc's design-review log) and concrete improvement PRs.
- **Each phase still ships green on its own `feat/v4-<slug>` branch →
  dev.** The gate (preflight + pytest + ruff) is non-negotiable per
  phase. But the package **version stays pre-4.0.0** the whole way —
  intermediate phases land as MINOR/PATCH `3.x` releases (the daemon is
  opt-in, MCP untouched), and the **4.0.0 tag waits until the entire
  system is judged maximal**.
- A breaking change mid-stream that we are NOT ready to crown as 4.0.0
  gets the back-compat treatment (alias the old name, keep old schema
  accepting, default-off the new behaviour) and ships MINOR until the
  final 4.0.0 cut collects them.
- **4.0.0 is the deliberate final cut**: daemon is the proven primary
  surface, every layer has survived a judge pass, legacy paths retire
  with a `docs/MIGRATION.md` + CHANGELOG Migration section.

The standing "under 4.0.0 forever" mandate is superseded **for this work
only**.

---

## 3. Engine reuse seams (the strangler-fig anchors)

The daemon is thin glue over these existing functions. Do NOT duplicate
their logic.

| Capability | Existing engine entry point |
|---|---|
| Route a prompt → protocol + plan | `tools/actions/router.py:route_request(prompt, root, persist_plan=)` |
| Read the active plan | `tools/actions/router.py:_load_active_plan(root)` |
| Progress digest | `tools/actions/research/planning.py:progress_digest(root)` |
| Master state ledger (atomic, file-locked) | `state/state_ledger.py:ResearchLedger` |
| Dispatch a tool call by name | `server/dispatch.py:_handle_tool_call(name, args, root)` |
| Tool catalogue + schemas | `server/registry.py:TOOL_DEFINITIONS`, `_HANDLERS` |
| Protocol load | `tools/actions/protocol.py` (loader) / `sys_protocol_get` handler |
| Autopilot floor gates | `server/autopilot_gate.py:enforce_autopilot_gate` |
| Project root resolution | `server/entry.py:_resolve_project_root` |
| Research-data API key injection | `server/entry.py:_inject_api_keys` |

**The key insight:** `_handle_tool_call(name, arguments, root)` is a
pure, transport-agnostic function. The stdio MCP server is just one
caller of it. The daemon's HTTP endpoints become a second caller of the
exact same function. That is the whole strangler-fig in one sentence.

---

## 4. Phase plan

Each phase is a shippable release. Sub-tasks within a phase may be their
own PRs. "DoD" = Definition of Done (the gate for declaring the phase
complete).

### Phase 0 — Daemon skeleton (additive, no behaviour change)
- New package `src/research_os/daemon/` with `__init__.py`, a `Daemon`
  class stub that holds config + a reference to the resolved root, and a
  `research-os daemon` CLI subcommand group (`start`/`stop`/`status`)
  that currently just reports "not yet serving".
- New optional extra `[daemon]` in pyproject (web server lib TBD in
  Phase 2; Phase 0 adds the extra empty/with only what's needed).
- Lazy-import guard: importing `research_os.daemon` must not pull heavy
  web deps at module load.
- DoD: preflight+pytest+ruff green; `research-os daemon status` runs;
  zero change to any existing surface; new `tests/unit/test_daemon_*`.

### Phase 1 — Daemon core loop + state bridge (read path)
- A persistent process that holds the master loop and a read-only view
  over `ResearchLedger` + active plan + progress digest for one or more
  project roots.
- A localhost control socket / HTTP health endpoint (`/healthz`,
  `/v1/state`) — READ ONLY. No mutation yet.
- Background task queue abstraction (the "master loop owns execution"
  primitive) — enqueue a long-running job, run it off the request
  thread, expose status. Jobs call existing engine functions.
- DoD: daemon starts, serves read-only state for a real RO project,
  survives client disconnect; task queue runs a trivial job to
  completion and reports status.

### Phase 2 — ~~OpenAI-compatible gateway~~ (REMOVED in 5.0.0)
An early draft proposed an OpenAI-compatible `/v1/chat/completions` gateway
that would forward prompts to a user-configured provider and run a tool loop
inside the daemon. **This was explicitly rejected and the dead
`daemon/gateway.py` was deleted in 5.0.0.** RO never proxied a model in
normal use (the gateway was opt-in and off by default), and RO is a passive
tool provider — it calls no LLM. Point your IDE / AI client straight at the
MCP tools instead; multi-agent orchestration belongs at the client level.
The daemon still exposes a read-only `/v1/capabilities` front door
(`daemon/capabilities.py`) so any agent can discover the tool + protocol
inventory in one GET — but that is a catalog, not a gateway.

### Phase 3 — Read-only MCP sidecar telemetry
- Re-expose the EXISTING MCP server in a read-only mode that reflects
  the running daemon's state (state, logs, task progress) so a chat
  client connected via MCP can observe what the daemon is doing.
- This is a thin re-projection, not a new server: same tools, filtered
  to the read-only/telemetry subset, pointed at the daemon's state view.
- DoD: with the daemon running, an MCP client sees live task/progress/
  state telemetry; write tools are absent or refuse in sidecar mode.

### Phase 4 — Ephemeral sandbox interface (Docker/Podman + native fallback)
- A standard sandbox interface: map `workspace/` as a bounded volume
  into a disposable container, run agent code, capture stdout/stderr to
  the audit trail, tear down.
- Runtime detection: Docker → Podman → native fallback (with a loud
  audit note that execution was unsandboxed). MUST work on a host with
  no container runtime (Vibhav's dev box).
- Wire into the existing exec tools (`tools/actions/exec/scripts.py`
  etc.) behind a config flag so native stays the default until proven.
- DoD: code runs in a container when one exists; falls back cleanly when
  not; audit trail records which mode was used and the full logs.

### Phase 5 — Read-only local web dashboard
- A lightweight, offline-safe, read-only dashboard served by the daemon:
  project execution step progress, interactive visualization trees,
  citation lists, file audit log. Mirrors the existing synthesis
  dashboard design tokens / a11y / offline-safety conventions.
- DoD: `localhost:<port>` shows live project status; no network
  requests; renders for a real project; updates as tasks progress.

### The 4.0.0 cut (after Phase 5 is proven)
- Make the daemon the default `research-os start` behaviour (stdio MCP
  becomes `research-os start --stdio` or a sidecar mode).
- Collect any deferred breaking renames.
- `docs/MIGRATION.md` + CHANGELOG Migration section.
- Bump to 4.0.0, tag, release.

---

## 5. How to work this safely (process for every session)

1. Read this file. Read the Progress Log (section 7).
2. `source /scratch/vsetlur/anaconda3/etc/profile.d/conda.sh && conda
   activate research-os`. Confirm the baseline gate is green BEFORE
   starting (so you know any breakage is yours).
3. Work on a `feat/v4-<slug>` branch off `dev`. Small, reviewable PRs.
4. Re-run the full gate before every push.
5. For big design-heavy steps, dispatch parallel subagents to draft the
   design / explore options, synthesize into a spec, THEN implement.
6. Update the Progress Log at the bottom of this file before ending the
   session. Record: what shipped, what's half-done, the next concrete
   step, and any landmine discovered. This is the anti-degradation
   mechanism — be specific enough that a cold session can resume.
7. Keep memory (the Hermes memory store) in sync with the high-level
   status, but the DETAIL lives here in the repo where it's versioned.

---

## 6. Design decisions (resolve as we go, record the decision)

Decisions are append-only with a date + rationale. A judge phase may
REVISIT a decision — when it does, add a new dated entry that supersedes
the old one rather than editing history.

- **[RESOLVED 2026-06-23] Web framework for the daemon's HTTP endpoints:**
  `starlette` + `uvicorn`, in the `[daemon]` optional extra, imported
  lazily. Rationale: the event-bus endpoints need SSE streaming
  (`/v1/stream`, `/v1/events`), which stdlib `http.server` makes painful;
  starlette is a thin ASGI layer and uvicorn is the de-facto server.
  Mitigation for the "heavy dep" worry: it's opt-in (extra), lazy, and
  the daemon degrades with a clear "install research-os[daemon]" message
  when absent. The HTTP layer lives behind a thin `daemon/server.py` so
  the transport stays swappable if a judge phase wants to reconsider.
- **[RESOLVED 2026-06-23] Multi-project model:** ONE daemon, MANY roots
  keyed by absolute path. Rationale: the daemon already resolves root
  per-request (`_resolve_project_root`), so a root registry is the
  natural fit and avoids a port-per-project explosion. A `Workspace
  registry` maps root → cached engine handles (ledger view, last status).
- **[RESOLVED 2026-06-23] State backend:** keep JSON `ResearchLedger`
  (proven, file-locked, atomic, self-healing on corruption). Do NOT move
  to SQLite now. Revisit ONLY if concurrent multi-client writes prove the
  lock contention is real (a judge-phase candidate, not a build blocker).
- **[OPEN] Auth on localhost endpoints:** bind 127.0.0.1 only (done in
  DaemonConfig) + a per-session bearer token for any MUTATING endpoint.
  Read-only endpoints (Phase 1) are localhost-bind-only for now. DECIDE
  the token scheme before the first mutating endpoint (Phase 2 tool
  dispatch). Candidate: a token minted at daemon start, written to
  `.os_state/daemon_token` (0600), required as `Authorization: ***
- **[OPEN] Long-job persistence:** the Phase-1 task queue is in-memory.
  Decide whether jobs must survive a daemon restart (persist queue to
  `.os_state/`) — likely yes for the "master loop owns multi-hour work"
  promise. Judge-phase candidate once the queue has real jobs.

---

## 7. Progress log (append-only; newest at top)

### 2026-06-24/25 — 4.0.0 hardening: multi-persona stress test (find + fix + verify)
Ran two batches of 3 parallel persona subagents (isolated git worktrees) against
the whole system, then integrated + finished + verified every fix on
feat/v4-daemon-core. 9 real root-cause bugs fixed, +8 regression tests.

Batch 1 (grad / PI / shared-HPC): interrogative-question hypotheses produced
broken prose; thousands-separated sample sizes false-blocked as hallucinations;
grounding corpus missed outputs/ root + caption files (false ship-gate blocks);
share-archive title disagreed with machine metadata; shipped README linked to
excluded files; staleness verdict could block forever without provable currency
(now degrades open); consent spent.json grew unbounded (now self-pruning, wired
through autopilot_gate, back-compat preserved).

Batch 2 (tool-builder / multi-mode / naive-AI): orphan literature/ README in
non-analysis modes (gated on layout); 'run the tests'/'run the build' dead-ended
or misrouted (new run_build_checks shortcut → tool_build); 'release it' skipped
the lifecycle (→ release_and_changelog); notebook_workflow + program_setup
chains dead-ended (wired forward); multi_study never seeded shared/protocol.md
(now seeded); stale notebook GETTING_STARTED line; _classify_pause dead
'long_running_job' branch removed; STATE.md had no 'what to do next' (added,
defers to sys_boot as source of truth).

Verified: all 6 modes init+boot with a mode_directive; the MCP↔daemon seam holds
(server+router import zero daemon modules); protocol library doctrine-clean;
live routing confirmed for the new build shortcuts. Gate: preflight 38/38,
pytest 2759, ruff clean. Subagents instructed to clean up after themselves;
stray temp probe files + their worktree scratch removed. NOT released — driving
to a clean state on dev for a maintainer stress test next.

### 2026-06-24/25 — Plain install + practical doc rewrites
Two changes. (1) **Packaging:** folded the old `[all]` extra set (web /
literature / viz / audit / ml / notebook / semantic / data) into base
`dependencies`, so `pip install research-os` now gives the full Python
experience — no extras to remember. Kept the per-feature extras + `[all]` as
no-op back-compat aliases; system-runtime features (r / julia / execution /
daemon serving) stay real opt-in extras. Updated the now-stale directed-install
hints in code (data/semantic/all import guards) to `pip install --upgrade
research-os`. (2) **Docs:** scrubbed every `[all]`/extras install line across
docs → plain `pip install research-os`; deep-rewrote the README to lead with a
real 30-second worked example, sharpened the problem framing (failure-mode →
guarantee table), real researcher vignettes, the two-layer (reactive core +
optional enforcement daemon) story, and the self-improving-agent-layer (Hermes)
pairing — all six modes named. Added a 'Your first ten minutes' end-to-end
walkthrough to START.md. Collapsed SETUP's redundant Default/Minimal split;
fixed FAQ's synthesis/extras answers. No broken links; round-trip + xref guards
green. Gate: preflight 38/38, pytest 2751, ruff clean.

### 2026-06-24/25 — Doc accuracy sweep: every doc matched to the live system
After the docs/v4 consolidation, audited all user/AI/architecture docs against
ground truth (v3.12.0, 154 tools, 146 protocols, 14 categories, 6 modes, 25
daemon paths) and fixed the drift. PROTOCOLS.md: stale category table + '130+/
thirteen categories/as of v3.11.1' header → current counts, new protocols
(data_preparation, agent_setup, voice_calibration, tool_evaluation_loop) called
out, auto-catalogue regenerated via scripts/regen_protocols_doc.py (146, all
listed). ARCHITECTURE.md: 152/142/15 → 154/~146/14, brittle prose counts
replaced with stable phrasing. START.md: chat-first quickstart + 'Eleven
commands' + added missing 'daemon' subcommand + 'Bring in your project — chat or
files'. AI_GUIDE.md: documented intake chat-fill params; dropped stale '(130+)'.
USE_CASES.md: added the 3 missing modes (notebook/hybrid/multi_study) to the mode
table. SETUP/FAQ: chat-first phrasing + repointed renamed anchor. TOOLS.md:
intake_autofill + synthesis_check grounding-mode descriptions. No broken links;
round-trip + xref guards green. Gate: preflight 38/38, pytest 2751, ruff clean.

### 2026-06-24/25 — Docs consolidation: drop the v4 silo, fold into docs/
Removed the docs/ vs docs/v4/ split. 'v4' is internal jargon, and the
architecture docs describe SHIPPED behaviour — siloing them hid them from every
index. All 9 docs/v4/*.md moved into docs/ (git renames): DESIGN_V4.md →
ARCHITECTURE.md; ROADMAP.md (this file) + the seven gate/daemon design docs kept
their names. Rewrote every reference across 31 files (daemon/, server/, scripts/,
tests/, CLAUDE.md): docs/v4/X → docs/X, prose DESIGN_V4 → ARCHITECTURE; zero
remain. De-versioned the ARCHITECTURE + ROADMAP headers. Added an 'Architecture
& internals' section to docs/README.md (the 9 docs were in no index) and
Architecture/Daemon rows + an 'Optional daemon enforcement kernel' bullet to the
top-level README (the daemon was absent from it). No broken links; all preflight
guards green against the new paths. Gate: preflight 38/38, pytest 2751, ruff
clean.

### 2026-06-24/25 — The receiver's view: a front door for shared archives
New perspective — the collaborator / PI / reviewer who RECEIVES the work and
must trust it without having done it. The share archive correctly strips all
AI-facing orientation (GETTING_STARTED, AGENTS, .os_state) but nothing replaced
it: a recipient unzipped into raw numbered folders + JSON manifests with no
human guide. README.md shipped only 'if present'; ro-crate/codemeta are for
tools, not people.
- **README_SHARED.md (`396d156`)** is now generated at the archive root by
  export_share_archive.py, stitched from the project's own files: What this is
  (question + domain, extracted from research_overview/STATE/intake, skipping
  the 'not yet set' placeholder), What was done (each numbered step + its
  conclusions headline), Deliverables (synthesis/ outputs), and How to read &
  trust this (folder map, narrative logs, pinned env, claims trace to
  workspace artefacts, the reproduce recipe). Named README_SHARED.md so it
  never clobbers a researcher's own README; always present so the recipient
  always has a front door.
- Fixed a template-escaping bug found in the process (literal newline expanded
  at template-definition time broke the generated script); added a test that
  compiles the template + a test that runs the real generated script and
  asserts the README lands in the zip with all sections.
- Principle: trust is a RECEIVED property. The person who didn't do the work
  needs the shortest path to 'what is this, what was done, can I trust it,
  how do I reproduce it' — and it must be in the artifact, not in RO.
- Gate green: preflight 38/38, pytest 2751, ruff clean.

### 2026-06-24/25 — UX pass: every researcher-facing surface chat-first + human-spoken
Looked at the system purely from what the researcher SEES and HOW they interact,
and fixed surfaces that contradicted the chat-first intake or leaked the AI's
internal tool names into human-facing text (`35c6308`, `ebe9485`).
- **Done-card** (first impression after init): reordered open-IDE → 'just tell
  the AI what you're studying, no files needed' → chat. Was file-drop-first.
  Verified by a live init.
- **GETTING_STARTED.md** (analysis/exploration/notebook modes): step 1 is now
  open-IDE / 'bring in your project — chat or files' with a concrete one-liner
  and files-as-fallback; first 'try' example is 'describe my project'. Was
  'Drop your files' first — contradicting the chat-first intake.
- **STATE.md**: unset-question hint said 'run tool_intake_autofill' — a
  researcher reading their own status file shouldn't be told an internal tool
  name. Now 'just tell the AI what you're studying, e.g. ...'.
- **'When things go wrong' table**: 'Run tool_workspace_repair' → 'Fix my
  workspace'; '<id>' → 'the last good one'.
- Principle: researchers chat, they don't call tools or hand-edit files. Every
  surface they read leads with the lowest-friction path and speaks human; tool
  names live in AGENTS.md (the AI's rules), not the human's onboarding.
- Gate green: preflight 38/38, pytest 2749, ruff clean.

### 2026-06-24/25 — Chat-first intake: fill the project without touching inputs/
Real onboarding UX gap: the whole intake flow assumed the researcher DROPS
FILES into inputs/, and tool_intake_autofill only inferred question/domain/
hypotheses from those files. Many researchers never edit inputs/ — they just
describe the project in chat. There was no smooth capture path, and
project_startup's scan_inputs DEAD-ENDED on empty inputs/.
- **tool_intake_autofill (`58bc343`)** gains question/domain/hypotheses/
  context_note params. Explicit chat values beat file inference, so an EMPTY
  inputs/ still yields a real intake; context_note joins the corpus so
  research_overview captures the framing verbatim. No-arg behaviour unchanged.
  Wired through tool def + handler.
- **project_startup**: scan_inputs no longer dead-ends — routes to the chat
  path when the researcher described the project conversationally, asks (one
  line, both paths offered) only when there's neither files nor a description.
  autofill_intake documents both paths.
- **inputs/intake.md template** now leads with 'just tell the AI in chat' as
  option 1. Carries a hidden ro:intake-template marker so intake_freshness
  still treats the unfilled scaffold as a stub (the richer template was being
  mis-read as filled); marker is gone once autofill writes the real intake.
- The principle: every input path works — chat-only, files-only, mixed, empty.
  Never force a researcher to write a file to start.
- Gate green: preflight 38/38, pytest 2749, ruff clean.

### 2026-06-24/25 — Mixed-mode layer made legible + skill-layer-first streamlining
With the RO MCP server now live (154 tools), exercised routing end-to-end and
improved the mixed-mode layer across all working modes plus the Hermes-skill
streamlining the user asked for.
- **Skill-layer-first tool discovery (`3169010`).** methodology/tool_discovery
  now consults the agent's domain skill layer (Hermes) FIRST: a skill already
  names the canonical library with validated params, so take it as the strong
  default + skip to install/log; fall through to the generic search reasoning
  only when no skill covers the task. The 'streamline where Hermes skills exist'
  pattern — keep the reasoning scaffold, defer how-to to the skill layer. Skill
  says HOW, RO confirms it FITS + records WHY.
- **Evaluate-loop mode-boost gap fixed (`3169010`).** build_evaluate (→
  build/tool_evaluation_loop, the evaluate→improve heartbeat) was in NO mode's
  boost set. Added it to tool_build (+2) and hybrid (+1) — it's a core build
  activity AND the heart of the hybrid loop. Verified live.
- **sys_boot now surfaces the mode (`71e9ea2`).** The deepest mixed-layer gap:
  workspace.mode silently biased routing but the AI never SAW it at boot, so it
  couldn't act mode-appropriately or notice when to switch. sys_boot now returns
  workspace_mode + a one-line mode_directive for all 6 modes, each with its
  behaviour + transition signal (analysis→hybrid when you need to build a tool,
  exploration→promote a probe, etc.). The mode is now a stated context the AI
  reasons about, not an invisible bias.
- Gate green: preflight 38/38, pytest 2747, ruff clean.

### 2026-06-24/25 — The layered-research-OS thesis: RO guidance + a self-improving agent layer
Researched the Hermes skills ecosystem online (hermes-agent.nousresearch.com/
docs) and acted on the architectural thesis it confirms: the best research
setup is RO (guidance + enforcement + provenance) UNDER a self-improving,
project-aware agent layer (Hermes as reference) that runs above any model.
Hermes skills are index-and-fetch style — e.g. the Bioinformatics skill indexes
400+ external bioSkills/ClawBio skills fetched on demand — which is exactly RO's own
philosophy ('RO needn't contain everything'). The pairing existed in code
(`research-os hermes add`, the distill/promote skill registry, the RO SKILL.md)
but wasn't discoverable or guided.
- **guidance/agent_setup protocol (`6926263`).** Scaffolds architecting the AI
  layer for a project: assess current setup → name the capabilities a research
  agent layer needs (persistent memory, skill ecosystem, MCP, self-improvement,
  model-agnostic) → choose + wire the layer (Hermes ref via hermes add; other
  MCP clients via ide add; CLI path for chat-only) → tailor researcher_config →
  ALIGN skills with protocols (skills = tool/domain how-to; protocols = method
  choice + grounding + reproducibility; distill/promote so it compounds).
  Doctrine-correct: recommends Hermes but allows any layer, naming capabilities
  not mandating a product. 182 protocols.
- **Hermes as a first-class init step (`6926263`).** The wizard now offers
