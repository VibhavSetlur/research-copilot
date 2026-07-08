<p align="center">
  <img src="assets/logo.svg" alt="Research OS — grounded · cited · auditable" width="520">
</p>

<h1 align="center">Research OS</h1>

<p align="center">
  <a href="https://pypi.org/project/research-os/"><img src="https://img.shields.io/pypi/v/research-os?color=orange&label=pypi&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://pypi.org/project/research-os/"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT"></a>
  <a href="https://github.com/VibhavSetlur/Research-OS/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/VibhavSetlur/Research-OS/test.yml?branch=main&label=tests" alt="tests"></a>
</p>

<p align="center">
  <strong>Talk to your AI in plain English. Get publication-grade research back.</strong><br>
  No hallucinated citations. No fabricated numbers. Every figure traceable to the script that made it.
</p>

<p align="center">
  <a href="docs/START.md">Quick start</a> ·
  <a href="docs/PROMPTING.md">How to ask</a> ·
  <a href="docs/USE_CASES.md">What you can ask for</a> ·
  <a href="docs/SCENARIOS.md">Worked examples</a> ·
  <a href="docs/RESEARCHER_GUIDE.md">Full guide</a> ·
  <a href="docs/FAQ.md">FAQ</a>
</p>

---

## 30-second version

```bash
pip install research-os
mkdir thesis-chapter-3 && cd thesis-chapter-3
research-os init .                # scaffold THIS folder, ~20 seconds
```

Open the folder in Claude Code (or Cursor, or any MCP-capable AI IDE) and talk:

> **You:** I have a CSV of 2,400 patients at `~/data/cohort.csv`. I want to know whether the new drug lowers 30-day readmission, controlling for age and comorbidity. Hypothesis: it does, and the effect is bigger for older patients.

> **AI:** *Captures your question, domain, and both hypotheses; profiles the CSV; surfaces current literature; proposes a baseline EDA + a logistic regression with an age interaction; asks you to confirm before running anything.*

From there: `run the baseline EDA` → `fit the model` → `draft the results section` → `is this ready to submit?`. Every figure lands with a caption and the script that made it; every citation is verified; every number in the draft traces back to a real file on disk.

That's the whole idea. The rest of this page explains why it matters.

### Three things to do next

1. **See a real project, start to finish.** [**SCENARIOS.md**](docs/SCENARIOS.md)
   walks two complete projects — a quick one, and a deep PI-level program that
   shows how you actually interact with Research OS turn by turn (what the
   researcher types, what they see in their folder, and what the AI does at each
   step). **This is the fastest way to understand how to work with it.**
2. **Set it up the robust way, not just the fast way.** A few minutes of proper
   onboarding — the AI scans your inputs, frames the question, grounds in real
   literature, and wires exactly one IDE — pays off across the whole project.
   The [**setup prompt**](docs/SETUP_PROMPT.md) is one copy-paste block that
   walks your AI through it in order.
