# Prompting Research OS — realistic requests that route well

Research OS does the bookkeeping, enforcement, and provenance for you. You drive
it in **plain language** — you don't call tools, you describe what you want and
your AI routes it through the right protocol.

The important change from ordinary prompt lists: real research requests are not
micro-phrases. They include context, data status, prior failures, constraints,
audience, uncertainty, and an explicit ask to clarify or verify before acting.
The router matches intent, not magic wording, so use natural messages that give
the assistant enough to avoid obvious mistakes.

---

## How a request flows

1. You type a message in your IDE/agent chat.
2. Your AI calls `tool_route` with your message. The router picks the protocol
   that fits and returns the relevant working surface.
3. The AI uses Research OS tools to inspect state, validate inputs, record plans,
   run analysis when approved, and write provenance.
4. If a daemon is running, it adds durable jobs, hard-gate consent, freshness
   checks, resource budgets, and notifications. Without a daemon, MCP tools still
   work normally over stdio.

You can always ask: **"What did you just do, what changed on disk, and what is
still unverified?"** The AI should answer from project state, not memory alone.

---

## A strong request template

Use this shape when the stakes are higher than a quick scratch check:

> **Context / goal:** What question are we answering, for whom, and what decision
> depends on it?
>
> **Data / files:** What exists, where it is, what is incomplete, and what should
> not be touched?
>
> **Prior work / failures:** What did you or someone else already try, and what
> went wrong?
>
> **Constraints:** Deadline, audience, privacy/IRB, compute/HPC limits, budget,
> collaborator preferences, venue requirements.
>
> **Uncertainty:** What are you not sure about? What assumption might be wrong?
>
> **Ask:** What should happen now, and what must be verified or clarified before
> any execution?

Short follow-ups are fine once the project is framed, but the first turn should
carry the real context.

---

## Realistic request patterns

### Pull literature into the project

> I'm revising the analysis plan for the ICU scheduling study. The key question
> is whether our staggered rollout can support a difference-in-differences design
> when staffing also changed around the same time. I already have two older PDFs
> in `inputs/literature/`, but I don't know whether they cover recent criticism
> of two-way fixed effects.
>
> Please search for recent, verified papers on staggered-adoption DiD and
> hospital-policy evaluation. Save project-wide background papers to
> `inputs/literature/`, keep any estimator-specific papers with the current
> analysis step if they only justify that choice, and tell me which papers weaken
> our plan. Do not invent citations; if a paper cannot be verified, list it as
> unresolved.

**Behind the scenes.** The AI searches Crossref / Semantic Scholar / PubMed /
arXiv as appropriate, saves validated references, refreshes citations, and may
run step-specific grounding when a paper affects a current analysis.

**Verify.** Ask: "Show me the saved papers, search log, and any unverified
citations." Check `inputs/literature/`, step-level `literature/`, and
`workspace/citations.md`.

### Containerize or reproduce a step

> Step 02 is the model I need to send to a collaborator. It ran on my laptop, but
> the collaborator uses a Linux workstation and we have had package-version drift
> before. Please inspect the step, snapshot the exact environment, and generate a
> step-scoped Dockerfile if the dependencies are stable enough.
>
> Before writing the Dockerfile, tell me whether any inputs are outside the
> project or symlinked from `/scratch`, because those may not travel. Afterward,
> show the build command and the limits of what the container reproduces.

**Behind the scenes.** The AI snapshots the step environment, writes a
step-scoped container recipe, and records what data/code the recipe does and does
not cover.

**Verify.** Ask for the environment snapshot, Dockerfile path, build command,
and any external data dependencies.

### Run something long without blocking the chat

> The stability sweep is going to take hours and we are on a shared SLURM
> cluster. The project config should cap jobs at 16 GB and four hours. Please
> verify the daemon is running, show me the command you intend to submit, estimate
> the resource request, and wait for my approval before launching.
>
> If it starts, I want provenance for the command, environment, inputs, and
> outputs, plus a notification or at least an outbox entry when it finishes. If
> the daemon is not available, do not run the sweep inline; tell me what setup is
> missing.

**Behind the scenes.** With the daemon present, long work routes through tracked
native/container/SLURM runs and consent/resource checks. Without the daemon, the
assistant should degrade open for ordinary MCP work but avoid pretending hard
background guarantees exist.

