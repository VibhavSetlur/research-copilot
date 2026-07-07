# Protocol doctrine — scaffold, not script

A Research OS protocol gives the AI a **scaffold for reasoning**, not
a **script to execute**. This is the single most important rule for
anyone editing a protocol or adding a new one. If you internalise
nothing else from this file, internalise that.

## The principle

A scaffold names:
1. The **questions** worth asking about a project
2. The **dimensions** worth reasoning over
3. The **grounding** the answer must cite
4. The **artefacts** that record the reasoning

A scaffold does NOT name:
1. The specific method
2. The specific tool / library / CLI
3. The specific threshold / cutoff / hyperparameter
4. The specific step sequence

The AI fills in the specifics per project, from the literature, never
from training memory or from a table in the protocol.

## Why

Three reasons.

**Reasoning generalises; recipes don't.** A protocol that says "use
DESeq2 with ~condition design" is correct for one decade in one
subfield and silently wrong everywhere else. A protocol that says
"reason about the outcome's distributional family + the dependency
structure + the field's current best-practice estimator" is correct
in every era of every field.

**Prescription erodes the AI's reasoning surface.** When a protocol
hands the AI an answer, the AI stops looking — even when the answer
is wrong for the current project. Scaffolds force the AI to *justify*
each commitment, which surfaces the cases where the default would
have been wrong.

**Maintenance debt.** A repository of 47 prescriptive protocols
becomes a repository of 47 things that go stale at different rates.
Scaffolds are stable across decades because the *questions* don't
change as fast as the *answers*.

## How to spot prescription in a protocol

A description that contains any of the below is suspect:

- A finite menu of methods mapped from data shape, like
  `Continuous · independent · low-D → OLS / Ridge / LASSO`. *(Real
  example, now removed.)*
- A named threshold without a citation, like `CFI ≥ 0.95`,
  `|SMD| > 0.10`, `I² > 75% = considerable`. The threshold may even
  be the field convention — but stating it without a source pushes
  the AI to copy it instead of looking it up for THIS field.
- A specific tool / library name as the default, like "use dowhy /
  econml / SHAP / MICE". The tool is fine to mention as an example;
  it is not fine to default-pick.
- A canned step sequence with no branch points, like
  "randomisation_check → ITT/PP → MICE → primary_analysis →
  safety → CONSORT". Each step might be reasonable; the
  fixed order asserts that this is the right shape for every project
  in the methodology, which it never is.
- A specific split ratio, sample-size cutoff, or count, like
  "70/15/15 split", "Aim for 30-100 codes", "minimum 10 studies".
  Numerical defaults masquerade as scaffolds; they're recipes.

## How to write scaffold language

Patterns that work:

- **Name the question, not the answer.** "What's the outcome's
  distributional family on this sample?" beats "Use a Poisson GLM for
  count data."
- **Name the dimension, not the value.** "Justify the split from the
  deployment regime" beats "Use a 70/15/15 split."
- **Demand grounding, not a tool.** "Surface the field's current
  best-practice estimator via `tool_search`" beats "Use
  DESeq2."
- **Frame thresholds as field-specific.** "Cite the source for
  whichever cutoff is used" beats "Use CFI ≥ 0.95."
- **State the failure mode, not the procedure.** "Treating clusters
  as fixed when they were fit on the same data inflates type-I error"
  beats "Run the test on a holdout sample."

## When prescription IS the right answer

Some commitments aren't optional and shouldn't be scaffolded around:

- **Reproducibility primitives.** "Set RNG seeds explicitly; print
  library versions" is prescription, but it's prescription about the
  *system*, not about the *science*. Keep it.
- **Mechanical conventions.** "Save figures to
  `outputs/figures/` at ≥300 DPI" is prescription. It's about file
  layout that downstream tooling depends on, not about the analysis.
  Keep it.
- **Universal failures of inference.** "Cluster-then-DE without
  pseudo-bulk aggregation is pseudo-replication" is a fact about
  inference, not a methodology choice. Stating the failure mode as a
  rule is fine.

The line: prescription about WHO uses what tool is bad; prescription
about HOW the system records the work is good.

## Reviewer's checklist

Before merging a protocol change, walk every step:

