<p align="center">
  <img src="assets/logo.svg" alt="Research OS — grounded · cited · auditable" width="520">
</p>

<h1 align="center">Research OS</h1>

<p align="center">
  <a href="https://pypi.org/project/research-os/"><img src="https://img.shields.io/pypi/v/research-os?color=orange&label=pypi&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://pypi.org/project/research-os/"><img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="Python 3.11+"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-server-brightgreen.svg" alt="MCP server"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT"></a>
  <a href="https://github.com/VibhavSetlur/Research-OS/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/VibhavSetlur/Research-OS/test.yml?branch=main&label=tests" alt="tests"></a>
</p>

<p align="center">
  <strong>Typed protocols, durable provenance, and optional enforcement for AI-assisted research.</strong><br>
  Research OS calls no LLM, proxies no chat completions, and keeps model access in your own IDE or agent.
</p>

<p align="center">
  <a href="docs/START.md">Quick start</a> ·
  <a href="docs/PROMPTING.md">How to ask</a> ·
  <a href="docs/SCENARIOS.md">Worked examples</a> ·
  <a href="docs/RESEARCHER_GUIDE.md">Full guide</a> ·
  <a href="docs/ARCHITECTURE.md">Architecture</a> ·
  <a href="docs/FAQ.md">FAQ</a>
</p>

---

## Research is not a one-line prompt

Real researchers rarely arrive with "analyze my data." They arrive with an unfinished story: a question shaped by collaborators, files scattered across a laptop or cluster, earlier attempts that half-worked, deadline pressure, reviewer worries, and uncertainty about whether the next method is defensible.

Research OS is built for that reality. It is a **passive MCP tool server** and **research protocol scaffold** that helps your AI assistant turn messy research into verified structure: project intake, typed protocols, checked preconditions, provenance ledgers, staleness warnings, resource budgets, citations, and review gates. The assistant still reasons, writes, and decides with you; Research OS makes the work inspectable, rerunnable, and auditable.

A realistic first turn looks more like this:

> **Context:** I'm studying long-COVID symptom trajectories from a retrospective cohort of about 8,000 patients seen in our health system between 2020 and 2023. The PI wants a defensible analysis plan before we run anything because this may become a journal submission, and two clinicians need to understand the main result.
>
> **Data:** I have de-identified encounter data in `inputs/raw_data/encounters_2020_2023.csv` and lab values in `/scratch/lab_panel_20240115.parquet`. The data dictionary is in `inputs/context/data_dictionary_v2.md`. Dr. Chen did an earlier notebook in `inputs/context/chen_2023_preliminary.ipynb`, but it has hard-coded paths and I don't know whether the code was ever approved for this scope.
>
> **What failed:** My first merge failed on malformed lab timestamps, and a Cox model seemed to violate proportional hazards. I'm not sure whether readmission should be treated as a competing risk or censored.
>
> **Constraints:** I need a workshop figure by Thursday, can't run jobs longer than two hours on the shared cluster, and we cannot export row-level data. Please verify paths and data status first, then sketch a statistical plan and ask me what needs clarification before executing anything.

That message gives the AI enough context to route to the right protocols, check the workspace, ask a meaningful clarification, and record a plan before code runs.

---

## Quick start

```bash
pip install research-os
research-os init my-study
cd my-study
research-os doctor
```

Open the folder in Claude Code, Cursor, Claude Desktop, VS Code, Windsurf, OpenCode, Continue, Aider, or another MCP-capable client. Restart the IDE after `init` so it loads the MCP server, then begin with a project context message like the one above.

`research-os init` creates a simple workspace:

```text
my-study/
├── inputs/                  # you own this: data, literature, notes, config
│   ├── raw_data/
│   ├── literature/
│   ├── context/
│   └── researcher_config.yaml
├── workspace/               # the AI writes steps, scripts, outputs, logs
├── synthesis/               # deliverables when you ask for them
└── .os_state/               # Research OS state, ledgers, manifests, daemon records
```

The rule is: **you own `inputs/`; Research OS owns `.os_state/`; the AI writes work products into `workspace/` and `synthesis/` when you ask.** See [START.md](docs/START.md) and [PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md) for the guided tour.

---

## What Research OS helps the assistant do

For a realistic first message, Research OS gives the assistant a disciplined workflow:

