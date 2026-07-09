# Start here

Everything you need to be productive with Research OS — install, your
first project, and the copy-paste prompts you'll actually use. Read top
to bottom (~15 minutes), or jump to the section you need.

Research OS is for **researchers**, not developers. You don't write
config or memorize commands — you scaffold one folder, open it in your AI
IDE, and talk in plain English. The system gives your project
**structure**: it onboards you, routes your words to the right protocol,
runs real computation through versioned steps, and grounds every number
and citation it produces.

---

## Quickstart — five steps that matter

```bash
# 1. Install once, globally — one server serves every project
pip install research-os

# 2. Make the project folder and scaffold it (the dot = "here")
mkdir aspirin-rct && cd aspirin-rct
research-os init .

# 3. RESTART your AI IDE (or reload the window) so it loads the new tools

# 4. Confirm it's healthy
research-os doctor

# 5. Open the folder in your AI IDE and start with a real intake message
```

A useful first message is not a command; it is a short project brief. For
example:

> I'm starting an analysis project on low-dose aspirin and 30-day cardiac
> events. The trial export is currently at `~/secure_exports/aspirin_trial.csv`;
> I have not moved it into `inputs/raw_data/` yet because I'm unsure whether the
> de-identified export includes the site column we need. The SAP draft is in
> `inputs/context/sap_v3_notes.md`, and two older figures from a failed notebook
> are in `inputs/context/old_outputs/`.
>
> My immediate goal is a Thursday lab-meeting figure, not a final manuscript. I
> tried a quick logistic regression last week, but the event rate is low and the
> PI asked whether we need exact methods or a Bayesian model. Please verify the
> environment and file paths, onboard the project, profile the data, check whether
> the old notebook is reusable, and ask me before running any analysis that writes
> outputs or takes more than a few minutes.

Five details carry the whole experience. Get these right and the rest is
just talking:

1. **`research-os init .`** — the dot scaffolds the folder you're
   *already in*. `research-os init my-project` creates a *nested*
   `my-project/` inside the current folder, which is rarely what you
   want. When in doubt, `cd` into the folder first and run `init .`.
2. **Restart the IDE before you expect tools.** The MCP server only
   loads on a fresh IDE session. If you had the IDE open during `init`,
   the Research OS tools won't appear until you fully restart it or
   reload the window.
3. **Run the self-test.** `research-os doctor` confirms install +
   workspace health before you sink time into a session.
