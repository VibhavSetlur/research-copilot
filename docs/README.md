# Research OS — documentation

This page routes by audience. CHANGELOG.md at the repo root has the full release history.

---

## For researchers

You're using Research OS on your own research project. Read in this order —
it's a path, not a pile:

**1. Understand it (5 min).** [**HOW_IT_WORKS.md**](HOW_IT_WORKS.md) — how a
real project actually unfolds (iterating on the plan, circling the literature,
bringing a new paper into a step mid-analysis, not calling things done too
early) and the three things that make your results hold up: provenance,
accuracy, organization. Start here even before installing.

**2. Set it up (15 min).** [**START.md**](START.md) — install, wire your IDE,
first project, cheatsheet. Or hand your AI the one
[**SETUP_PROMPT.md**](SETUP_PROMPT.md) (copy, fill the blanks, paste) and let
it do the whole setup + onboarding for you.

**3. See it for real.** [**SCENARIOS.md**](SCENARIOS.md) — two worked projects
end to end: a **basic** one (one dataset → a grounded result) and a **deep
PI-level program** that touches nearly every capability (onboarding, literature
grounding, iterative phased planning, branching + deleting steps, synthesis
meetings, a live public dashboard, Docker runs, provenance, image + folder
sharing, cross-actor handoff). A named researcher, real data, the exact words
they typed, what landed on disk.

**4. Work with it (keep open).** [**RESEARCHER_GUIDE.md**](RESEARCHER_GUIDE.md)
— the full reference: the mental model, every protocol, the config, power-user
patterns, troubleshooting.

**Ask for what you want.** [**PROMPTING.md**](PROMPTING.md) — the phrasebook:
how to word a request to get a specific outcome (dockerize a step, pull papers
into inputs, build a shareable dashboard that doesn't leak step numbers, make
sample data to test a tool) and what Research OS does behind the scenes when you
do. Plus how to verify each result actually happened.

Reference, as you need it:

- [GLOSSARY.md](GLOSSARY.md) — the vocabulary: step, path, plan.md,
  conclusions.md, the data folders, the literature corpus, audit, and more.
- [PROJECT_LAYOUT.md](PROJECT_LAYOUT.md) — the canonical directory layout: the
  safety backbone (`.os_state`, `inputs/`, `workspace/`, …) and what each
  workspace mode adds. The single source of truth for what lives where.
- [USE_CASES.md](USE_CASES.md) — "I want to write a paper / build a poster /
  reproduce a result" → which protocol fires.
- [TOOL_BUILDER.md](TOOL_BUILDER.md) — building software, not analysing data?
  The **tool_build** workspace mode: spec → implement → test → ship.
- [SETUP.md](SETUP.md) — per-IDE MCP wiring, troubleshooting installs.
- [BEST_SETUP.md](BEST_SETUP.md) — the best agent layer + MCP stack + daemon
  setup for your project type (Hermes, context7, autonomous loops).
- [FAQ.md](FAQ.md) — common questions.
- [CLI.md](CLI.md) — every `research-os` CLI sub-command.
- [DAEMON.md](DAEMON.md) — the optional daemon: long jobs without blocking the
  chat, run provenance + freshness, hard human-approved gates, a resource
  budget the machine enforces, and completion notifications. Skip it for quick
  work; start it for big / long-lived projects.
- [SHARING.md](SHARING.md) — how to hand off a workspace to a collaborator.

---

## For AI agents + plugin authors

**AI agents:** start at [**AI_GUIDE.md**](AI_GUIDE.md). At runtime, prefer `sys_boot` and `sys_active_tools` over the docs — they reflect what's actually installed.

**Plugin authors:** start at [**PLUGIN_AUTHORING.md**](PLUGIN_AUTHORING.md). The in-tree packs under `src/research_os_<pack>/` are working templates.

Shared:

- [TOOLS.md](TOOLS.md) — full tool catalogue.
- [PROTOCOLS.md](PROTOCOLS.md) — every protocol, when each fires, quality bars enforced.
- [PROTOCOL_DOCTRINE.md](PROTOCOL_DOCTRINE.md) — the scaffold-not-script principle behind every protocol.
- [RELIABILITY.md](RELIABILITY.md) — audit + test posture (auto-generated).

---

## Architecture & internals

How the system is built — the MCP reasoning core, the optional daemon
enforcement kernel, and the on-disk contract between them. Read these if
you're extending Research OS, embedding it, or want to understand how the
guarantees are enforced.

- [**ARCHITECTURE.md**](ARCHITECTURE.md) — the big picture: what the MCP
  server is, what the daemon is, what moves and what stays, the design
  principles that hold the line.
- [ROADMAP.md](ROADMAP.md) — design history + build log + running progress
  log for the daemon enforcement kernel.
- [DAEMON.md](DAEMON.md) — the optional daemon from the operator's side:
  starting it, what it gives you, when to bother.
- [DAEMON_BRIDGE.md](DAEMON_BRIDGE.md) — the single canonical MCP↔daemon
  contract (`.os_state/` by shape; the seam neither side may cross).
- [UNSKIPPABLE_GATES.md](UNSKIPPABLE_GATES.md) — how the daemon turns soft
  prose gates into hard, human-approved ones.
- [PRECONDITION_GATE.md](PRECONDITION_GATE.md) — protocols declare what must
  be true; the daemon verifies before a step runs.
- [STALENESS_GATE.md](STALENESS_GATE.md) — don't ship a result built on data
  that changed underneath it.
- [HYBRID_ARCHITECTURE.md](HYBRID_ARCHITECTURE.md) — protocols declare, the
  daemon enforces: the soft-prose → hard-structure throughline.
- [NOTIFICATION_SPINE.md](NOTIFICATION_SPINE.md) — how a long job tells the
  researcher it finished.
- [RESOURCE_BUDGET.md](RESOURCE_BUDGET.md) — turning "stay within budget"
  prose into machine-enforced rlimits.

---

## For maintainers + integrators

- [**CONTRACT.md**](CONTRACT.md) — which surfaces are stable enough to pin against. Read this if you're embedding RO programmatically.
- [**RELEASING.md**](RELEASING.md) — release runbook.
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — contributor workflow + branch model + test conventions.
- [`../CHANGELOG.md`](../CHANGELOG.md) — release history.