1. **Boot and inspect state** — load config, previous runs, active plans, stale outputs, unresolved gates, and daemon status if present.
2. **Route the request** — map the researcher's words to a protocol scaffold and a small active tool surface.
3. **Verify the workspace** — confirm files exist, profile data before inference, record hashes, and surface missing documentation or stale inputs.
4. **Ask a useful clarification** — for example, whether missing onset dates should be imputed or handled as a sensitivity analysis.
5. **Record the plan** — write the research question, hypotheses, method rationale, decision points, constraints, and verification steps to disk.
6. **Check gates before execution** — preconditions, staleness, resource budget, consent, and provenance expectations.
7. **Run only after approval** — execute scripts or daemon jobs, log code/input/output hashes, and ground every conclusion in produced artifacts and verified sources.

The goal is not to guarantee scientific correctness automatically. The goal is to make claims, choices, files, and approvals visible enough that you, your PI, collaborators, and reviewers can inspect them.

---

## A realistic session arc

**Turn 1 — Researcher:** gives context, data paths, prior failures, constraints, uncertainty, and asks for verification before action.

**Assistant + Research OS:** boots the workspace, checks data and prior artifacts, identifies that the Chen notebook used logistic regression rather than a survival model, flags the malformed timestamp issue from the data dictionary, and asks whether the team prefers multiple imputation or a sensitivity analysis for missing symptom onset.

**Turn 2 — Researcher:** "Use multiple imputation if it is defensible, but please don't assume Chen's notebook is approved. Also, I think readmission should be a competing risk because some patients died before follow-up; correct me if that framing is wrong."

**Assistant + Research OS:** records the correction, checks the run ledger and approval state, explains the competing-risk choice, proposes a primary analysis plus sensitivity comparison, and asks for sign-off before opening the first numbered step.

**Turn 3 — Researcher:** "Before coding, add a guard against overfitting. The clinicians want Kaplan-Meier curves, the PI wants credible intervals, and I need the workshop version to be honest about what is exploratory."

**Assistant + Research OS:** updates the plan, separates preregistered covariates from exploratory ones, checks compute budget, and only then proceeds to create the first step, run code, and log outputs with provenance.

---

## The trust stack

| Layer | What it does | Evidence |
|---|---|---|
| **Researcher config** | Declares project mode, researcher preferences, compute limits, and interaction policy | `inputs/researcher_config.yaml` |
| **Schema and bundle** | Validates protocol, tool, and result contracts at build/init time | `.os_state/` bundle artifacts |
| **Protocols** | Scaffold reasoning steps and decision points without hardcoding scientific choices | protocol YAML + generated references |
| **Precondition gate** | Checks required context, inputs, dependencies, and approvals before work proceeds | gate verdicts and run logs |
| **Unskippable gates** | Makes ambiguous or failed enforcement visible instead of silently passing | consent and audit ledgers |
| **Staleness gate** | Warns when an output is older than changed inputs or upstream runs | staleness verdicts and lineage |
| **Resource budget** | Tracks and constrains expensive or long-running work when configured | config + daemon/runtime records |
| **Run ledger** | Records command, code, input/output hashes, timing, status, and approvals | `.os_state/runs/` |
| **Notifications** | Surfaces gate blocks, consent needs, interrupted runs, and completions | daemon outbox or configured delivery |
| **Daemon bridge** | Keeps MCP tools and daemon separated by an on-disk/HTTP contract | [DAEMON_BRIDGE.md](docs/DAEMON_BRIDGE.md) |

---

## Two layers: reasoning plus optional kernel

### Reasoning layer: always present

Your AI assistant reads the protocols, files, and constraints; reasons in natural language; proposes steps; writes scripts and prose; and calls Research OS MCP tools. Research OS is reactive: it responds to those tool calls, records state, and validates structure. It does **not** call an LLM or require your model-provider keys.

### Optional daemon kernel

For long-running or high-assurance projects, the daemon is a separate local process that adds durable execution, recovery, hard gates, resource budgets, and notifications. It is not a chat server, gateway proxy, or OpenAI-compatible API. We intentionally removed the old gateway path; use MCP for tools and let your AI client own model access.

```bash
research-os daemon status
research-os daemon start
research-os daemon stop
```

Start without the daemon. Add it when you need long jobs to survive chat disconnects, consent tokens for sensitive actions, shared-HPC resource ceilings, or stronger provenance for review.

