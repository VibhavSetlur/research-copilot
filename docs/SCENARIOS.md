# Scenarios — Research OS on real projects

Two worked examples. The first is **short**: a single researcher with one
dataset, start to a result, so you can see the basic shape. The second is
**long and deep**: a PI running a real multi-phase program, and it deliberately
touches nearly every capability Research OS has — onboarding, literature
grounding, iterative phased planning, branching and deleting steps, synthesis
"meetings," a live public dashboard, Docker runs, image and folder sharing, git
provenance, and cross-actor handoff — so that if you want to *truly* understand
the system, you can follow one project through all of it.

These are not idealized. Real research loops, backtracks, and revises. The
scenarios show that, not a clean line from setup to paper.

A note on how to read them: lines you type to your AI are shown as **You ▸**.
What the AI does (the real tools and CLI it calls) is shown indented beneath.
Every tool name (`tool_route`, `sys_boot`, …), protocol, CLI command, and file
path used here is real.

---

## Scenario 1 — Basic: one dataset, one question, one result

**Researcher:** Maya, a grad student. **Goal:** does a new scheduling policy
reduce ICU readmissions in her hospital's de-identified extract? **Mode:**
analysis. **Editor:** Cursor. She has one CSV and a vague hypothesis.

### Setup (5 minutes)

She opens the folder in Cursor and pastes the [Setup Prompt](SETUP_PROMPT.md)
with a realistic context block: the project is `icu-readmission`; the goal is to
assess whether a new scheduling policy lowered 30-day ICU readmission; the CSV is
still in `~/exports/icu.csv`; the policy date may differ by unit; an old notebook
used questionable inclusion criteria; the advisor wants a reviewable plan before
models; and no row-level data should leave the machine. The AI:

```
pip install research-os
research-os init . --ide cursor --workspace-mode analysis --question "does the new scheduling policy lower 30-day ICU readmission"
research-os daemon start            # optional kernel → serving: yes
```

It fixes the `command: research-os` path in `.cursor/mcp.json` to the absolute
conda path, tells her to **restart Cursor**, and waits.

### After restart — the AI proves it works, then onboards

```
sys_boot              → state + mode=analysis + next protocol = project_startup
tool_route(prompt=<Maya's full context message>)  → guidance/project_startup
research-os doctor    → all green
```

Onboarding (`project_startup`) is where the project gets framed — the AI does
**not** jump to modeling:

- `sys_file_list` over `inputs/raw_data`, `inputs/literature`, `inputs/context`.
- Maya hadn't moved her file in; she says, "It's at `~/exports/icu.csv`, but
  please check size and de-identification status before copying." The AI copies
  it into `inputs/raw_data/` only after confirming it is small and appropriate,
  then records the source.
- `tool_intake_autofill(question=…, hypotheses=["H1: policy reduces 30-day readmission"], context_note=…)`
  → writes `inputs/intake.md` and registers H1 in state.
- `tool_data(operation='profile', filepath="inputs/raw_data/icu.csv")` → flags
  12% missingness in one column and a class imbalance she didn't know about.
