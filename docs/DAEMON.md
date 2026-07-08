# The Research OS daemon

The daemon is **optional**. Research OS works fully without it — every
`sys_*` / `tool_*` call runs in-process through your IDE's MCP connection,
and that's the right setup for most chat / IDE sessions. The daemon adds a
separate, persistent process that turns Research OS from a set of tools
into a small **operating layer** around your project.

If you never start a daemon, none of what follows is in your way: hard
gates fall back to a simple confirmation, jobs run inline, nothing
changes.

## When to start it

Start a daemon when you want any of:

- **Long jobs that don't block the chat** — kick off a fit / sweep /
  benchmark / pipeline run, get the turn back immediately, and be
  **notified when it finishes** (optionally straight to Slack / email / a
  webhook).
- **Run provenance + freshness** — every tracked run records its inputs,
  command, environment, and outputs, so the daemon can tell you when a
  result has gone **stale** (an input changed underneath it) and rebuild
  exactly the affected sub-graph.
- **Hard gates you can't accidentally skip** — with a daemon present, the
  riskiest actions (compiling the final paper, a force-overwrite, a big
  job, scaffolding a paper before the work exists) require a **real,
  one-time, human-authorised approval** — not just the AI deciding it's
  fine.
- **A resource budget the machine enforces** — declare a memory / CPU /
  wallclock ceiling once and every run the daemon launches is held to it
  (a real `rlimit`, not a suggestion). Especially valuable on a shared
  cluster.