1. Could a researcher in a different field use this step? If the
   answer requires renaming the methodology, it's scaffolded; if it
   requires rewriting the step, it's prescribed.
2. Does the step name a tool or threshold? If yes, is it tagged as
   "the literature names" / "the field's reporting standard names" /
   "cite the source"? If not, rewrite.
3. If you removed every tool name, library name, and numerical
   threshold from the step description, would the step still tell
   the AI what to do? If yes, the step is a scaffold. If no, it was
   a recipe.
4. Does the step demand citation for every commitment? Reasoning
   without grounding is just opinion.

## Examples

Prescription:

```yaml
- id: factor_structure
  description: |
    EFA / CFA. Report:
      CFA → CFI, TLI (≥0.95), RMSEA (≤0.06), SRMR (≤0.08).
```

Scaffold:

```yaml
- id: factor_structure
  description: |
    Decide between exploratory and confirmatory factor analysis.
    Report whichever fit indices the field treats as canonical for
    this kind of model. Thresholds are field-specific — cite the
    source.
```

Prescription:

```yaml
- id: data_split
  description: |
    Stratified 70/15/15 split. Set random_state explicitly.
```

Scaffold:

```yaml
- id: evaluation_regime
  description: |
    The split mirrors the deployment regime. Time-forward
    deployment → time-forward split. Cross-institution deployment →
    leave-one-institution-out split. A random k-fold split requires
    a positive justification, not a default.
```

### A whole protocol as scaffold — `synthesis_step_report`

The same principle scales from a single step to an entire deliverable
protocol. The two synthesis protocols that produce visual artefacts sit
at opposite ends on purpose:

* **`synthesis_dashboard`** carries a `required_structure` and an
  archetype menu. That's deliberate prescription (see *When prescription
  IS the right answer*): a dashboard is a known genre with load-bearing
  conventions — a filter bar, an evidence grid, drill-downs — and a
  researcher reaching for one expects that shape.

* **`synthesis_step_report`** is the canonical **guidance-first**
  protocol. It has **no `required_structure`, no `forbidden_structure`,
  no archetype menu**. It frames the work entirely through
  `design_principles` (honesty, grounding, one-glance hierarchy,
  travels-as-one-file) and `quality_standards` (a11y baseline, offline
  safety, no placeholders, every number traceable to the step's
  `conclusions.md`). The scaffold the tool writes is a *minimal shell* —
  palette tokens, an accessibility baseline, offline safety, and the RO
  house identity — with the design intent left in comments only. The AI
  invents the layout and sections that tell THIS step's story fastest.

The lesson: prescribe structure only when the genre's conventions are
load-bearing. When the right shape depends on the specific findings —
as it does for a per-step report — give the AI principles and a quality
bar, then get out of its way. The gate (`_check_step_report`) enforces
the *bar* (honesty, grounding, accessibility, offline, no placeholders),
never a heading list.

## `next_protocol_kind` — how the AI should interpret `next_protocol`

`next_protocol:` alone is ambiguous: does the AI **advance forward** to
the next stage, **loop back** to the same protocol for the next item, or
**stop** because this protocol is terminal? Add `next_protocol_kind:` to
disambiguate. Values:

| Value | When to use |
|---|---|
| `forward_default` | The named protocol is the next stage in the canonical pipeline. The AI advances. This is the most common case. |
| `iterate_back` | `next_protocol` points back at THIS protocol (or a sibling that re-enters this one's loop). The AI re-runs the same protocol on the next item / step / hypothesis until the researcher says to stop. Example: `guidance/analysis_plan` after one step is done — the AI loops back for the next step, not forward to reproducibility. |
| `terminal` | This protocol ends the workflow. `next_protocol:` should be `null`. The AI stops and reports the deliverable. Example: `synthesis/synthesis_paper` after the paper compiles. |

```yaml
id: guidance/analysis_plan
next_protocol: guidance/analysis_plan      # loops back per step
next_protocol_kind: iterate_back

id: domain/research_design
next_protocol: methodology/methodology_selection
next_protocol_kind: forward_default

id: synthesis/synthesis_paper
next_protocol: null
next_protocol_kind: terminal
```

The field is OPTIONAL but recommended for any protocol whose default
routing would confuse a fresh AI. When omitted, the AI infers:

- `next_protocol: null` → `terminal`
- `next_protocol` equals this protocol's own `id` → `iterate_back`
- otherwise → `forward_default`

Preflight emits a soft warning when a protocol is missing the field but
the inference would have flipped the AI's behaviour (e.g. a step-loop
protocol whose `next_protocol` points sideways at a sibling, not
backward at itself).

