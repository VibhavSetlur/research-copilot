# Research OS — Architecture

> **The system's architecture and design rationale.** What the MCP server
> is, what the daemon is, what moves and what stays, where protocols live,
> and the design principles that hold the line. Read alongside
> [`ROADMAP.md`](ROADMAP.md) (the build log + design history) — this is the
> *why* and the *what*; the roadmap is the *when*.

---

## 0. One sentence to start

**Research-OS calls no LLM and has no gateway.** It is a pure passive tool
provider: it exposes MCP tools, protocol scaffolds, and journaled project
state. Every act of reasoning belongs to the user's IDE or AI client. RO
ensures that reasoning is grounded, gated, reproducible, and auditable.

The throughline: **turning soft, trusted prose into hard, verified structure
— while the reasoning layer stays soft** (see [`docs/PROTOCOL_DOCTRINE.md`](PROTOCOL_DOCTRINE.md)).

---

## 1. The system as it actually is today

Three surfaces, one clean seam:

| Surface | Inventory | Role |
|---|---|---|
| `server/` (MCP) | Generated and verified at build/test time; see [TOOLS.md](TOOLS.md) and `docs/_STALE_COUNTS_REFERENCE.md` | Passive tool provider. Tools + protocols + router + ledger. |
| `daemon/` | enforcement + execution + notification kernel | Runs, schedulers, journal, provenance, recovery, gates, event bus. |
| `protocols/` | Generated and verified at build/test time; see [PROTOCOLS.md](PROTOCOLS.md) | Scaffolds for reasoning — the "how to think" layer, not scripts. |

The critical property of this split: there is **exactly one seam** between
`server/` and `daemon/`, and it is enforced:

```python
# server/dispatch.py
def _handle_tool_call(name: str, arguments: dict, root: Path) -> list[TextContent]:
    # rate-limit -> resolve alias -> autopilot gate -> _HANDLERS[name](...) -> normalize envelope
```

`server/` and `tools/` MUST NOT import `research_os.daemon`. The dependency
arrow points daemon→server, never the reverse. The daemon reads project
state from the on-disk `.os_state/` contract, surfaced through
`server/daemon_bridge.py` (canonical paths + `daemon_present` +
`http_get`/`http_post`). This invariant is enforced by `scripts/preflight.py`.

---

## 2. The architectural thesis: FRONT, don't MOVE

The instinct "move tools to the daemon" is wrong. The correct decomposition:

### Layer A — Reasoning core (STAYS in `server/`, unchanged)

The tools and protocols are *pure functions over project state*. They take
`(name, args, root)` and return an envelope. They have no concept of
transport, sessions, or concurrency. **They never learn about HTTP or
daemons.** Moving them into the daemon would couple reasoning to transport —
the exact mistake this architecture exists to undo.

- Tools stay where they are. The daemon fronts `_handle_tool_call`.
- Protocols stay as YAML under `protocols/`. They are read by the router,
  which the daemon also fronts.
- `ResearchLedger` stays the source of truth for project state.
- **There is no chat-completions proxy.** Multi-agent orchestration belongs
  at the client level and was explicitly rejected as a daemon responsibility.
  Personas are client-read mode context and dispatch-time policy, not
  prompt injection by RO.

### Layer B — Daemon kernel (LIVES in `daemon/`, the enforcement + execution spine)

The daemon is an enforcement + execution + notification kernel that fronts
Layer A via the on-disk seam. It provides:

- **Multi-root state registry** — one daemon, many project roots keyed by
  absolute path; a `Workspace` registry caches engine handles per root.
- **Background task queue** — enqueue long-running jobs off the request
  thread; jobs call existing engine functions.
- **Subprocess + SLURM runner** — durable process ownership independent of
  the IDE session; SLURM submit/poll/cancel.
- **Durable run journal + crash recovery** — inputs/command/outputs +
  artifact hashes recorded per run; interrupted-run rehydration on restart.
- **Provenance / lineage / staleness / reproduce** — lineage DAG linked by
  content hash; freshness verdict blocks stale deliverables.
- **Resumable runs** — interrupted runs are rehydrated as `INTERRUPTED`,
  the researcher is notified, and *orient* recommends `resume_interrupted`.
- **Sandbox tiers + resource budgets** — per-run `rlimit`s
  (mem/CPU/wall/fsize/nofile) from `runtime.resource_budget`; a real kernel
  ceiling on shared nodes.
