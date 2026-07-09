# Use Cases — "I want to X" → what to say → what fires

You don't memorize protocols. You say what you want in plain English;
`tool_route` maps your message to the right protocol, and your
**workspace mode** shapes how it runs. This page exists so you can see
what's possible and confirm the AI's choice.

> **Want a real project instead of a lookup table?**
> [SCENARIOS.md](SCENARIOS.md) walks two worked projects end to end — a basic
> one (one dataset → a grounded result) and a deep PI-level program touching
> every capability (onboarding, iterative planning, branching, synthesis
> meetings, a live dashboard, Docker runs, provenance, sharing/handoff) — with
> the exact prompts and what lands on disk.

> **How do I word the request?** This page maps an outcome to a prompt and the
> protocol it fires. For the exact phrasing plus what Research OS does behind the
> scenes for each kind of request (and how to verify it happened), see
> [PROMPTING.md](PROMPTING.md), the prompt phrasebook.

---

## Real research goals (start here)

These are the goals researchers actually arrive with. Find yours and adapt the
example message; each routes cleanly.

### "I want to write a paper from my data."

**Start like this:**

> I have data in `inputs/raw_data/` and a draft question, but I need the path to a
> journal paper to be defensible rather than fast. The target audience is
> [journal/committee/collaborators], the main hypothesis is [hypothesis], and the
> thing I am least sure about is [missingness/confounding/model choice]. Prior
> exploratory work is in `inputs/context/`, and some of it may be stale.
>
> Please onboard the project, verify the data and prior artifacts, propose the
> analysis plan and literature checks, and ask for approval before running models
> or drafting manuscript prose.

**What fires:** onboarding (`session_boot` → `project_startup`) →
`guidance/analysis_plan` per experiment step → `audit/audit_and_validation`
→ `synthesis/synthesis_paper`. **Mode:** analysis.
**You get:** numbered steps under `workspace/NN_*` with grounded figures
and conclusions, then a content-grounded paper **structure** assembled
from *your* results — an outline tailored to your audience and venue that
you render, not a fixed template filled in. Every number traces back to a
step; every citation is verified.

### "I want to build a dashboard."

**Start like this:**

> I need a dashboard for [executives/clinical collaborators/consortium members]
> by [deadline]. The headline should be [decision or takeaway], but some results
> are still provisional and should be labeled that way. Please inspect which
> outputs are grounded and current, propose a dashboard structure for an external
> reader, and hide or flag any stale or unapproved findings.

**What fires:** `synthesis/synthesis_dashboard`. **Mode:** analysis.
**You get:** a dashboard **structure** — sections, the figures and tables
to feature, the narrative order — grounded in your computed results and
tuned to the audience (`audience: academic | executive | technical |
teaching`). Research OS assembles the structure for you to render; it
doesn't hand you a fixed HTML palette.

### "I want to reproduce a published result."

**Start like this:**

> I want to reproduce the result in the PDF I dropped into `inputs/literature/`.
> I have [data/code/no data yet], and my goal is to identify what matches, what
> fails, and whether the discrepancy is due to inputs, environment, method, or an
> unclear paper detail. Please verify the paper metadata, extract the claimed
> result, and propose the reproduction plan before running code.