## Cross-referencing protocols (`see_also`, optional)

A growing protocol library is only useful if a researcher (or the AI
following a protocol) can find adjacent work without scanning every
file. The recommended convention for cross-references is a top-level
`see_also:` field carrying a short list of related protocol IDs.

```yaml
id: methodology/missing_data_strategy
name: "Missing-data strategy"
version: '1.9.3'
see_also:
  - methodology/multiple_comparisons     # both shape the analysis plan
  - audit/preregistration                # missingness assumptions belong in the prereg
  - methodology/sensitivity_analysis     # sensitivity sweep tests robustness
steps: ...
```

**When to populate `see_also`:**

- The reader of THIS protocol almost always needs ONE of those other
  protocols within the same session (sequential or branching).
- The protocols share a foundational artefact (a registered plan, a
  shared assumption log, a common output the reader will return to).
- The relationship is non-obvious — the trigger phrases of the related
  protocol wouldn't surface it via `tool_route` on their own.

**When NOT to add `see_also`:**

- The related protocol is already reachable via `next_protocol`
  (that's the linear successor; `see_also` is for lateral siblings).
- The relationship is "any audit protocol" or "any synthesis protocol"
  — too coarse to be actionable.
- You're padding to make a protocol look thorough. Empty / blank
  `see_also:` is a docs smell; better to omit the field.

**Status (v1.9.3):** the field is documented but not yet wired into
any tool or auto-rendered surface. A future release may surface
`see_also` in `sys_protocol_get format='summary'` and in the workflow
DAG. Adding `see_also` to your own protocols today is a low-risk
investment — the schema accepts the field; downstream tools will pick
it up when they're built.

## Autonomy gates — name the risk, let adaptive resolve it

Many protocols pause at a decision point with an `AUTONOMY GATE:` block.
The default autonomy level is **adaptive**: it flows on cheap, reversible
moves and pauses only on the handful that are irreversible, expensive, or
spend real money. A gate that only addresses `manual / supervised` and
`autopilot` leaves the default-level AI to guess — so every gate must
**name the risk dimension** and say how adaptive resolves it.

The canonical idiom:

```yaml
AUTONOMY GATE:
  Risk: <reversible+cheap | irreversible | expensive but re-runnable | spends real money>.
  adaptive (default) → <flow / pause>, judged from THIS action's
    reversibility + cost, not from a fixed rule.
  manual / supervised → <what to present and confirm before acting>.
  autopilot → <proceed, and what to log / flag>.
```

This is scaffold language, not a recipe: the gate names the *dimension*
(is this action reversible? what does it cost?) and leaves the AI to
judge whether THIS instance clears the bar. Match the verbs to the
engine's enforced floors (`server/autopilot_gate.py`): truly
irreversible / real-money actions pause even on the loosest setting;
expensive-but-re-runnable actions pause at the normal floor; reversible
actions flow. A gate whose `adaptive` line contradicts the engine's
floor for the same action is a bug — reconcile the prose to the floor,
not the floor to the prose.

When a step's action is plainly reversible and cheap (drafting, EDA,
writing a figure, scoping an increment), it does not need a gate at all;
adaptive flows through it. Reserve gates for the moves where pausing
actually protects something.

## Tools verify recorded work — they never do the science

Research-OS tools provide **state, provenance, gates, routing, and
search**. They do NOT perform the researcher's analysis. A tool must
never compute a finding, run a statistical test, solve for a quantity,
or decide a verdict from raw data — that is the AI's job to create, on
the researcher's behalf, in the AI's own code.

The audit gates make this concrete. They follow the `audit_citations`
shape: read the artefact the AI produced, check that each expected
element is present and interpreted, write a report, and return
`recorded` / `missing` (or `verified` / `unverified`). They do not
generate the artefact.