- **Notification spine** — every run-finish / interrupt emits a
  notification via `notify_command` or the outbox.
- **Consent / hard gates** — a floor gate needs a one-shot,
  argument-bound token only a human can mint; the AI can request but never
  grant.
- **Event bus** — SSE at `/v1/stream` and `/v1/events`; one bus, many
  subscribers.
- **`/v1/capabilities` front door** — one read-only GET describing
  identity + field + tool/protocol inventory + work-state freshness; logic
  in `daemon/capabilities.py`. This is NOT a gateway.
- **Read-only HTTP endpoints** — `/healthz`, `/v1/state`, `/v1/runs`,
  `/v1/capabilities`; localhost-bind-only for read paths.
- **Bearer-auth-gated mutating endpoints** — `/v1/runs` (submit),
  `/v1/gates/respond`, `/v1/consent/*` and similar mutating paths are
  guarded by a per-session bearer token (env `RESEARCH_OS_DAEMON_TOKEN`,
  config field `auth_token_env`). When no token is configured, those
  endpoints stay open behind the 127.0.0.1 localhost bind. Provision via
  `research-os daemon token --mint-token`.

### Layer C — Transport (STDIO MCP + daemon HTTP)

Two transports, no gateway:

- **stdio MCP** — the original surface; still the default for IDE users.
  Communicates via `_handle_tool_call`. Unaffected when no daemon is
  present.
- **Daemon HTTP** — read-only + bearer-auth-gated-mutating endpoints
  served by the daemon over localhost. The only surface that knows about
  wire formats. No `/v1/chat/completions`, no completions proxy of any kind.

Still ahead: a **read-only web dashboard** (`localhost:<port>`) showing
live project status — the one surface not yet shipped.

### The one real migration

The MCP `exec`/run tools (`tool_exec_*`) currently spawn subprocesses
directly. They should be rewired to call `daemon.run_command` so that:

- agent-run code and human-run code share the journal + provenance,
- reproduce/diff work on agent runs too,
- there is one execution audit trail, not two.

That is the *only* thing that "moves." Everything else *fronts*.

---

## 3. Background-safety guarantees (what the daemon actually promises)

The daemon's reason to exist is that research jobs are long and people walk
away from them. The execution spine ships with a concrete safety contract —
these are guarantees, not aspirations, each mapping to a running piece of
`daemon/`:

| Guarantee | Mechanism | Where |
|---|---|---|
| **Long jobs survive disconnect** | the daemon owns the process, not the IDE's MCP session; closing the chat doesn't kill the run | `runners`, `tasks` |
| **Everything that runs is journaled** | inputs/command/outputs + artifact hashes recorded per run; lineage DAG linked by content hash | `runstore`, `provenance`, `lineage` |
| **Runaway jobs are bounded** | per-run `rlimit`s (mem/CPU/wall/fsize/nofile) from `runtime.resource_budget`; a real kernel ceiling on a shared node | `resource_budget`, `sandbox` |
| **Consent gates hold unattended** | a floor gate needs a one-shot, argument-bound token only a human can mint; the AI can request but never grant | `consent` |
| **Stale results can't ship** | freshness verdict over the lineage DAG; compiling the final deliverable is blocked while inputs it depends on have changed | `staleness`, `lineage` |
| **You find out what happened** | every run-finish / interrupt emits a notification, delivered via `notify_command` or held in the outbox | `notifications`, `events` |
| **Interrupted runs recover** | on start, any run whose last persisted status was non-terminal is rehydrated as `INTERRUPTED`, the researcher is notified, and *orient* recommends `resume_interrupted` | `core` (rehydrate), `runstore` (`mark_interrupted`), `orient` |

### The interrupted-run recovery path (the "box rebooted" case)

The flow is entirely server-side and needs no client present:

```
daemon start
   └─ runstore.recent_manifests()            # read the run journal
        └─ any run with non-terminal status?  # it looked live; the daemon is fresh ⇒ it died mid-run
             └─ runstore.mark_interrupted(id) # rewrite manifest status → INTERRUPTED (+ transition)
                  └─ notifications.emit_runs_interrupted(ids)   # push or outbox
                       └─ orient: action="resume_interrupted"   # surfaced FIRST among run states
```