**What fires:** `methodology/reproduction_attempt`. **Mode:** analysis
(or exploration if you're just probing). **You get:** a reproduction
report — what matched, what didn't, and where the discrepancy lives —
with every comparison grounded in re-run computation, not eyeballing.

### "I want to run a long Docker job and walk away."

**Say (in the terminal):**

```bash
research-os daemon setup            # once
research-os daemon start
research-os daemon docker myimg:1.0 --gpus all -- python train.py
research-os daemon runs             # check history later
research-os daemon logs <run_id>    # manifest + output
```

**What fires:** the **per-project daemon**, not an inline tool. The run
is journaled and provenanced; the exact image digest is recorded so it
reproduces bit-for-bit; the project root is mounted so outputs land back
in the workspace. It survives the IDE closing and rehydrates after a
reboot. On a shared box set `runtime.shared_server: true` so the AI asks
before allocating heavy resources. (For SLURM: `research-os daemon submit
job.sbatch`.)

### "I want to hand this off to a collaborator."

**Start like this:**

> I need to hand this project to [collaborator/team] without losing the decision
> trail. Please package only the approved scope: current results, provenance,
> assumptions, pending decisions, and instructions for reproducing key outputs.
> Screen for restricted data or internal notes before creating an archive, and
> ask me about anything ambiguous.

**What fires:** `guidance/collaboration_handoff`. **Mode:** any.
**You get:** a self-contained package — data provenance, the decision
trail, what's done and what's pending — so a new person (or a fresh chat)
can pick it up. To wrap a working session instead, say *"hand off the
session"* (`guidance/chat_handoff`); to resume, *"pick up where we left
off"* (`guidance/session_resume`).

### "I want to build a pipeline tool, not analyze data."

**Say (init in the right mode first):**

```bash
research-os init . --workspace-mode tool_build
```

then start with a spec-level message:

> I need a FASTQ deduplicator that handles paired-end reads and eventually beats
> `seqkit rmdup` on 10 GB inputs, but correctness and edge-case coverage come
> first. Please define the input contract, acceptance tests, benchmark plan, and
> failure cases before implementation. Ask before choosing compatibility-breaking
> behavior.

**What fires:** `build/spec_and_design` → `build/implement_iteration`
(loop) → `build/test_strategy` → `build/benchmark_vs_baseline` →
`build/release_and_changelog`. **Mode:** tool_build. **You get:** a
tested, benchmarked tool in its own inner git repo with a governance
surface (`spec/`, `decisions/`, `eval/`). "Done" is a passing eval +
green tests + a clean build, not a figure. Full walkthrough:
[TOOL_BUILDER.md](TOOL_BUILDER.md).

---

## Realistic first-session arcs

The highest-leverage first turns give the AI enough context to verify before it
acts. Pick the scenario closest to yours and adapt the message.

### Data + a specific hypothesis

> I have a de-identified cohort CSV in `inputs/raw_data/cohort.csv` and a data
> dictionary in `inputs/context/data_dictionary.md`. The working hypothesis is
> that the new discharge workflow lowered 30-day readmission, but the intervention
> date may differ by unit and I do not want a naive before/after analysis.
>
> Please onboard the project, verify that the required columns exist, profile the
> outcome and missingness, and propose a defensible first analysis. Ask me before
> running any model or creating final figures. The audience is my PI and a
> clinical collaborator, so I need the assumptions explained plainly.

**Routes to:** `guidance/project_startup` → `tool_intake_autofill` → analysis
planning.

### Data, no hypothesis yet

> I have survey data from a pilot study in `inputs/raw_data/`, but the original
> question was too broad and the PI asked me not to go fishing. Please inspect the
> files, summarize what variables and sample sizes we actually have, and help me
> narrow to one or two plausible hypotheses before any formal analysis.
>
> Treat this as exploratory until we explicitly promote a question. If you make
> quick plots, put them in scratch and label them exploratory so they do not look
> like confirmed results.

**Routes to:** onboarding plus `methodology/exploratory_data_analysis` or
`guidance/scope_clarification`.

### Existing project, messy history

> I'm bringing an old project into Research OS. We have months of notebooks,
> several figures, and a draft results section, but I don't know which outputs are
> current. The raw data is in `inputs/raw_data/`; old notebooks and collaborator
> comments are in `inputs/context/`; and the draft manuscript is in
> `inputs/context/draft_results.md`.
>
> Please classify what state the project is in, identify which analyses were done
> outside Research OS, record a provenance ceiling, and tell me what needs to be
> re-run or verified before synthesis. Do not rewrite the paper until the current
> results are identified.

**Routes to:** `guidance/mid_pipeline_entry` and, if appropriate,
`synthesis/synthesis_from_inputs`.

### Building a tool

> This is a `tool_build` project. I need a FASTQ deduplicator for paired-end reads
> that can beat `seqkit rmdup` on large files, but correctness matters more than
> speed for the first milestone. The code is not written yet; I have a few example
> files and a benchmark target in `inputs/context/`.
>
> Please write a spec first: input contract, edge cases, acceptance tests,
> benchmark plan, and what "done" means. Ask me before implementation choices
> that affect file format compatibility. After the spec is approved, implement in
> small iterations with tests.

**Routes to:** `build/spec_and_design` → `build/implement_iteration` →
`build/test_strategy`.

### Interview transcripts / qualitative work

> I have interview transcripts in `inputs/raw_data/transcripts/`, but three files
> are still awaiting de-identification and must not be coded. The IRB protocol,
> interview guide, and prior memo are in `inputs/context/`. I need a codebook and
> methods memo for a committee meeting, not a finished paper.
>
> Please verify which transcripts are cleared, propose whether we should start
> with inductive coding or a framework codebook, and ask before quoting any
> participant text. Track provenance for codebook changes because my committee
> will ask how themes evolved.

**Routes to:** `methodology/qualitative_research` → codebook/quality-audit
protocols.

### Shared-HPC long run

> The validation sweep will take several hours on the shared cluster. Before
> launching anything, verify the daemon status, the resource budget, and the SLURM
> defaults. The command should use no more than 16 GB and four hours, and I need a
> run record I can show my collaborator.
>
> If the daemon is absent, do not run the sweep inline. Tell me what setup is
> missing and what command you would submit once the kernel is available.

**Routes to:** daemon-mediated run/SLURM workflow with consent/resource checks.

A few routing facts the validation surfaced:

- **You don't have to phrase it exactly.** `tool_route` does semantic matching
  first, then a hierarchical trigger picker. Messy researcher language is fine.
- **Wrong protocol? Say "actually I meant X."** It re-routes without reloading
  the workspace.
- **No data yet? Say so and ask for consultation.** A methods-consultation turn
  can teach, compare, or plan without committing the project to an analysis.

---

## By workspace mode

The first fork is *what kind of project this is*, set at `research-os
init .` (`--workspace-mode`, or the wizard) and stored as
`workspace.mode` in `inputs/researcher_config.yaml`.

| You're… | Mode | Realistic opening shape | Routes to |
|---|---|---|---|
| Analyzing data toward a finding / paper | **analysis** *(default)* | Give the question, data path/status, prior failed analysis, audience, and ask for intake + plan before models. | the analysis protocols below |
| Building software you iterate on | **tool_build** | Describe the tool contract, edge cases, benchmark target, acceptance criteria, and ask for a spec before implementation. | `build/spec_and_design` · `build/implement_iteration` · `build/test_strategy` · `build/benchmark_vs_baseline` · `build/release_and_changelog` |
| Poking around, no committed direction | **exploration** | Say which probe is low-stakes, what must stay in scratch, and what evidence would justify promotion to a formal step. | `guidance/casual_exploration` |
| Working notebook-first | **notebook** | Explain what the notebook already does, what outputs are trusted, and ask to reproduce or promote only after verification. | `notebook/notebook_workflow` |
| Building a tool AND using it on data | **hybrid** | Separate the tool milestone from the analysis milestone, and ask to record which tool version produces each result. | `hybrid/hybrid_workflow` · `hybrid/tool_to_analysis_handoff` |
| Running a program (several sub-studies) | **multi_study** | Define the umbrella goal, shared codebook/governance, per-study differences, and roll-up decision gates. | `program/program_setup` · `program/study_register` · `program/cross_study_synthesis` |

---

## By role

### Graduate student / postdoc running their own analyses

Instead of one-line commands, give the assistant the review context:

> I'm the postdoc responsible for the analysis and need a PI-reviewable result by
> next Friday. The data are in `inputs/raw_data/`, the SAP draft and failed
> notebook are in `inputs/context/`, and the current uncertainty is whether the
> missing outcomes are ignorable. Please onboard, verify the old notebook's event
> definition, plan the first EDA step, and ask before running the adjusted model.

Use follow-ups such as: "The EDA changed my mind; branch a sensitivity analysis
but preserve the primary path," or "Before drafting, audit claims and tell me
what is still ungrounded." These route to project startup, analysis planning,
iterative planning, synthesis, and audit protocols as appropriate.

### Principal investigator / lab leader

> I'm reviewing a student's project before lab meeting. I do not need new
> analyses yet; I need to know whether the current claims are supported, which
> outputs are stale, and what decisions require my approval. Please inspect the
> workspace, summarize the evidence trail for each main claim, and prepare a
> meeting update that separates settled results from open methodological risks.
>
> If you find a tempting extra analysis, list it as an option rather than running
> it. I want the student to keep ownership of the next step.

This style routes to progress updates, quick review, code review,
collaboration-handoff, or grant-synthesis protocols depending on the artifacts
present.

### Methodologist / statistical consultant

> I'm advising on method choice, not taking over the project. The team wants to
> model repeated measurements with missing visits, but they are mixing prediction
> goals with causal language. Please inspect the design notes and data dictionary,
> explain the viable model families, list assumptions we can and cannot verify
> from the files, and propose what should be preregistered before data-driven
> tuning.
>
> If you recommend a power analysis or simulation, describe the required inputs
> first and ask for missing design parameters rather than inventing them.

This routes to methodological consultation, methodology selection, power
analysis, data-quality audit, preregistration, or simulation-study protocols.

### Reviewer / journal-club host

> I need to lead journal club on these three PDFs. Please compare the papers'
> research questions, designs, assumptions, and evidence strength. Focus on what a
> skeptical reviewer would ask: unmeasured confounding, multiple comparisons,
> figure clarity, and whether claims exceed data. Verify bibliographic metadata
> and do not rely on memory of the papers.
>
> End with discussion questions and one slide-friendly summary table, but keep
> the critique grounded in quoted or cited paper sections.

This routes to quick paper review, comparative review, figure critique,
reproduction attempts, systematic review, or evidence synthesis.

### Communicator / outreach

> I need a patient-facing summary of the current findings, but only if the claims
> are grounded and approved for sharing. The audience should not see internal
> filenames, uncertain subgroup results, or anything that could be read as medical
> advice. Please audit what is safe to say, flag provisional findings, and draft a
> plain-language structure with caveats preserved.

This routes to lay-summary, press-release, blog, or social-thread synthesis, with
claim and audience checks before wording.

### Presenter / talk-giver

> I have a 12-minute conference talk, and the audience will know the field but
> not our dataset. Please build a talk structure from grounded results only: one
> motivation slide, the design, the main finding, the sensitivity result, and the
> honest limitation. Do not leak workspace step numbers or file paths. If any
> figure is stale or lacks provenance, flag it instead of placing it in the talk.

This routes to slide or poster synthesis and the relevant pre-synthesis audits.

### Theorist / mathematician (theory_math pack)

Activate by saying "prove this", "I have a conjecture", "draft a proof",
or by dropping a `.lean` / `.v` / `.tex` draft into `inputs/raw_data/`.
The pack also reads `inputs/preliminaries.md` (definitions + lemmas your
proofs assume — a hard prerequisite for strategy selection).

| You want to… | What to include in the request | Protocol |
|---|---|---|
| Register an open problem | State the conjecture, definitions already fixed, related lemmas, and whether this is exploratory or for a paper. | `theory_math/conjecture/conjecture_tracking` |
| Choose a proof strategy | Provide the claim, known failed approaches, allowed machinery, and what would count as progress. | `theory_math/method/proof_strategy_selection` |
| Statement → verified proof | Include preliminaries, proof obligations, formalization target if any, and ask for gap checks before prose. | `theory_math/proof/proof_verification_workflow` |
| Formalize in Lean 4 / Coq | Name the theorem, source proof, dependencies, and whether sorry/admitted placeholders are allowed. | `theory_math/formal/lean_integration` · `coq_integration` |
| Compile the theory paper | Identify which claims are proved, which are conjectural, bibliography status, and target venue style. | `theory_math/output/theory_paper_structure` |

### Starting in the middle / just want a viz

| You want to… | What to include in the request | Protocol |
|---|---|---|
| Plug an in-progress project into RO | Describe what artifacts exist, what was produced outside RO, what is trusted, and what needs verification. | `guidance/mid_pipeline_entry` |
| Synthesize from results computed elsewhere | Provide result tables/figures, provenance limits, target audience, and ask to mark unsupported claims. | `synthesis/synthesis_from_inputs` |
| Build a figure deck from a results table | Name the audience, takeaway, table path, required caveats, and visual accessibility needs. | `visualization/visualization_workflow` |
| Multi-panel figure (A/B/C/D) | Explain the scientific story of each panel and which data/output supports it. | `visualization/multi_panel_composition` |
| Critique a figure | Provide the figure, audience, intended claim, and what kind of critique you need. | `visualization/figure_critique` |
| Color-blind / WCAG check | Name the deliverable and target display/print context. | `visualization/color_accessibility_audit` |

### No project yet, just thinking

| You want to… | What to include in the request | Protocol |
|---|---|---|
| Learn / compare methods | Your study design, outcome/data shape if known, what you already tried, and the level of explanation you need. | `methodology/methodological_consultation` |
| Power-justify an upcoming study | Planned design, effect size assumptions, constraints, recruitment limits, and what inputs are uncertain. | `methodology/power_analysis` |
| Pre-register before data lands | Primary question, outcomes, analysis choices, exclusions, and what should remain exploratory. | `methodology/preregistration` |
| Choose a study design | Scientific goal, feasible data collection, ethical/privacy constraints, and decision deadline. | `domain/research_design` |
| Don't know what to ask | What you have, what you are worried about, and whether you want consultation, exploration, or a formal project. | `guidance/scope_clarification` |

---

## By output type

| Want this output | Protocol |
|---|---|
| Polished figure / figure deck | `visualization/visualization_workflow` |
| Multi-panel figure (A/B/C/D) | `visualization/multi_panel_composition` |
| Paper (IMRAD) | `synthesis/synthesis_paper` |
| Discussion / Results / Limitations section | `writing/writing_discussion` · `writing/writing_results` · `writing/writing_limitations` |
| Cover letter | `synthesis/synthesis_cover_letter` |
| Pre-submission checklist + verdict | `audit/pre_submission_checklist` |
| Abstract | `synthesis/synthesis_abstract` |
| Poster | `synthesis/synthesis_poster` |
| Dashboard | `synthesis/synthesis_dashboard` |
| Slides (lab / conference / defense) | `synthesis/synthesis_slides` |
| Internal / technical report | `synthesis/synthesis_report` |
| Grant narrative | `synthesis/synthesis_grant` |
| Lay summary / press release / blog | `synthesis/synthesis_lay_summary` |
| PI / weekly update | `synthesis/synthesis_progress_update` |
| One-pager / handout (with QR) | `synthesis/synthesis_handout` |
| Reproduction report | `methodology/reproduction_attempt` |
| Power justification paragraph | `methodology/power_analysis` |
| Evaluation protocol document | `methodology/evaluation_design` |
| Data-quality audit report | `methodology/data_quality_audit` |

> **What "output" means here.** Research OS provides **structure**, not a
> fixed template. A synthesis protocol assembles a content-grounded
> *outline* — the right sections, the figures and numbers to feature, the
> narrative order — tailored to your audience and venue, for you to
> render. It does not hand you a canned `.typ`/`.html` palette to fill in.

---

## End-to-end recipes (the protocol stack for a complete deliverable)

`tool_route` picks ONE protocol per message. A full project is many
protocols composed — the AI walks them automatically as each protocol's
`next_protocol` advances.

| If your project is… | The pipeline | Final deliverable |
|---|---|---|
| **Qualitative interview study** | `project_startup` → `qualitative_research` → `coding_scheme_development` → `qualitative_quality_audit` → `audit_and_validation` → `synthesis_paper` (+ `synthesis_dashboard`) | Paper structure (+ dashboard structure) |
| **Quantitative ML benchmark** | `project_startup` → `methodology_selection` → `evaluation_design` → `method_comparison` → `audit_and_validation` → `synthesis_paper` | Paper structure |
| **Theory / math proof** | `project_startup` → `proof_strategy_selection` → `proof_verification_workflow` → `theory_paper_structure` → `synthesis_paper` | Theory paper structure (Theorem / Proof / References) |
| **Building a tool (tool_build)** | `spec_and_design` → `implement_iteration` (loop) → `test_strategy` → `benchmark_vs_baseline` → `release_and_changelog` | A tested, benchmarked tool in its own git repo |

When the wrong recipe gets picked, say *"actually I meant \<X\>"* and the
AI re-routes without losing the workspace.

---

## Deep scenarios (the whole machine, including the daemon)

The recipes above are protocol stacks. The scenarios below are
*narratives* of messy, real research with the daemon running — long jobs,
walking away, autonomy, mode changes. The daemon is OPTIONAL: with none
running, everything still works over stdio; the daemon adds durable
execution, recovery, enforcement, and notifications. Start one with
`research-os daemon start`.

### Scenario 1 — overnight run on a shared cluster, then walk away

A postdoc on a shared box has a 9-hour sweep.

1. The researcher writes: *"My cohort file is at `/scratch/me/cohort.parquet`
   and is about 80 GB, so please do not copy it blindly. I need an analysis
   project and a hyperparameter-sweep plan, but verify the data shape, symlink
   with provenance if appropriate, and show the resource estimate before
   launching."* → the AI inits, symlinks the data into `inputs/raw_data/`
   (recording path + hash and flagging the project not-self-contained), onboards,
   and plans step `01_sweep`.
2. Because `runtime.shared_server: true`, the AI **asks** before
   launching — the sweep wants ~40 GB and 9 h. The researcher approves.
3. The job runs through the **daemon** (`research-os daemon run` /
   `daemon docker`), not inline, so it survives the IDE closing. The
   daemon journals it, applies the resource budget, and the researcher
   goes home.
4. The login node reboots overnight. The daemon **rehydrates**: the run
   is marked `interrupted`, and `sys_boot` next morning leads with
   *"1 run was interrupted — resume it."*
5. When the sweep finishes, the daemon **notifies** and (if configured)
   re-prompts the AI to score the result and plan `02_analysis`.

### Scenario 2 — exploration that earns its way into a real analysis

1. *"Set up an exploration project. I suspect dosage tracks outcome, but this
   is a low-stakes probe and should stay in scratch until we see whether the
   signal survives basic checks. Please label outputs exploratory and tell me
   what evidence would justify promoting it."* → inits in **exploration** mode.
2. Three probes later, one holds up. The AI: *"this looks real — we can
   promote to analysis mode."*
3. *"yes, switch to analysis"* → the AI **plans** the numbered-step
   surface, then on confirm **applies it additively** — scratch probes
   preserved, the earned probe promoted into step `01`.

### Scenario 3 — plan deeply, then let the AI run toward the goal

1. *"Plan this deeply before execution. The goal is a validated signature for
   collaborators, not a paper yet. You may run toward the goal after I approve
   the roadmap, but nothing destructive autonomously, no row-level export, and
   cap any run at 16 GB. Ask at decision gates."* → the AI walks
   `methodology/deep_planning` to write a branchable roadmap in
   `inputs/research_plan.md`.
2. On approval, it hands off to `guidance/roadmap_execution`: pick the
   next milestone → execute → score it → record evidence → re-plan →
   continue. Quality is enforced by per-milestone judging + audit gates.
3. If the agent is **Hermes Agent**, it orchestrates the loop, pulls
   relevant skills each cycle, and notifies the researcher at decision
   points or if a run would exceed the 16 GB cap.

---

## You don't have to choose

`tool_route` picks the right protocol from a plain-English prompt. When
you genuinely don't know what you want, say so:

> "I have some data and several half-formed ideas, but no clean hypothesis yet.
> Please inspect what is on disk, ask one clarifying question at a time, and help
> me decide whether this should be exploratory, analysis, or just a methods
> consultation before we touch the data."

The AI loads `guidance/scope_clarification`, classifies the ambiguity,
asks ONE narrowing question, and re-routes on your answer. When a project
spans two subfields, the AI runs `methodology/deep_domain_research` once
per subfield and holds both pipelines side-by-side rather than
force-fitting one.

For the full feature history, see [CHANGELOG.md](../CHANGELOG.md).