---

## Work modes for real projects

Choose a mode during `research-os init` or pass `--workspace-mode`:

```bash
research-os init my-tool --workspace-mode tool_build
```

- **analysis** — data, evidence, results, and papers.
- **tool_build** — governed software or pipeline development with tests and evaluation.
- **exploration** — scratch-first probing before promoting work into formal steps.
- **hybrid** — research plus tool development in one project.
- **notebook** — Jupyter-first work with Research OS state and gates around it.
- **multi_study** — multiple related studies with shared context and roll-up synthesis.

See [HYBRID_ARCHITECTURE.md](docs/HYBRID_ARCHITECTURE.md), [TOOL_BUILDER.md](docs/TOOL_BUILDER.md), and [SCENARIOS.md](docs/SCENARIOS.md).

---

## For reviewers, PIs, and teams

Research OS is designed to make review possible before submission:

- **Citations** are verified through research-provider tools before they become part of a draft.
- **Claims** are tied back to project artifacts rather than floating in a chat transcript.
- **Runs** can be tracked with commands, inputs, outputs, timestamps, and environment context.
- **State** persists across sessions in memory, logs, and ledgers.
- **Staleness and preconditions** are visible before synthesis or sign-off.
- **Consent** can be daemon-mediated so the AI cannot approve its own hard gates.

A reviewer can inspect the run ledger and ask: what data was used, what code ran, what changed, which approvals were required, and which outputs became stale.

---

## Installation and docs

**Requirement:** Python 3.11 or later.

```bash
pip install research-os
python -m research_os --version
```

For source development:

```bash
git clone https://github.com/VibhavSetlur/Research-OS
cd Research-OS
pip install -e .
python -m research_os doctor
```

| If you want to… | Read |
|---|---|
| Start fast | [START.md](docs/START.md) |
| Wire an AI IDE | [SETUP.md](docs/SETUP.md) and [SETUP_PROMPT.md](docs/SETUP_PROMPT.md) |
| Learn how to prompt it | [PROMPTING.md](docs/PROMPTING.md) and [USE_CASES.md](docs/USE_CASES.md) |
| See worked projects | [SCENARIOS.md](docs/SCENARIOS.md) |
| Understand the workspace | [RESEARCHER_GUIDE.md](docs/RESEARCHER_GUIDE.md) and [PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md) |
| Browse tools and protocols | [TOOLS.md](docs/TOOLS.md) and [PROTOCOLS.md](docs/PROTOCOLS.md) |
| Understand architecture | [ARCHITECTURE.md](docs/ARCHITECTURE.md), [SCHEMA.md](docs/SCHEMA.md), and [CONTRACT.md](docs/CONTRACT.md) |
| Run the daemon | [DAEMON.md](docs/DAEMON.md), [DAEMON_BRIDGE.md](docs/DAEMON_BRIDGE.md), and [CLI.md](docs/CLI.md) |
| Share or review results | [SHARING.md](docs/SHARING.md), [HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md), and [RELIABILITY.md](docs/RELIABILITY.md) |

The full documentation index is [docs/README.md](docs/README.md).

---

 Maintainer-facing release and contribution workflows live in [CONTRIBUTING.md](CONTRIBUTING.md), [RELEASING.md](docs/RELEASING.md), and [PROTOCOL_DOCTRINE.md](docs/PROTOCOL_DOCTRINE.md).

---

## Citation

If you use Research OS in published work, please cite the project metadata in [CITATION.cff](CITATION.cff).

```bibtex
@software{research_os,
  title = {Research OS: Auditable AI Research Scaffolding},
  author = {Research OS Contributors},
  url = {https://github.com/VibhavSetlur/Research-OS},
  version = {5.0.0}
}
```

---

## Contributing, security, and license

Issues and PRs are welcome:

- Bugs: [open a bug report](https://github.com/VibhavSetlur/Research-OS/issues/new?template=bug_report.md)
- Feature ideas: [request a feature](https://github.com/VibhavSetlur/Research-OS/issues/new?template=feature_request.md)
- Contributions: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security reports: [SECURITY.md](SECURITY.md)

Research OS is released under the [MIT License](LICENSE). It does not call an LLM, does not proxy chat completions, and does not manage your model-provider keys.