Rehydration is idempotent and best-effort — a failure to rehydrate logs at
debug level and never blocks startup. The *orient* logic deliberately ranks
an interrupted run **above** a failed one: a half-finished job that *looks*
complete is the most dangerous thing a returning researcher can build on,
so the AI is told about it first and steered to finish it before proceeding.

---

## 4. Fail-safe closed / degrade-open

No daemon ⇒ behaves exactly as the stdio MCP server (stdio users unaffected).
Ambiguous enforcement ⇒ never silently pass a gate, never falsely block.
Each daemon layer is independently optional: the system runs without a
sandbox, without a dashboard, without a daemon — core boots with only
stdlib + current deps; heavy web libs are imported lazily and degrade with
a clear "install research-os[daemon]" message when absent.

---

## 5. Where protocols live, and how they get better

Protocols stay as YAML under `protocols/`; their catalogue is generated and
verified at build/test time. They are **scaffolds for reasoning, not scripts to execute** — see
[`docs/PROTOCOL_DOCTRINE.md`](PROTOCOL_DOCTRINE.md). Today they are
reachable reactively (the router picks one when a tool call arrives); the
daemon unlocks three new modes:

1. **Proactive protocol execution.** The daemon can *drive* a protocol as
   a long-running plan: step through a multi-stage methodology, parking
   between steps, surviving client disconnects. Today a protocol is a
   suggestion the agent may ignore; the daemon can make it a *tracked
   workflow* with state.
2. **Protocol-as-DAG.** A protocol's `decomposition` is implicitly a
   dependency graph. The daemon can compile it into an executable DAG
   (run step 3 only after 1+2 succeed) — this is the snakemake/nextflow
   convergence point, done natively.
3. **Protocol provenance.** Every protocol step that touches execution
   gets journaled, so "which protocol produced this figure" is answerable.

The improvement: protocols evolve from *static reasoning scaffolds* into
*resumable, audited, partially-executable workflows* — without rewriting
a single YAML, because the daemon reads the same files.

---

## 6. Feature inventory (daemon build phases)

Grouped by value delivered. ✅ = shipped.

### A. Run lifecycle & reproducibility (the foundation)
1. ✅ Durable run journal + provenance capture
2. ✅ Artifact tracking (cwd-diff, sha256)
3. ✅ Human CLI surface (run/runs/logs)
4. ✅ Reproduce-a-run (byte-level verdict)
5. ✅ HPC scheduler runner (SLURM submit/poll/cancel)
6. ✅ Run comparison / experiment diff
7. **Run lineage graph** — DAG of runs linked by artifact-hash provenance.
8. **Re-run with overrides** — `daemon run --from <id> --set SEED=42` to
   fork an experiment changing one variable, lineage preserved.
9. **Artifact garbage collection** — content-addressed artifact store with
   dedup + retention policy.
10. **Run tagging & search** — tag runs, query by tag/status/date.
11. **Snakemake/Nextflow adapters** — workflow engines as run-kinds, so a
    pipeline gets one journal entry with per-rule sub-runs.
12. **Input registry** — hash + register input datasets so reproduce can
    verify inputs didn't drift, not just outputs.

### B. Multi-root serving + transport
13. ✅ Per-session bearer token auth for mutating endpoints
14. ✅ Event bus (SSE at `/v1/stream`, `/v1/events`)
15. ✅ Multi-root state registry (one daemon, many project roots)
16. ✅ `/v1/capabilities` agent front door (`daemon/capabilities.py`)
17. **Read-only web dashboard** — the one surface still ahead: live runs
    table, artifact previews, diff viewer, lineage graph at
    `localhost:<port>`.
18. **Client session continuity** — a Cursor session and a CLI session
    observe the *same* project state simultaneously.

### C. Execution safety & environments
19. ✅ Native execution sandbox (resource limits via cgroups/ulimit)
20. **Conda env capture & restore** — record the exact env; reproduce can
    rebuild it (`conda env export` → lockfile in the manifest).
21. **Ephemeral env per run** — optional fresh env from a lockfile so runs
    can't pollute each other.
22. **Secret redaction in journals** — scrub tokens/keys from captured
    logs before they hit `.os_state/`.
23. **Dry-run / plan mode** — show what a run *would* do without executing.

### D. The research workflow itself
24. **Proactive protocol driver** — daemon steps through a methodology
    protocol as a tracked, resumable plan.
25. **Protocol-as-DAG executor** — compile a protocol decomposition into a
    dependency graph and run independent steps in parallel.