- `audit_power` does NOT solve for power. It reads the AI's power /
  sample-size justification and verifies it records the test family,
  the effect size **and its source**, alpha, n, and the target power
  with a conclusion.
- `audit_assumptions` does NOT run Shapiro / Levene / Breusch-Pagan /
  Durbin-Watson / VIF / Cook's. It reads the AI's diagnostics record
  and verifies each named check has a statistic, an interpretation,
  and — for any violation — a recorded response.

The litmus test: **if removing the tool would change a scientific
result, the tool was doing the science and is wrong.** Removing a
verify-gate only removes the check that the work was recorded — the
result itself is untouched, because the AI computed it. Arithmetic
conversions that merely restate the AI's own inputs (e.g. an E-value
from a reported risk ratio) are not "doing the science" and are fine.

## The schema: YAML is the format, the Pydantic model is the contract

As of 5.0.0 (`schema_version: '3.0'`) every protocol validates against a
single typed **`Protocol`** model (`schema/protocol.py`), and every tool
call / result / routing decision travels in a typed **envelope**
(`schema/envelope.py`: `ToolCall`, `ToolResult`, `RoutingDecision`,
`Envelope`). The routing fields that once lived in a separate
`_router_index.yaml` (`intent_class`, `sub_intent`, `triggers`,
`decomposition`, `tier`) now live **inside each protocol body** and are
part of that model. Preflight validates all 158 protocols against it and
rebuilds the single `_protocols.bundle` sidecar from the YAMLs.

This does **not** change the doctrine. The model is the *schema*; YAML is
the *format*. Protocols stay soft scaffolds for reasoning — the typed
envelope hardens the *transport* (what a tool call looks like on the wire,
what a result must carry) while the *reasoning* it carries stays as open
as this whole document demands. Hard structure at the seam; soft reasoning
inside it. See `docs/SCHEMA.md` for the full model reference.

## No version commentary in live bodies

Protocol bodies, MCP tool descriptions, and code docstrings/comments
must read as **timeless current doctrine**. They describe what the
system does NOW. They do not narrate which version added which rule
or which version fixed which bug.

**Where version history lives:**

| Surface | Carries |
|---|---|
| `CHANGELOG.md` | What changed in each release, with rationale |
| `git log` / `git blame` | Line-level provenance |
| `version:` (protocol YAML) | Which package release this protocol shipped with |
| `schema_version:` (protocol YAML) | Bumps only when prescriptive structure changes |
| `last_reviewed:` (protocol YAML) | When a maintainer last read this for staleness |

**What stays out of live bodies:**

- "`v1.4.0` added X" / "`v1.5.0` fixed Y" / "as of `v1.3.4` we …"
- "previously this clobbered, now we …"
- "promoted from WARN to BLOCK in `v1.5.0`"
- "the `v1.3.4` stress test caught this"
- "carried over from the `v1.5.1` stress audit"

**Why:** every load of a live doctrine surface pays the token cost.
A 13-protocol routing call that has 200 lines of version chatter
strung across the protocols burns ~3 KB of context on history the
reader can't act on. The CHANGELOG already carries the history;
readers who need it know where to find it.

**The rule for inline WHY comments.** Comments that explain a
*non-obvious mechanical reason* a piece of code looks the way it
does (a workaround, a subtle invariant, a hidden constraint) stay.
Comments that *narrate* the project history ("`v1.3.4` added this
because the `v1.3.3` stress test surfaced…") get stripped down to
the timeless WHY: "this matches `^##\s` not `^##` so that `###`
sub-headers don't truncate the parent section."

**Enforcement.** `scripts/lint_no_version_chatter.py` scans the live
surfaces (protocols/, server.py, tools/actions/, project_ops.py,
wizard.py) and flags `v\d+\.\d+(?:\.\d+)?` references plus the
common "previously this / was the bug / promoted from WARN to BLOCK
in vX" phrasings. Run with `--strict` to fail on any hit; run with
`--diff` to fail only on hits in files modified relative to HEAD.
Preflight invokes it in `--diff` mode so new commits can't introduce
new chatter without the maintainer noticing.

---

If you read a step in a protocol that fails the checklist above,
file the rewrite or do it yourself. The point of this file is that
the principle outlives any one person editing the codebase.