4. **Onboard before you analyze.** Don't jump straight to "fit a model."
   Let the AI scan your inputs, capture the question + hypotheses, do a
   literature pass, and ground the framing first (see
   [Onboard before you analyze](#onboard-before-you-analyze)).
5. **Talk, don't command.** The AI translates plain English into the
   right protocol via `tool_route`. You never call MCP tools by hand.

The rest of this guide unpacks each step.

---

## Install (60 s)

```bash
pip install research-os
```

Extras: `all` (everything Python — recommended), `ci` (lean, used by
CI), or a subset of `web` / `literature` / `viz` / `audit` / `ml` /
`notebook`.

**Research OS is global.** Install once; the same `research-os` binary
serves every project you scaffold.

Verify:

```bash
research-os --help
# Subcommands: init · ide · mcp · hermes · skills · route · api-key
#              start · daemon · doctor · refresh · completion
```

If you see `research-os: command not found`, add `~/.local/bin` (or your
virtualenv's `bin/`) to your `PATH`. Need help with Python / pip /
virtualenvs / conda? See [SETUP.md](SETUP.md).

You do **not** need an LLM API key. Your AI IDE owns model access;
Research OS sits behind it as an MCP server.

---

## Scaffold your first project (15 s)

```bash
mkdir my-project && cd my-project
research-os init .                 # scaffold the folder you're in
# research-os init . --yes         # non-interactive (CI / scripts)
```

> **Use the dot.** `research-os init .` scaffolds the current folder.
> `research-os init my-project` *nests* a new folder inside it — a
> common first-time surprise. `cd` in first, then `init .`.

`init` is the only per-project command. Its first question — **"What are
you building?"** — sets the *workspace mode* (next section). It then
collects: project name, optional domain + research question, which AI
IDEs to wire, and whether to run a smoke check. Pass any of
`--workspace-mode / --name / --domain / --question / --ide` to pre-fill
an answer and skip that step.

It drops:

- `AGENTS.md` — the AI's operating manual (every supported IDE reads it)
- `inputs/{raw_data, literature, context}/` — where **you** drop files
- `workspace/`, `synthesis/`, `docs/`, `.os_state/` — AI workspace + outputs
- Pre-wired MCP configs for **Claude Code, OpenCode, Antigravity, Cursor,
  Claude Desktop, VS Code, Windsurf, Continue, Aider**

### Then RESTART your IDE

The MCP server only loads on a fresh IDE session. **If your IDE was open
during `init`, fully restart it (or reload the window) now** — otherwise
the Research OS tools simply won't appear in the chat and the AI will act
like it's never heard of them. This one step trips up most first-timers.

---

## Pick a workspace mode

The first wizard question — *"What are you building?"* — sets a
**workspace mode** that shapes the scaffold and how the AI works. Six
modes exist; most people want **analysis**.

| Pick this if you're… | Mode | What changes |
|---|---|---|
| Turning data into results + a write-up | **analysis** *(default)* | Numbered experiment steps under `workspace/NN_*`; "done" = grounded figures + conclusions. |
| Building software (CLI, library, service) | **tool_build** | Governance layer (`spec/`, `decisions/`, `eval/`) above an inner git repo; "done" = tests + build + eval pass. → [TOOL_BUILDER.md](TOOL_BUILDER.md) |
| Poking around with no committed direction | **exploration** | Scratch-first (`workspace/scratch/`), light gates; promote a probe to a real step only when it earns it. |
| Working notebook-first (Jupyter is the unit of work) | **notebook** | Notebooks are first-class; run / reproduce / promote / synthesize from them. |
| Building a tool *and* using it on data in one project | **hybrid** | The analysis ↔ build pivot in one workspace. |
| Running several related sub-studies under one umbrella | **multi_study** | A shared commons plus per-study registration. |

Set it without the wizard via `research-os init . --workspace-mode <mode>`,
or change it later in `inputs/researcher_config.yaml` (`workspace.mode`).
Not sure? Pick **analysis** — you can switch (the AI plans the
transition, then applies it additively, preserving your work).

---

## Confirm install + workspace health (the self-test)

Before you start a real session, run the doctor. It's your one-command
"is everything wired right?" self-test.

```bash
research-os doctor                # full report (install + workspace)
research-os doctor --verbose      # show fix hints for passing checks too
research-os doctor --json         # machine-readable
research-os doctor --workspace-only   # skip install checks (CI use)
```

The doctor checks python version, conda env, version consistency, pack
registration, embeddings freshness, typst / chromium on PATH, **IDE MCP
wiring**, orphan figures, unresolved gates, disk usage, and git
cleanliness. It exits `0` (all pass), `1` (warnings only), or `2`
(failures). If `doctor` says the IDE is wired but the tools still don't
show up in chat — that's the restart step you skipped above.

---

## Open your AI IDE on the project and talk

The MCP server auto-launches per IDE-project. After your restart, the
status bar / MCP panel should show **`research-os` connected**.

Open the chat and say what you want, in plain English. Aim for enough context
that a careful collaborator could avoid obvious mistakes:

> I'm not ready for modeling yet. Please onboard this project and verify what is
> actually on disk. The main question is whether the scheduling policy reduced
> 30-day ICU readmission, but the policy date may differ by unit and I need that
> checked against the data dictionary before we call it difference-in-differences.
> The CSV is still outside the project at `~/exports/icu_readmission.csv`; copy it
> only if it is small enough, otherwise propose a symlink and record provenance.
> I also need a short explanation of the first statistical choice because my
> advisor will ask why we did not start with a simple before/after comparison.

Then iterate naturally:

> Actually, don't use all units yet. Start with adult medical ICU only, and tell
> me if that makes the sample too small before running the baseline EDA.

You never call MCP tools directly. The AI routes your words to a protocol
via `tool_route`. If it picks the wrong one, say *"actually I meant X"*
and it re-routes without reloading the workspace.

---

## Onboard before you analyze

The single biggest difference between a robust project and a messy one is
**onboarding first**. When you open a fresh project, the AI runs
`session_boot` then `project_startup` — and it should do this *before*
opening any numbered analysis step. Onboarding walks through, in order:

1. **Scan `inputs/`** — `raw_data/`, `literature/`, `context/`.
2. **Fill the intake** — `tool_intake_autofill` reads your files *or*
   pulls the question + hypotheses straight from what you typed in chat;
   `tool_intake_freshness` flags anything stale.
3. **Bring external data in with provenance** — copy or symlink (it
   reasons about which for large/shared data) and records the source path
   + hash.
4. **Profile the data** — `tool_data` reports rows, columns, types,
   missingness, and anything odd.
5. **Snapshot the environment** — `sys_env` captures your toolchain so
   results are reproducible.
6. **Do a literature pass — mandatory.** Via `tool_search` /
   `tool_literature_search_and_save`, so your framing is grounded in the
   field, not invented.
7. **Ground the framing** — `tool_ground` ties the question + hypotheses
   to what's actually on disk before any experiment runs.

You don't recite this list — you say *"onboard me"* or *"fill out the
intake"* and the AI walks it. The payoff: by the time you run your first
real step, the question is captured, the data is profiled and
provenanced, and the literature is in hand.

**The coaching posture.** Research OS is a careful collaborator, not an
eager autocomplete:

- It **looks before it leaps** — reads your files and proposes a plan,
  and asks before creating experiments or final outputs.
- It **won't make things up** — every citation is verified against real
  databases; every number must trace to a real file it produced. If it
  can't, it says so.
- It **explains on request** — *"why that test?"*, *"teach me ANCOVA
  before I use it."*
- It **remembers** — come back tomorrow and say *"pick up where we left
  off."*

---

## The Hermes layer

Research OS gives the AI **structure and tools**. The optional **Hermes
layer** gives it **know-how and stamina** — reusable skills, memory
across projects, and the ability to drive long autonomous runs. You don't
need Hermes to use Research OS, but it makes the AI noticeably sharper in
your field.

**Skills** are on-demand know-how documents in the open Agent Skills
standard — your field's actual methods and validated parameters, loaded
only when relevant. Research OS draws skills from three sources through
one index:

| Source | What it is | How to get it |
|---|---|---|
| **Hermes skills** | The agent's own skill library at `~/.hermes/skills` | Ships with Hermes |
| **K-Dense science pack** | 140 MIT-licensed deep-science skills (bulk-rnaseq, rdkit, experimental-design, literature-review, …) | `research-os skills add-science-pack` |
| **Native Agent Skills** | Any external Agent-Skills library your IDE points at | Point your IDE at the `skills/` dir |

```bash
research-os skills add-science-pack       # clone + wire the K-Dense pack
research-os skills list-science           # see the domain → skill map
```

**Autonomous skill retrieval.** You don't pick skills by hand. On a fresh
project, `sys_boot.recommended_skills` matches your domain + workspace
mode and surfaces the skills that fit (e.g. genomics → biopython, gget,
bulk-rnaseq). The AI loads them *before* starting, so it works with your
field's methods instead of guessing. The system also learns — it distills
lessons from your projects into new skills and carries the durable ones
forward.

If you're running Hermes, it can also orchestrate the long-haul loops:
plan deeply, execute toward a goal mostly hands-off, pull relevant skills
each cycle, and notify you at decision points. Docs:
<https://hermes-agent.nousresearch.com>. Wire it with `research-os hermes add`.

---

## Your first ten minutes (a real walkthrough)

You've got a clinical-trial export, a half-formed question, and a deadline.
Here's a realistic first arc — the words you type are in **bold**. Notice that
most of the value comes before the first model runs.

1. **Scaffold and open.**

   ```bash
   mkdir aspirin-rct && cd aspirin-rct
   research-os init .        # pick "analysis" mode, your IDE, defaults
   ```

   Restart the IDE, then open `aspirin-rct/`. The MCP panel shows
   **`research-os` connected**.

2. **Onboard with context, not a one-liner.**

   > **I'm analyzing a de-identified trial export for a Thursday lab meeting. The
   > question is whether low-dose aspirin reduces 30-day cardiac events versus
   > placebo, but this is not submission-ready yet. The CSV is at
   > `~/secure_exports/aspirin_trial.csv`; the SAP draft is in
   > `inputs/context/sap_v3_notes.md`; and an older notebook in
   > `inputs/context/old_aspirin_analysis.ipynb` produced inconsistent event
   > counts.**
   >
   > **Please verify the project setup and file paths, profile the data, check the
   > old notebook only for reusable QA logic, and tell me what you think the first
   > defensible analysis should be. Do not run the model or write final figures
   > until I confirm the plan. The PI is worried about the low event rate and will
   > ask why we chose the model.**

   The AI boots Research OS, records the question and constraints, checks the
   path, proposes copy vs symlink, snapshots the environment, profiles the CSV,
   and notices the old notebook counted events before excluding withdrawals. It
   asks a clarification rather than guessing: *"Should withdrawals before day 30
   be censored, excluded, or treated according to the SAP?"*

3. **Correct the scope.**

   > **Good catch. Use the SAP: withdrawals before day 30 are censored. Also, I
   > realized the Thursday audience is clinicians, so I need an interpretable
   > baseline table and an absolute-risk plot, not just model coefficients. Please
   > update the plan and tell me if the event count is too low for the adjusted
   > model before running anything heavy.**

   The AI updates the intake and analysis plan, checks event counts and missing
   covariates, searches current guidance on low-event binary outcomes, and records
   the model-choice rationale. If the plan passes preconditions, it asks for
   approval to open `workspace/01_baseline_eda/`.

4. **Run a narrow, reviewable first step.**

   > **Approved. Run baseline EDA and the event-count sanity checks only. Keep it
   > under a few minutes and show me the script before interpreting the output.**

   You get `workspace/01_baseline_eda/` — a readable script, summary table,
   missingness report, figure drafts with captions, and `conclusions.md` tying
   observations back to the question. The outputs carry provenance sidecars, and
   the AI flags anything too thin to support inference.

5. **Only then move to the analysis.**

   > **The EDA looks right. Fit the adjusted model from the SAP, but also produce
   > an absolute-risk figure for clinicians and log why we did not use the old
   > notebook's event definition.**

   The AI opens the next step, runs the model, records the decision, grounds every
   number in produced artifacts, and verifies citations. If a data file changes or
   an upstream step is stale, the staleness gate surfaces that before synthesis.

6. **Check before you share.**

   > **Before I send this to the PI, audit the claims, citations, and provenance.
   > Give me a GREEN/YELLOW/RED verdict and a short list of what still needs human
   > review.**

   You get a review verdict and a punch list: ungrounded claims, missing
   limitations, unresolved data questions, or stale outputs. You never trusted a
   number on faith; the loop is **context → verify → plan → ask → run → ground →
   audit**. Fuller examples across domains live in [SCENARIOS.md](SCENARIOS.md).

---

## Bring in your project — chat or files

**Fastest path:** just tell the AI what you're studying — no files
required. Say *"I want to know if X affects Y; data's a CSV at
`~/data.csv`; hypotheses: …"* and the AI captures it into the intake for
your approval.

**Prefer to stage files first?** Drop them in:

```bash
mv path/to/data.csv      inputs/raw_data/
mv path/to/paper.pdf     inputs/literature/
mv my_notes.md           inputs/context/
```

`inputs/raw_data/` and `inputs/literature/` are **source-of-truth** —
soft-guarded, so the AI overwrites them only with `force=true` plus your
OK. The rest of `inputs/` is AI-maintained. Only `.os_state/` is ever
hard-locked.

No data at all? That's fine — describe the project in chat, or stay in
pure consult mode (*"teach me about propensity scores before I use
them"*).

### When your project needs extra `inputs/` subfolders

The wizard creates `raw_data/`, `literature/`, `context/`. Some packs
expect more — pre-stage if you want, or just `mkdir` mid-session:

| You have… | Drop it here | Used by |
|---|---|---|
| A text corpus (novels, transcripts, sources) | `inputs/corpus/` OR `inputs/raw_data/<slug>/` | humanities distant/close reading |
| Hand-picked close-reading passages | `inputs/textual/passages/` | humanities close reading |
| Definitions / preliminaries for a theorem | `inputs/preliminaries.md` | theory_math proof strategy (hard prerequisite — blocks without it) |
| Source code under benchmark | `inputs/context/code/` | engineering `method_comparison` |
| Interview / survey instruments, IRB | `inputs/context/` | qualitative protocols, audit gates |

The immutability guarantee only applies to `raw_data/` and `literature/`.

---

## Using a small or medium AI? Set `model_profile` first

**The single most important knob if you're not on a frontier model.**
Open `inputs/researcher_config.yaml` and set:

```yaml
model_profile: "small"    # Claude Haiku 4.5, GPT-4o-mini, Gemini Flash, local
model_profile: "medium"   # default — Claude Sonnet, GPT-4o, Gemini Pro
model_profile: "large"    # Claude Opus, GPT-5/o-series, Gemini 3 Pro
```

Small models get 1 step/turn, summary-only protocol loads, and prefer
shortcut tools to keep context lean. If your AI runs out of context
mid-plan, drop a tier; if it hands off after every step, bump up. Full
table in [SETUP.md § 6](SETUP.md#pick-the-right-model_profile-for-your-ai).

---

## Long jobs and shared servers (the daemon, optional)

For overnight sweeps, big training runs, or anything that must survive
your IDE closing, start the **per-project daemon**:

```bash
research-os daemon setup            # one-time, in the project
research-os daemon start            # start it for this project
research-os daemon status           # is it running?

research-os daemon run -- python train.py --in data.csv   # durable run
research-os daemon docker myimg:1.0 -- python run.py       # in a container
research-os daemon submit job.sbatch --scheduler slurm     # to SLURM

research-os daemon runs             # durable run history
research-os daemon logs <run_id>    # one run's manifest + output
```

Every run is **journaled and provenanced** — recreatable, recoverable
after a reboot, and notifiable on completion. `daemon docker IMAGE -- CMD`
records the exact image digest so the run reproduces bit-for-bit. Without
a daemon everything still works over stdio; the daemon just adds durable
execution, recovery, and notifications. On a shared box, set
`runtime.shared_server: true` so the AI asks before allocating heavy
resources.

---

## Manage IDE wiring

```bash
research-os ide list                  # every supported IDE; marks what's wired
research-os ide add cursor            # wire Cursor only
research-os ide add windsurf aider    # wire several at once
research-os ide remove opencode       # un-wire OpenCode
research-os ide config-path cursor    # print where Cursor's MCP config lands
```

`research-os ide` walks up from CWD for `.os_state/`, so it works from
any subdirectory — no need to `cd` to the root.

---

## Cheatsheet

### CLI (twelve subcommands)

```bash
research-os init .                        # scaffold THIS folder (use the dot)
research-os init . --force                # re-scaffold (preserves data + config)
research-os init . --ide cursor,claude    # only those IDEs

research-os ide list / add / remove / config-path <ide>

research-os skills add-science-pack       # K-Dense 140-skill science pack
research-os skills list-science           # domain → skill map

research-os doctor                        # self-test: install + workspace health
research-os route "fit a survival model"  # preview which protocol the router picks
research-os refresh                       # re-sync template files after upgrading
research-os hermes add                    # wire the Hermes agent layer (optional)
research-os daemon start|stop|status|setup|run|docker|submit|runs|logs
research-os start                         # MCP server (IDE auto-launches it)
research-os completion bash               # shell-completion script
```

### Where files go

```
inputs/raw_data/      ← your data (source-of-truth; soft-guarded)
inputs/literature/    ← your PDFs (source-of-truth; soft-guarded)
inputs/context/       ← your notes / drafts / past reports
docs/                 ← research question, domain, glossary
workspace/            ← AI lives here; numbered experiment folders
workspace/scratch/    ← AI sandbox (gitignored)
synthesis/            ← final outputs (created only when you ask)
.os_state/            ← internal — do NOT edit by hand
```

### When something is wrong

| Symptom | Fix |
|---|---|
| Tools don't appear in chat | You skipped the **IDE restart** after `init` — restart / reload the window |
| AI seems lost | *"show me sys_help"* — it re-orients |
| Wrong protocol picked | *"actually I meant X"* — it re-routes |
| AI making bad calls | *"switch to manual mode"* |
| Workspace looks broken | *"fix the workspace"* — `tool_workspace_repair`, never deletes |
| Chat too long | *"hand off the session"* → fresh chat → *"pick up where we left off"* |
| Deleted by mistake | *"list checkpoints"* → *"rollback to <id>"* |
| Install / wiring uncertain | `research-os doctor` |

---

## What to read next

- [HOW_IT_WORKS.md](HOW_IT_WORKS.md) — how a real project unfolds and why
  results hold up (provenance, accuracy, organization).
- [USE_CASES.md](USE_CASES.md) — realistic scenario messages → which
  protocol / mode fires.
- [SCENARIOS.md](SCENARIOS.md) — two worked projects end to end (a basic one and a deep PI-level program).
- [RESEARCHER_GUIDE.md](RESEARCHER_GUIDE.md) — the full workflow guide.
- [TOOL_BUILDER.md](TOOL_BUILDER.md) — building software (tool_build mode).
- [SETUP.md](SETUP.md) — detailed install + per-IDE wiring.
- [FAQ.md](FAQ.md) — common questions.
- [PROTOCOLS.md](PROTOCOLS.md) · [TOOLS.md](TOOLS.md) — full catalogues.
- [AI_GUIDE.md](AI_GUIDE.md) — the operating manual for the AI driving
  Research OS.