26. **Literature ingestion pipeline** — long-running batch fetch as a
    daemon job (the canonical "MCP can't do this" case).
27. **Citation graph builder** — build + serve a citation network from the
    project's literature, queryable.
28. **Notebook execution as runs** — execute a `.ipynb` as a tracked run;
    artifacts = output cells + figures.
29. **Hypothesis ledger** — register hypotheses, link runs as evidence
    for/against, track the research narrative.
30. **Auto-provenance for figures** — every figure written during a run
    stamped with run id + git commit in its metadata.
31. **Result freshness checks** — daemon periodically re-reproduces key
    runs and flags any that have drifted.
32. **Data versioning** — DVC-style content-addressed dataset tracking
    integrated with the input registry.

### E. Observability & operations
33. **Structured metrics** — Prometheus-style `/metrics`.
34. **Run timeline / Gantt** — visualize concurrent runs over wall-clock.
35. **Health & self-diagnosis** — `daemon doctor` checks scheduler
    availability, disk, env, port, ledger integrity.
36. **Log aggregation & tail** — `daemon logs --follow` live-tail any run.
37. ✅ Crash recovery — interrupted-run rehydration shipped (daemon restart
    marks orphaned non-terminal runs `INTERRUPTED`, notifies, and *orient*
    recommends `resume_interrupted`). Still to do: re-attach to in-flight
    SLURM jobs by recorded scheduler job id.

### F. Collaboration & sharing
38. **Run export / import** — bundle a run as a portable archive.
39. **Shareable reproduce reports** — a self-contained HTML reproduce verdict.
40. **Project snapshot** — freeze the whole project state at a tag.
41. **Read-only share link** — serve a project dashboard read-only to a
    collaborator on the same network.
42. **Audit log export** — full chronological event log for a methods section.

### G. Intelligence & ergonomics
43. **Smart run suggestions** — "you changed `train.py`; re-run the 3 runs
    that depend on it?" (uses lineage graph).
44. **Failure triage** — on a failed run, surface the error + the diff vs
    the last successful run of the same command.
45. **Cost/resource accounting** — track cpu-hours / SLURM allocation per
    project, per experiment.
46. **Natural-language run query** — "show me the run that produced
    fig3.png" answered from provenance.

---

## 7. Build order (dependency-aware)

```
[done] run lifecycle (1–6)
   │
   ├─ 7 lineage ─ 8 re-run-overrides ─ 43 suggestions ─ 46 NL query
   ├─ 12 input registry ─ 32 data versioning ─ 31 freshness
   ├─ 20 env capture ─ 21 ephemeral env ─ 19 sandbox
   │
   ├─ 14 event-bus streaming ─┬─ 17 dashboard ─ 18 continuity
   │                          └─ 15/16 multi-root + capabilities
   │
   └─ 11 workflow adapters ─ 25 protocol-DAG ─ 24 protocol driver
```

**Next recommended phases:**
- **Run lineage graph (#7).** Cheap now (artifacts already hashed); unlocks
  suggestions, NL query, re-run-overrides, freshness. Highest leverage per LOC.
- **Re-run with overrides (#8).** Turns the journal from a record into an
  *experiment-forking* tool.
- **Read-only web dashboard (#17).** The one surface still ahead in group B.

---

## 8. What "better" means concretely

Three principles to hold the line through every phase:

1. **The reasoning layer stays pure.** No tool, no protocol ever imports
   from `daemon/`. The dependency arrow points one way: daemon → server,
   never back. Enforced by `scripts/preflight.py`.
2. **One execution path.** Agent-initiated and human-initiated runs go
   through the same `daemon.run_command`. No second subprocess spawner.
3. **Everything that runs is reproducible.** If it has a lifecycle, it
   gets a manifest. No "quick" untracked execution path that escapes
   provenance.

---

## Summary

Research-OS is a pure passive reasoning core (generated MCP tool and protocol
catalogues + journaled state) fronted by an enforcement/execution/notification daemon
kernel and grounded by reproducible provenance. The daemon provides durable
run ownership, consent gates, staleness enforcement, crash recovery, a
notification spine, and a bearer-auth-gated HTTP API — but it calls no LLM
and proxies no completions. There is no gateway inside RO. All reasoning
belongs to the user's AI client. The seam between `server/` and `daemon/`
is enforced by preflight: the arrow points daemon→server, never the reverse.