**Verify.** Ask: "Show me running jobs, the resource budget, and the run ledger
entry." Use `research-os daemon runs` and `research-os daemon logs <run_id>` if
you want the terminal view.

### Build a dashboard, slides, or poster

> I need a dashboard for the consortium by Monday. The audience is clinical
> collaborators who have not seen the workspace, so do not expose step numbers,
> raw file paths, or internal tool names. The safe message is: the candidate
> signature is promising but still provisional until held-out validation finishes.
>
> Please inspect which results are grounded and current, propose the dashboard
> structure, and flag any findings that should be hidden or labeled provisional.
> Ask before generating a public-facing artifact if any supporting run is stale.

**Behind the scenes.** Synthesis protocols assemble an audience-facing structure
from grounded project artifacts and run checks for claims, citations,
accessibility, and staleness.

**Verify.** Open the deliverable. If you see workspace bookkeeping, ask the AI to
rewrite for an external reader and re-run the synthesis check.

### Test a tool or generate sample data

> I'm in `tool_build` mode building a FASTQ deduplicator. We do not have a clean
> public benchmark dataset yet, but I need to know whether the parser handles
> paired-end reads, empty files, malformed quality strings, and duplicate IDs.
>
> Please define the real input contract, generate seeded synthetic fixtures only
> if no suitable real sample is available, label synthetic data clearly, and run
> the tool end-to-end. Before improving the implementation, show me the failing
> cases and the validation check so we don't optimize against vague examples.

**Behind the scenes.** Tool-build protocols pin the input/output contract, create
or select fixtures, run validations, and feed failures into the improve/test
loop.

**Verify.** Ask for the fixture paths, generator seed, validation script, and
which failures became tests.

### Plan iteratively before execution

> We may be trying to answer too many questions. I have a primary outcome, two
> secondary outcomes, and a reviewer concern about subgroup fishing. Please build
> a phased analysis plan with decision gates before any code runs.
>
> Separate confirmatory from exploratory work, record which choices require PI
> approval, and tell me what data checks must pass before we open step 01. If the
> plan depends on assumptions you cannot verify from the files, ask me rather
> than choosing defaults.

**Behind the scenes.** The AI writes a branchable plan, registers hypotheses and
assumptions, and keeps early planning in scratch or planning docs until you
approve a numbered step.

**Verify.** Ask for the durable plan, open hypotheses, decision gates, and the
first preconditions to check.

### Resume after time away

> Pick up where we left off. I think step 03 was re-run after the data dictionary
> changed, but I don't remember whether the paper draft used the new output.
> Please boot the project, check staleness and unresolved gates, summarize the
> current state, and recommend the next action. Do not continue writing until you
> confirm which results are current.

**Behind the scenes.** The AI reads `sys_boot`, state files, run ledgers, and
daemon notes if present, then orients from recorded state instead of chat memory.

**Verify.** Ask: "Which outputs are current, stale, blocked, or missing
provenance?"

---

## Framing tips that consistently help

- **Name the audience and decision.** "For a PI methods review" yields different
  work than "for a patient-facing newsletter."
- **Say what not to do.** "Do not analyze real transcripts yet" or "do not run
  jobs over two hours" should become gates or constraints.
- **Distinguish project-wide from step-specific context.** A paper that changes
  the research question belongs in project literature; a paper justifying one
  estimator can live with that step.
- **Ask for verification.** "Verify paths," "ground every number," "check
  citations," "show stale outputs," and "audit before sharing" trigger the
  discipline Research OS is for.
- **Use quick/scratch only when you mean it.** "Just sanity-check in scratch" is
  useful for low-stakes probes; don't use it for work you plan to cite.
- **Correct the AI explicitly.** "Actually, exclude pilots" or "I meant a
  methods memo, not a manuscript" should re-route without losing state.
- **Remember the boundary.** Research OS provides structure, tools, and
  enforcement points. It does not call an LLM, guarantee the science, or replace
  human judgment.

---

See also: [SCENARIOS.md](SCENARIOS.md), [USE_CASES.md](USE_CASES.md),
[HOW_IT_WORKS.md](HOW_IT_WORKS.md), and [RESEARCHER_GUIDE.md](RESEARCHER_GUIDE.md).