- A **mandatory literature pass**: `tool_search` for recent readmission-policy
  work and `tool_research_method method="difference-in-differences"`; the
  relevant hits are saved to `inputs/literature/`. (The AI does not trust its
  training memory for what's published.)
- It shows her the framed question, H1, the data-quality flags, and the method
  it's leaning toward, and asks: **approve or refine?** She approves.

### One analysis step → a grounded result

`tool_route` → `guidance/analysis_plan`. The AI opens the first numbered step
with `sys_path(operation='create')`, plans it into sub-tasks with
`tool_plan_step`, writes a script under `workspace/01_did_readmission/scripts/`,
runs it with `tool_python_exec`, and produces a figure. Because the computation
ran **through a step script**, an output `.prov.json` sidecar is written
automatically (inputs by hash, script, seed, package versions, git sha).

It writes `conclusions.md` from the artifacts, then **grounds** the prose:
`tool_ground` confirms every number traces to a real output, and
`tool_citations_verify` checks the references against Crossref. `tool_step_complete`
runs the completeness + grounding + staleness checks before the step is allowed
to close — the class-imbalance caveat gets recorded, not glossed.

### Result

Maya has a figure, a written conclusion every number of which is traceable, and
a clean methods trail — in an afternoon. When her advisor asks "is this result
current and reproducible?", she opens the figure's `.prov.json` and the saved
search log. That's the basic loop: **frame honestly → run through steps →
ground → check before calling it done.**

---

## Scenario 2 — Deep: a PI's multi-phase program, end to end

This one is long on purpose. If you read one thing to understand what Research OS
*is*, read this.

**PI:** Dr. Okafor, who runs a lab studying airway inflammation. **The real
project:** integrate three single-cell + bulk RNA-seq cohorts to find a drug-
response signature, validate it computationally, brief collaborators at two
points, keep a **public-facing dashboard** live for the consortium while the work
is still moving, and hand a validated signature to a wet-lab group to test —
**without writing a paper yet**, because a grant and the wet-lab work depend on
the result first. She already has a plan in her head; she wants Research OS to
*organize the chaos*, enforce rigor, and keep everything reproducible and
shareable across a shared HPC cluster.

> **Why no paper at the end?** Real PI work often stops at a *validated,
> shareable result* — the paper waits on wet-lab confirmation and the grant
> cycle. Research OS does not assume "the deliverable is a manuscript." Here the
> deliverables are a dashboard, a shared signature + Docker image, and a
> collaborator handoff.

### Phase 0 — Setup and onboarding on a shared HPC node

Dr. Okafor opens the project on a login node and pastes the Setup Prompt with
`[hermes]=yes`, `[os]=shared HPC login node`, `[mode]=hybrid` (she will both
*analyze* cohorts and *build* a small scoring tool), and `[autonomy]=adaptive`.
Her context is messy and specific: three paragraphs of lab background, two named
papers, cohort locations on `/scratch`, notes that one cohort has incomplete
metadata, a prior batch-correction attempt that failed, a 16 GB shared-node
budget, and the requirement that "the signature has to be defensible to a study
section."

The AI installs into a conda env, scaffolds, and because the default daemon port
is taken on the shared node, `research-os daemon setup --start` auto-picks a free
port and launches it detached (no Docker, no systemd). It fixes the MCP path,
she restarts, and the self-test passes.

**Onboarding (`project_startup`) does the heavy lifting:**

- The three cohorts live on `/scratch`. Two are moderate (copied into
  `inputs/raw_data/` to freeze provenance); one is 40 GB, so the AI **symlinks**
  it, records the absolute source path + a content hash, and flags that the
  project is now not fully self-contained. (This copy-vs-symlink reasoning is in
  the protocol, not a guess.)
- `tool_intake_autofill` turns her `[context]` into a framed question, four
  hypotheses, and a domain classification (genomics). Each hypothesis is
  registered with `mem_hypothesis_add`.
- Maya asks for literature realistically: **"Before we call this
  difference-in-differences, find recent hospital-policy and staggered-adoption
  papers, and tell me if they undermine the plan."**
  `tool_literature_search_and_save` runs targeted searches; the two papers she
  named are fetched by DOI; current papers land in `inputs/literature/`; and the
  searches (including empty ones) are logged. She drops three more PDFs in
  herself — `inputs/` is immutable input, and the intake SHA-256 inventory now
  tracks them.
- Because she's on Hermes, the AI pulls the matching skills up front (single-cell
  analysis, the R/Python stat stack, figure work) and runs
  `research-os skills add-science-pack` so the K-Dense science skills
  (bulk-rnaseq, experimental-design, …) are available;
  `sys_boot.recommended_skills` lists which apply.

### Phase 1 — Iterative planning *before* any analysis

She doesn't want the AI to dictate steps. She writes: **"Iterate on a plan with
me before any analysis. I am worried the cohorts are not comparable, and the
prior batch-correction attempt overcorrected disease signal. Use the papers I
named, ask if metadata is missing, and separate what we need for the grant from
what would be needed for a paper."** `tool_route` → `guidance/iterative_planning`.
Over **two sessions**, the AI drafts the roadmap in `inputs/research_plan.md`
(the durable, branchable plan — no numbered step is committed yet), they argue
about cohort batch correction, she points at a method from one of the papers, the
AI revises `inputs/research_plan.md` and appends each change to its iteration
log. Producing no analysis on day one is correct. Only when the plan stops moving
does she say "lock it in," and the roadmap's milestones become numbered phases,
each ending in a **decision gate**.