3. **Make it self-improving.** Pair Research OS with the
   [**Hermes agent layer**](#the-strongest-pairing-research-os--a-self-improving-agent)
   for memory across projects, reusable skills, and autonomous long runs.

---

## The problem it solves

AI coding assistants are fast, and they will cheerfully lie to you. Not maliciously — they pattern-match. Ask for a literature review and you'll get plausible citations to papers that don't exist. Ask for a results section and you'll get confident p-values that were never computed. Ask a follow-up next week and last week's decisions are gone.

For throwaway code, fine. For research that ends up in a thesis, a grant, or a paper, those failures are career-damaging — and they're invisible until a reviewer (or a retraction) finds them.

Research OS is an **MCP server that sits between your AI and your project** and refuses to let those four things happen:

| The failure mode | What Research OS does instead |
|---|---|
| **Invented citations** | Every reference is checked against Crossref / Semantic Scholar / PubMed / arXiv before it lands in a draft. Can't verify it? It's dropped, not quietly kept. |
| **Invented numbers** | Every quantitative claim in your write-up must point at a real file in `workspace/`. If a number isn't grounded in an artifact, synthesis blocks. |
| **400-line unreviewable scripts** | Work is split into small, content-hash-cached steps. Change one input; only the affected parts re-run. You can actually read what ran. |
| **Lost context** | Decisions, hypotheses, dead-ends, and draft revisions are written down as you go. Tomorrow's chat resumes exactly where today's ended. |

It works with the AI tools you already use — **Claude Code, Cursor, Claude Desktop, Antigravity, VS Code, Windsurf, OpenCode, Continue, Aider**. One install, one wizard, and the assistant you already trust does work that's traceable, grounded, and reproducible — the rigor you'd need *before* you submit, not a guarantee a reviewer will accept it.

---

## What working with it actually feels like

No commands to memorize, no DSL to learn. You describe what you want; the AI loads the right protocol and walks it.

**Starting** — you don't even need to touch a file:

> "Here's my project: does sleep duration predict exam scores in this dataset? Data's at `~/study/students.csv`. I think more sleep helps, more so for younger students."

The AI records your question + hypotheses, profiles the data, surfaces relevant prior work, and asks you to confirm before any analysis starts. (Prefer to drop files in `inputs/` first? That works too — same result.)

**Doing the work:**

> "run a baseline EDA"

You get `workspace/01_baseline_eda/` — readable scripts, figures with real captions, tables, and a written conclusion that links back to your hypotheses. Numbered, cached, re-runnable.

> "compare logistic regression against gradient boosting"

A real head-to-head: same split, same metrics, paired significance test, and a stated winner — not a hand-wavy "both have tradeoffs."

**Writing it up:**

> "draft the discussion"

A discussion that cites *your* results. Every citation verified, every figure and number traceable.

> "make me a poster for the lab meeting Thursday"

The AI assembles the poster's **structure** — which results to feature, the narrative arc, what each panel is for — grounded in your real findings, for you to render. Research OS gives you structure tailored to your audience, not a fixed template.

**Shipping it:**

> "is this ready to submit?"

A GREEN / YELLOW / RED verdict with a punch list — every check a journal will run, before they run it.

> "dockerize this step so it runs on the cluster"

The AI pins that step's exact packages and writes a step-scoped Dockerfile *in the step's own folder* — the scripts, data, and pinned environment travel together, so the one step rebuilds and runs anywhere, not just the whole project.

> "going to lunch, pick up tomorrow"

State, plan, hypotheses, dead-ends, and drafts all persist. Tomorrow's session opens exactly where you left off.

→ Full catalogue of what to say: **[USE_CASES.md](docs/USE_CASES.md)** · How to word a request for a specific outcome (and what happens behind the scenes): **[PROMPTING.md](docs/PROMPTING.md)** · Two worked projects end to end — a basic one and a deep PI-level program touching every capability: **[SCENARIOS.md](docs/SCENARIOS.md)**

---

## Three ways to work (set once, at init)

The wizard's first question — *"What are you building?"* — picks a **workspace mode** that reshapes the scaffold and how the AI behaves:

- **analysis** *(default)* — data → results → paper. Numbered experiment steps; "done" means grounded figures + conclusions.
- **tool_build** — you're building software (a CLI, a library, a pipeline). Research OS governs the build from above (spec → implement → test → benchmark) while the tool lives in its own git repo; "done" means **tests + build + eval pass**, not figures. → [docs/TOOL_BUILDER.md](docs/TOOL_BUILDER.md)
- **exploration** — scratch-first. Poke at the data with light gates; promote a probe to a real step only when it earns it.

Three more modes cover bigger shapes — **hybrid** (build a tool *and* use it on data in one project), **notebook** (Jupyter is the unit of work), and **multi_study** (a program of sub-studies sharing a codebook). Set the mode at init (`research-os init --workspace-mode <mode>`) or change it later in `inputs/researcher_config.yaml`.

---

## What you actually see on disk

A clean three-folder workspace. You only ever touch one of them.

```
thesis-chapter-3/
│
├── inputs/                 ← YOU own this (the AI reads, never overwrites)
│   ├── raw_data/             your data — CSV, Parquet, FASTQ, NIfTI, …
│   ├── literature/           PDFs of papers the project draws on
│   ├── context/              PI emails, lab notes, prior drafts
│   └── researcher_config.yaml  one optional file that tunes AI behavior
│
├── workspace/              ← the AI works here (you read; it writes)
│   ├── 01_baseline_eda/      one analysis step per numbered folder
│   │   ├── scripts/            code you can read + re-run
│   │   ├── outputs/            figures (with captions), tables, reports
│   │   └── conclusions.md      findings + interpretation, tied to hypotheses
│   ├── methods.md            project-wide methods narrative (append-only)
│   ├── analysis.md           decision log + dead-ends + rationale
│   ├── citations.md          verified citations only
│   └── logs/                 every audit pass + every gate override
│
└── synthesis/              ← deliverables land here (only when you ask)
    ├── deliverables/               structured outlines for paper / poster / slides
    ├── dashboard/                  a public-facing dashboard's structure
    └── figures/                    curated focal figures + captions
```

One principle holds it together: **you own `inputs/`, the AI owns the rest, and nothing exists until you ask for it.** A fresh project isn't pre-cluttered with empty folders — `workspace/01_*` appears the first time you run a step. And Research OS gives you **structure, not design**: deliverables are content-grounded outlines tailored to your audience, for you and your AI to render — not a fixed template.

→ Deeper tour: **[RESEARCHER_GUIDE.md](docs/RESEARCHER_GUIDE.md)** · Exact layout per mode: **[PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md)**

---

## Install & run

```bash
# 1. Install once — the same binary serves every project you scaffold.
pip install research-os

# 2. Scaffold a project (arrow-key wizard).
mkdir my-project && cd my-project
research-os init

# 3. (Optional) confirm everything's healthy.
research-os doctor

# 4. Open the folder in your AI IDE and talk. The MCP server auto-launches.
#    > here's my project: I want to know if X drives Y; data's at <path>
#    > what should I do next?
#    > draft the results section
#    > is this ready to submit?
```

The full experience ships in the base install — no extras to remember. A handful of features that need their own system runtime (the enforcement daemon, R, Julia) are opt-in; see [SETUP.md](docs/SETUP.md).

### Prefer to let your AI set it up? Use the one setup prompt

There's a single, copy-paste **[setup prompt](docs/SETUP_PROMPT.md)** that walks
your AI through the whole thing — install, wire **only your IDE** (not all of
them), start the daemon, **test that it actually works**, and remind you to
restart (the one step people miss) — then onboard your project before any
analysis. It's a fill-in-the-gap template: you only have to provide a project
name, your goal, and a free-text "context block" where you dump your thoughts;
leave the rest blank and the AI asks or picks sensible defaults.

→ **Copy it from [docs/SETUP_PROMPT.md](docs/SETUP_PROMPT.md)** and paste it to
your AI with the project folder open.

Why the restart matters: an IDE/agent loads its MCP servers when the session starts, so the Research OS tools only appear **after** you reopen the project. Pointing your AI at Research OS without this almost always ends with it improvising instead of using the real tools — which is exactly why the prompt makes the AI stop, wait for your restart, and self-test before doing anything.

→ Full walkthrough: **[START.md](docs/START.md)** · Per-IDE wiring: **[SETUP.md](docs/SETUP.md)** · CLI reference: **[CLI.md](docs/CLI.md)**

---

## Two layers, and why they matter

**1. The reasoning core (always on).** The MCP server every command above talks to. Three tool namespaces — `sys_*` (workspace / files / state), `tool_*` (research work), `mem_*` (append-only memory) — plus a deep library of protocols the AI routes to via `tool_route`. The core is *reactive*: it runs in your IDE, responds to each prompt, and never blocks. Most projects need nothing more.

**2. The enforcement daemon (optional).** For big or long-lived projects, a local daemon adds what a reactive server can't:

- **Background runs** with a durable journal, provenance, and lineage — long jobs don't freeze the chat.
- **Freshness gates** — it won't let the AI ship a result built on data that changed underneath it.
- **Hard, human-approved gates** — the AI can't self-approve past a real checkpoint.
- **A resource budget** the machine actually enforces, and completion notifications.

The core behaves *identically* with or without the daemon — it only ever *adds* enforcement, never changes the tools. → [DAEMON.md](docs/DAEMON.md) · [ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## The strongest pairing: Research OS + a self-improving agent

Research OS is the **rigor substrate** — it governs *how to reason* and *what to
verify*. The AI on top is the **brain**. The pairing is strongest when that AI
layer can **learn your work and carry skills across sessions**, like
[Hermes Agent](https://hermes-agent.nousresearch.com). Then three layers compose:

- **Research OS** — research done right: protocols, gates, provenance, the
  numbered-step structure.
- **Skills** — your field's *how-to*. Research OS actively **pulls the skills a
  project needs** from three sources and loads them before you start, instead of
  relying on the model's memory:
  1. **Hermes skills** you've built or installed (`~/.hermes/skills/`),
  2. the **K-Dense scientific-agent-skills** library (community MIT science
     skills — install with `research-os skills add-science-pack`),
  3. any **native Agent Skills** in the open SKILL.md standard.
  `sys_boot.recommended_skills` tells the AI which ones match this project on the
  first turn.
- **Self-improvement** — Hermes learns *your* way over time. Lessons distilled in
  one project are promoted into loadable skill cards that surface in the next.

```bash
research-os hermes add          # wire Research OS into Hermes
research-os skills add-science-pack   # install the K-Dense science skill library
research-os skills list-science       # see what's available
```

The `guidance/agent_setup` protocol walks the whole setup, and the
[setup prompt](docs/SETUP_PROMPT.md)'s step 9 has the AI pull the right skills up
front. It works with any AI — Claude Code, Cursor, a bare API — but Hermes is the
closest fit because the skill + memory + autonomous-run layer is exactly what a
long research program needs.

---

## Why trust the output

| The worry | The guarantee |
|---|---|
| AI invented a citation | Verified against four databases; unverifiable ones dropped. |
| AI invented a number | Every claim traces to a real `workspace/` file or synthesis blocks. |
| Script too big to review | Atomic, content-hash-cached sub-steps; edit one, re-run only what's affected. |
| Context lost between sessions | Decisions / hypotheses / dead-ends / drafts persist on disk. |
| Figure drifts from its caption | Each figure ships with caption + plain-English summary + provenance sidecar (script, seed, library versions). |
| Pre-registered plan silently changed | The analysis plan is content-hashed; every deviation surfaces at synthesis. |
| Negative results vanish | First-class workflow for refuted / underpowered / abandoned findings. |
| Pre-submission anxiety | A final check runs every gate a journal will — verdict + punch list. |

→ Full release history: **[CHANGELOG.md](CHANGELOG.md)**

---

## Documentation

| If you're… | Read this |
|---|---|
| **New here** | [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) — how real projects unfold + why your results hold up (provenance, accuracy, organization) · then [docs/START.md](docs/START.md) — install + first project |
| **Setting up with your AI** | [docs/SETUP_PROMPT.md](docs/SETUP_PROMPT.md) — one copy-paste, fill-in-the-gap prompt that drives your AI through the whole setup + onboarding |
| **Looking for an example** | [docs/SCENARIOS.md](docs/SCENARIOS.md) — two worked projects (basic + deep PI-level) · [docs/USE_CASES.md](docs/USE_CASES.md) — what to say for what you want |
| **Wording a request** | [docs/PROMPTING.md](docs/PROMPTING.md) — how to phrase prompts to get a specific outcome (dockerize a step, pull papers, sample data, a no-leak dashboard) + what happens behind the scenes |
| **Going deep** | [docs/RESEARCHER_GUIDE.md](docs/RESEARCHER_GUIDE.md) — the full workflow guide |
| **Wiring an IDE** | [docs/SETUP.md](docs/SETUP.md) — Claude Code, Cursor, VS Code, etc. |
| **Stuck** | [docs/FAQ.md](docs/FAQ.md) — common questions |
| **Building a tool, not analysing data** | [docs/TOOL_BUILDER.md](docs/TOOL_BUILDER.md) — tool_build mode end to end |
| **Curious about a protocol** | [docs/PROTOCOLS.md](docs/PROTOCOLS.md) — every workflow with triggers + quality bars |
| **Looking up a tool** | [docs/TOOLS.md](docs/TOOLS.md) — every MCP tool with examples |
| **Understanding how it's built** | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the core, the daemon, the seam between them |
| **Running long / enforced jobs** | [docs/DAEMON.md](docs/DAEMON.md) — the optional enforcement daemon |
| **Sharing a finished project** | [docs/SHARING.md](docs/SHARING.md) — share-safe zip + GitHub paths |
| **Contributing a protocol** | [docs/PROTOCOL_DOCTRINE.md](docs/PROTOCOL_DOCTRINE.md) — the scaffold-not-script principle |
| **Driving the AI side** | [docs/AI_GUIDE.md](docs/AI_GUIDE.md) — what the AI itself reads |

Doc index: **[docs/README.md](docs/README.md)**

---

## Tune how the AI behaves

One optional file — `inputs/researcher_config.yaml` — controls everything. Every field has a sensible default. The two that matter most:

```yaml
interaction:
  quality_gate_policy: enforce          # enforce | allow_override | warn_only
  ambiguity_posture: ask_when_uncertain # vs take_best_default
```

You can change these mid-session just by telling the AI ("switch to autopilot", "stop asking, use your best judgment").

→ Full reference: **[RESEARCHER_GUIDE.md § config](docs/RESEARCHER_GUIDE.md#8-configuration-inputsresearcher_configyaml)**

---

## Contributing

Issues and PRs welcome.

- **Found a bug?** → [Open an issue](https://github.com/VibhavSetlur/Research-OS/issues/new?template=bug_report.md)
- **Want a feature?** → [Request one](https://github.com/VibhavSetlur/Research-OS/issues/new?template=feature_request.md)
- **Code contribution?** → [CONTRIBUTING.md](CONTRIBUTING.md) covers the workflow, branch model, and test conventions.
- **Have a question?** → [GitHub Discussions](https://github.com/VibhavSetlur/Research-OS/discussions)
- **Security report?** → [SECURITY.md](SECURITY.md)

---

## License

[MIT](LICENSE) · No telemetry · Research OS never touches your LLM provider keys (your AI IDE owns model access).

If you use Research OS in published work, citation metadata lives in [CITATION.cff](CITATION.cff).