- **Work that survives you walking away** — a long job keeps running after
  you close the chat, and if the daemon itself dies mid-run the next start
  **rehydrates** that run as `INTERRUPTED` and tells you. Nothing silently
  vanishes. (See [*When you walk away*](#when-you-walk-away).)

---

## Start / stop

```bash
research-os daemon start      # serve the localhost API + job queue
research-os daemon status     # is it running? what project is active?
research-os daemon stop       # graceful, per-project
```

The daemon binds `127.0.0.1` only (never a public port). One daemon serves
the project it's started in; it writes a small descriptor to
`.os_state/daemon.json` so your IDE's MCP session discovers it
automatically — the AI's `sys_daemon` tool reports it without any wiring.

On a shared login node with no Docker and no systemd, prefer
`research-os daemon setup` — it does the awkward parts for you (see
[*Shared servers & HPC*](#shared-servers--hpc)).

---

## The three ways to run a long job

This is the heart of the daemon for a researcher. There are **three
runtimes** for a long, reproducible job. They differ only in *where* the
process runs — **all three are journaled, provenanced, and stall-watched
identically**, and all three show up in the same run list and the same
lineage graph.

| Runtime | Command | Runs in… | Records | Use it when |
|---|---|---|---|---|
| **native** | `research-os daemon run "<cmd>"` | your current conda / venv env, on this box | git sha + environment | quick-to-medium jobs on the machine you're on |
| **container** | `research-os daemon docker IMG -- CMD` | a Docker / Podman image | **image + content digest** (bit-for-bit recreatable) | you need a pinned, portable environment |
| **scheduler** | `research-os daemon submit "<cmd>"` | a SLURM-allocated node | full env snapshot + scheduler job id | heavy compute that belongs on the cluster |

```bash
research-os daemon run "python fit.py --epochs 200"        # native
research-os daemon docker myimg:tag -- python run.py        # container
research-os daemon docker myimg:tag --gpus all -- python train.py   # container + GPU
research-os daemon submit "python sweep.py"                 # SLURM
research-os daemon runs                                     # list recorded runs
research-os daemon logs <run_id>                            # a run's details + captured output
```

**native** — runs in the environment you started the daemon in. Records
the git sha and the environment so the result is traceable. The simplest
path; the right default on your own machine.

**container** — runs the command *inside* a Docker or Podman image via the
daemon's `DockerRunner`. It mounts the project into the container so
outputs land back in your workspace, and records the **image name + its
content digest** — so the run is recreatable bit-for-bit, not just "ran in
some container once". Networking is **isolated by default**; opt in with
`--network`. Add `--gpus all` for GPU work. The same image-by-digest
record is what lets you hand the exact environment to a collaborator (see
[SHARING.md](SHARING.md#5-share-a-docker-image-by-digest)).

**scheduler** — hands the job to **SLURM** (`daemon submit`, or
`tool_slurm_submit`). The daemon polls the job to terminal state, survives
a login-node reboot, and re-attaches to an in-flight job by its recorded
scheduler job id rather than orphaning it. Defaults (partition, walltime,
cpus, mem) come from `runtime.cluster_defaults` in your config.

The same Docker path extends to **Kubernetes/HPC schedulers** via a
kubectl wrapper or the SLURM submit path. **Snakemake / Nextflow**
pipelines are detected as workflow run-kinds: `GET /v1/workflows` previews
the planned DAG via a read-only dry-run when the engine is installed, and
each pipeline gets one journal entry with per-rule / per-process sub-runs.

### What every tracked run records

Whichever runtime you pick, a tracked run records:

- **Provenance** — its inputs, the exact command, and its outputs, so the
  result is traceable to what produced it.
- **An environment snapshot** — for scheduler (SLURM) jobs especially, the
  **complete installed-package manifest** (not just the conda env *name*),
  so a 12-hour run is recreatable *from its record*, not merely
  describable.
- **A place in the lineage graph** — every run is a node; inputs/outputs
  are edges. This is what powers freshness + rebuild (below).

### The stall watcher

The daemon runs a **stall watcher**: a `RUNNING` job whose output hasn't
advanced in ~30 minutes is flagged as **possibly stuck**. It surfaces in
`daemon_notes` and to the AI — so you're not left waiting on a wedged job
that *looks* alive.

### When it finishes — notifications

When a run finishes, the daemon emits a notification. To have
notifications actually **reach** you, set a delivery command — a script
that receives the notification as JSON on stdin and posts it wherever you
want (Slack, email, a webhook):

```yaml
# inputs/researcher_config.yaml
daemon:
  notify_command: "/home/me/bin/ro-notify.sh"   # gets the notification JSON on stdin
```

With no `notify_command`, notifications are still **recorded** to the
outbox — you just pull them rather than be pushed:

```bash
research-os daemon notifications               # the outbox + delivery status
research-os daemon notifications --undelivered # only what didn't reach you
```

### How the AI launches a run (same journal)

The AI can launch a background run the same way, without blocking the
chat: when the gateway is enabled it `POST`s to **`/v1/jobs`** — the
single agent-initiated execution path, so an AI-launched run and a
CLI-launched run share **one journal, one provenance trail, one lineage
graph**. The job queue is visible read-only at `GET /v1/jobs`; the durable
archive of finished runs is `GET /v1/runs`. Submitting a journaled job is
gated (the gateway flag plus a per-session bearer token), so the AI can
never spawn unbounded background work on its own.

---

## Freshness, rebuild, and the provenance diagram

Because runs are tracked, the daemon knows the dependency graph and can
tell when a result is stale:

```bash
research-os daemon lineage              # the run dependency graph
research-os daemon stale                # which runs are stale (input changed / upstream stale)
research-os daemon rebuild              # re-run only the stale sub-graph, in dependency order
research-os daemon reproduce <run_id>   # re-run one recorded run, check outputs still match
research-os daemon diff <a> <b>         # compare two runs: command, env, outputs
```

The **run lineage renders as a provenance diagram**: `GET /v1/lineage.mermaid`
returns the graph as Mermaid, so you (or the AI, or a dashboard) can see
the whole chain — which run produced which artefact, what fed it, and
what's gone stale downstream — as a picture, not a table.

This is also a **safety gate**: with a daemon present, compiling the final
deliverable is blocked while results it depends on are stale — you can't
ship a paper (or a tool release) built on data that changed underneath it
without seeing the warning and clearing it.

---

## The approval loop (hard gates)

With a daemon running, a floor gate doesn't accept the AI's own
"confirmed" — it requires a token only **you** can mint. The full loop:

1. The AI hits a gated action and is told `consent_required`, with the
   exact `gate_key` and a fingerprint of the specific arguments.
2. The AI calls `sys_consent(action='request', …)` and tells you what
   needs approval and why.
3. You review and decide:

   ```bash
   research-os daemon consent                 # list pending requests + active grants
   research-os daemon consent approve <id>    # mint a one-shot, argument-bound token
   research-os daemon consent deny <id>       # refuse
   ```

4. The AI fetches the minted token (`sys_consent(action='token', …)`) and
   retries. The token is **one-shot** — it clears exactly that one action
   and is burned, so one approval can't be replayed across many calls.

The approval is bound to the exact action you saw: a token for "compile
paper.typ" can't be reused to compile something else.

---

## How the AI sees the daemon

The AI doesn't import the daemon — it talks to it over the local API the
same way you would, and only ever **reads** unless you authorise a change:

- **`sys_daemon`** — "is anything running in the background, what should I
  do next, what's the resource budget, were there undelivered
  notifications?" One call, the AI's situational awareness. When no daemon
  runs it returns `running:false` and the AI proceeds normally.
- **`sys_consent`** — the AI's side of the approval loop (above). It can
  *request* approval and *check* for a minted token, but it can never
  grant its own.

This is the deliberate split: the AI plans and reasons; the daemon holds
the things the AI must not be able to forge.

---

## What the daemon watches — in every workspace mode

The daemon's self-check (at startup and on a periodic tick) and the shared
structure audit are **mode-aware**, so the daemon stays involved whatever
kind of project this is:

- **all modes:** structure integrity, interrupted runs, unframed intake,
  agent-compliance (repeated protocol failures / abandoned protocols),
  provenance integrity (stale results whose inputs changed), script naming.
- **analysis / hybrid:** the above, plus (hybrid) the `tool/` half needs
  its own tests before the analysis relies on it.
- **tool_build:** `eval/` must define "done", `spec/` must say what's being
  built, `decisions/` should record ADRs, and the inner `project/` repo
  needs tests once it has code.
- **notebook:** flags notebooks that are stale versus the data they read,
  or a project with no notebooks yet.
- **multi_study:** flags an empty `studies/` or a missing `shared/` commons
  (codebook / preregistration / governing protocol).
- **exploration:** flags promote-worthy scratch probes that were never
  promoted to a numbered, provenanced step.

These surface as `daemon_notes` (read at `sys_boot`) and in the per-turn
audit findings, so the AI course-corrects early instead of a reviewer
finding the gap.

---

## One daemon per project

The daemon is **per-project**, not a global service. Each
`research-os daemon start` runs a separate process bound to one project
root, advertises itself in that project's `.os_state/daemon.json` (host,
port, pid), and writes that project's notes / journal / runs under its own
`.os_state/`. Two projects run two independent daemons — start and stop
each without touching the other. On a shared node the default port may be
taken; the daemon auto-selects a free one and records it, so per-project
daemons coexist. **Nothing leaks between projects.**

**Supervising several projects at once.** A daemon fronting more than one
project re-checks **all** of them on its periodic tick, and
`GET /v1/supervision` returns a roll-up — each project's health counts,
its worst findings, and a `needs_attention` list — so a PI can answer "are
all my students' projects healthy and on-protocol?" in one call without
opening each. Persistent BLOCKs still escalate per project.

---

## Resource budget

Declare a ceiling once, under `runtime:` in your config — the daemon turns
it into a real `rlimit` on every run it launches:

```yaml
# inputs/researcher_config.yaml
runtime:
  resource_budget:
    memory_mb: 16384      # RLIMIT_AS  per run
    cpu_seconds: 7200     # RLIMIT_CPU per run
    wall_seconds: 7200    # wallclock kill
    file_size_mb: 51200   # RLIMIT_FSIZE
    open_files: 4096      # RLIMIT_NOFILE
```

A blank or `0` field means uncapped (the sandbox default applies). On a
shared HPC node this is how you keep a runaway job from hurting everyone
else. The AI sees the active budget via `sys_daemon` and is told to
respect and cite it before launching anything heavy.

---

## When you walk away

This is the case the daemon is built for: you kick off a long job, close
the laptop, and come back tomorrow — or the shared node reboots overnight,
or your SLURM allocation gets preempted at 3am. The daemon is designed so
that **nothing you started silently disappears** and the AI knows exactly
how to pick the work back up.

What actually happens, step by step:

1. **The job outlives the chat.** Because the daemon owns the process —
   not your IDE's MCP session — closing the chat (or losing the
   connection) doesn't kill the run. It keeps going, journaling as it does.
2. **The daemon dies anyway.** If the daemon itself is taken down
   mid-run — the box reboots, the node is preempted, someone `kill`s it —
   the run was non-terminal when its last status was persisted.
3. **Rehydrate on the next start.** The next time the daemon starts, it
   reads the run journal, finds any run whose last persisted status was
   non-terminal, and rewrites that manifest as **`INTERRUPTED`** — with a
   status transition recorded, so the timeline shows exactly when it
   stalled. Rehydration is best-effort and never blocks startup.
4. **You get told.** The daemon emits a `runs_interrupted` notification on
   that same start — delivered via your `notify_command` if set, otherwise
   waiting in the outbox (`research-os daemon notifications`). You learn
   the work stopped without having to go looking.
5. **The AI orients to it.** When the AI next calls `sys_daemon`, the
   daemon's *orient* logic surfaces interrupted runs **as a high-priority
   recommended next action**, `resume_interrupted`: "*N run(s) were
   interrupted (the daemon stopped mid-run — e.g. the machine rebooted
   while you were away); their work did not complete and may have left
   partial output.*" The recommended move is to inspect them and re-run
   the affected step so it completes cleanly, **before** building anything
   on a partial result.

Inspect and resume manually any time:

```bash
research-os daemon runs                 # interrupted runs show status=interrupted
research-os daemon logs <run_id>        # what it managed to produce before it stalled
# then re-run the affected step (the AI does this for you on resume_interrupted)
```

The point of the whole flow is that a partial result can't quietly become
the foundation of a paper. An interrupted run is *louder* than a failed
one in the orient ordering — it's the first run-state the AI is told
about — precisely because a half-finished job that *looks* done is the
most dangerous thing a returning researcher can build on.

---

## Shared servers & HPC

The daemon's design assumptions are a shared login node, not a personal
laptop: no Docker for the daemon itself, a conda environment, other
people's jobs on the same box, and a scheduler in front of the real
compute. Everything above is built to behave well there.

**Stand it up in one command.** On a no-Docker conda node with no systemd,
`research-os daemon setup` does the awkward parts for you — it picks a
FREE port (so your daemon doesn't collide with another user's or another
project's on the same box), resolves the absolute `research-os` path
inside your conda env (the bare command isn't on PATH once a process
detaches from the env), and prints the exact `nohup` line to launch it
detached:

```bash
conda activate research-os
research-os daemon setup            # report: free port + conda + the launch line
research-os daemon setup --start    # ...or just start it in the background now
# later:
research-os daemon stop             # graceful, per-project
```

`research-os daemon start --background` is the same detached launch if you
already know your port. Both log to `.os_state/daemon.log`, record the pid
in the per-project descriptor, and survive logout. Two users (or two
projects) on one node each get their own daemon on their own port —
nothing is shared.

**Tell Research OS it's shared.** Set this once and the whole system
shifts to shared-node behaviour — long work gets backgrounded instead of
blocking, and the AI is told to respect the resource budget before
launching anything heavy:

```yaml
# inputs/researcher_config.yaml
runtime:
  shared_server: true
```

**No Docker required for the daemon.** The daemon and the whole stack
install and run from a plain conda env; there is no container build step.
Isolation comes from `rlimit`s + the command allowlist + (where the host
supports it) namespaces / cgroups — not containers. `GET /v1/sandbox`
reports the strongest isolation tier this host actually supports, so a
caller knows the bounding before submitting work. (Containers are still
available as a *runtime for your jobs* via `daemon docker` — see above —
they're just not required to run the daemon.)

**Hand heavy compute to the scheduler.** Research OS ships adapters for
the cluster tools you already run — detected and used automatically when
present:

- **SLURM** — `research-os daemon submit "<cmd>"` (or `tool_slurm_submit`)
  submits with full provenance and polls to completion; re-attaches by
  recorded scheduler job id after a restart.
- **Snakemake / Nextflow** — detected as workflow run-kinds; DAG preview
  via `GET /v1/workflows`; one journal entry per pipeline with per-rule /
  per-process sub-runs.

**Disk hygiene on a shared filesystem.** Runs are content-addressed and
artifact hashes are recorded, so re-running identical work doesn't
duplicate outputs. The resource budget's `file_size_mb` (`RLIMIT_FSIZE`)
caps how large any single run's output can grow — a real ceiling against a
runaway job filling a shared scratch volume. Keep `inputs/raw_data/` and
`inputs/literature/` immutable (the server enforces this); large derived
artefacts live under `workspace/` and `.os_state/`, which are yours to
prune between studies.

---

## Other subcommands

```bash
research-os daemon domain        # detected research field + field-aware defaults
```

The pre-v5 **gateway** (`daemon gateway`) OpenAI-compatible chat surface was
removed. Use MCP stdio for AI-client connections, and use the daemon's status,
execution, run, consent, freshness, and notification commands for the optional
background kernel.
---

## Mental model

| Layer | Who | Does |
|---|---|---|
| You | the researcher | drop files in `inputs/`, talk in natural language, **approve** gated actions |
| The AI | your IDE's model | plans, reasons, calls tools, requests approval |
| The MCP server | in-process | executes + records every research action |
| The daemon | optional process | runs long work (native / container / scheduler), tracks provenance, **enforces** hard gates, notifies you, **recovers interrupted runs** |

The daemon never replaces the MCP server — it sits alongside it as the
part that persists, executes in the background, and holds the authority
the AI isn't allowed to hold itself. Start it when a project is big or
long-lived enough to want that; skip it for quick work.