`guidance/iterative_planning`, `methodology/deep_planning`, and
`guidance/roadmap_execution` structure the phases:

1. Per-cohort QC + batch-correction.
2. Integrate the three cohorts.
3. Derive a candidate drug-response signature.
4. Validate the signature (held-out cohort + stability).
5. Decision gate → hand to wet lab.

### Phase 2 — Executing phases as numbered steps, with branching

Each phase runs as one or more numbered steps under `workspace/`. The AI opens a
step (`tool_step`), writes and runs analysis (`tool_python_exec`,
`tool_r_exec`), and every output gets its `.prov.json`. A single QC step goes
`_v1 → _v2 → _v3` across days as she refines a threshold — **old versions never
disappear**; that iteration ledger *is* the methods section.

**A new paper arrives mid-step.** A reviewer-grade method paper drops while
she's in the integration step. Two homes, and the distinction is the point:

- It reframes the whole integration approach → it goes to `inputs/literature/`
  as a project-level citation.
- It only justifies the specific batch-correction choice she's making *right
  now* → it goes in that step's own `workspace/NN_integrate/literature/` so the
  reason lives next to the change.

The script bumps to `_v(k+1)`, the new output gets a fresh sidecar,
`conclusions.md` records *why* the revision happened, and the provenance check
flags any downstream step built on the old output as stale.

**Branching and deleting a step.** The signature-derivation phase forks: she
wants to try both a regularized-regression and a network-propagation approach.
The AI proposes the fork with `tool_alternative_path_propose` /
`tool_branch_recommendation` and runs both as sibling steps. The network
approach dead-ends (unstable across cohorts). She doesn't pretend it didn't
happen: `tool_route` → `guidance/dead_end_routing` **preserves** the failed path
(it stays in the tree, marked dead-end, with the lesson recorded via
`tool_lessons`) and routes back to the regression branch. A dead end you can see
is a result; a deleted one is a gap a reviewer will find.

**Adding context mid-stream.** Her collaborator emails a constraint ("the
signature must use genes on the clinical panel"). She drops it into
`inputs/context/`, asks the AI to re-read intake; the constraint propagates into
the next step's scope without disturbing finished steps.

### Phase 3 — A synthesis "meeting"

After Phase 2, she wants to brief the lab. Research OS treats this as a
first-class **synthesis** activity, not an afterthought.
She asks: **"Put together a progress update for the lab. The audience needs to
know what is settled, what remains provisional, and whether dropping the noisy
cohort is scientifically defensible. Do not make it look like a completed paper."**
`tool_route` → `synthesis/synthesis_progress_update`. The AI uses
`tool_synthesis_scaffold` to assemble a **structure** (what's settled, what's
open, the decision the meeting needs to make) pulled from the real step
conclusions — and per Research OS doctrine it gives **structure, not design**: a
markdown outline with per-section intent, for *her* to deliver, not a templated
deck. `tool_synthesis_check` confirms every claim in the update traces to a
grounded step output. They meet, decide to drop one cohort that's driving
heterogeneity, and that decision re-orders the later phases — exactly the
decision-gate model.

### Phase 4 — New results, second synthesis, and a live public dashboard

With the cohort dropped, the integration and signature steps re-run (new run
records, not new step folders — the definitions are stable, the runs accumulate).
A cleaner signature emerges.

The consortium wants visibility **while the work is still moving.** Dr. Okafor
writes: **"Stand up a consortium dashboard, but mark the signature provisional,
hide anything derived from the dropped cohort until we review it, and do not show
internal file paths or step numbers."** `tool_route` →
`synthesis/synthesis_dashboard`. The AI scaffolds the dashboard's **structure** —
which current, grounded results are safe to show, what's marked provisional,
what's hidden until validated — and she renders it. It's regenerated as results
land, with provisional items clearly flagged so no one over-reads an in-flight
number. A second `synthesis_progress_update` briefs the collaborators on the new
signature.

### Phase 5 — Heavy validation through the daemon: Docker, provenance, sharing

Validation is compute-heavy and must be **bit-for-bit reproducible** for the
study section. This is where the daemon's job engine carries the load.

- **A long SLURM run** for the stability analysis:
  `research-os daemon submit "Rscript validate_stability.R"`. The daemon polls it
  to completion, survives a login-node reboot mid-run, captures a full
  environment snapshot, and journals it. A **stall watcher** would flag it if the
  log stopped advancing.
- **A containerized run for exact reproducibility.** The integration pipeline
  ships as a pinned Docker image so the result is recreatable on any machine:
  ```
  research-os daemon docker airway-integrate:1.4 --gpus all -- python run_integration.py --cohorts all
  ```
  The run is tracked like any other and records the **image + content digest** in
  its provenance, so "which exact image produced this output?" has an answer.
  (Works with Podman too; on the cluster's Kubernetes it runs via a thin
  wrapper — same daemon contract.)
- **Sharing the image.** She pushes `airway-integrate:1.4` to the lab registry so
  the wet-lab group and collaborators run the identical pipeline; the digest in
  the run record is the contract.
- **Git provenance throughout.** The AI commits work increments with `tool_git`,
  stamping each commit so a result links back to the exact code that made it.
  `verify_provenance_integrity` (via `tool_audit`) re-hashes recorded inputs and
  outputs before the validation milestone to prove nothing drifted.
- **Seeing how it all connects.** `tool_workflow_dag` renders the analysis
  workflow, and the daemon's content-addressed **run-lineage** renders as a
  provenance diagram (`GET /v1/lineage.mermaid`) — "how was the validated
  signature produced, from what, through which runs?" answered as a picture.

### Phase 6 — The decision gate and a cross-actor handoff (no paper)

The validation clears her bar. The decision gate says: **hand the signature to
the wet lab; defer the manuscript.** She does not force a paper the data isn't
ready to support.

Dr. Okafor asks: **"Hand the validated signature folder to the wet-lab group for
the next step. Include the Docker image digest, assumptions, gene-panel
constraint, and exactly what result they owe back. Screen for anything restricted
before packaging."** `tool_route` → `program/pipeline_stage_handoff`. The AI:

- scopes exactly which output folder is the handoff (the validated signature +
  its provenance), not the whole project;
- pins its provenance (the runs, the Docker image + digest, the inputs by hash)
  and resolves any staleness first;
- writes a consumer-facing **contract** (a `HANDOFF.md` in the folder): what each
  file is, the gene-panel constraint, the assumptions the wet lab must respect,
  the exact deliverable they owe back, and how to reproduce the signature from
  the image;
- packages it safely (`sys_export_share_archive` for the outside group; the run
  journal + sidecars travel intact), screening for anything restricted;
- and confirms the **return loop** — where the wet-lab result lands so this
  pipeline can consume it back later.

For the grant, she also asks for `synthesis/synthesis_grant` structure — again an
outline grounded in the real results, for her to write.

### What just happened

Across the program, Research OS:

- **Organized the chaos** — onboarding, a locked iterative plan, numbered phases
  with decision gates, branches, a recorded dead end, mid-stream context.
- **Enforced rigor** — every result grounded, citations verified, completeness/
  staleness checks before each step closed, provenance re-verified before
  milestones.
- **Made the work reproducible and shareable** — `.prov.json` sidecars, the run
  journal, SLURM + Docker runs with environment + image-digest provenance, git
  stamping, a shared image, a contracted folder handoff.
- **Briefed humans on her terms** — two synthesis meetings and a live public
  dashboard, all *structure not design*, every shown number traceable.
- **Knew when to stop** — a validated, shared result, no premature paper.

Every capability above is real and reachable today. To go deeper on any of it:
[HOW_IT_WORKS.md](HOW_IT_WORKS.md) for the concepts, [PROTOCOLS.md](PROTOCOLS.md)
for the full protocol catalogue, [DAEMON.md](DAEMON.md) for the job engine and
Docker/SLURM runs, [TOOLS.md](TOOLS.md) for every tool, and [SHARING.md](SHARING.md)
for archives and handoffs.
