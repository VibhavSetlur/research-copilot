# Precondition gate — protocols declare what must be true, the daemon verifies

Status: shipped (both tiers) — `requires:` blocks compile to
`_precondition_meta.json`; `server/preconditions.py` surfaces unmet checks
(tier 1, always on); `world_state: preconditions_met` gates them when a
daemon enforces (tier 2). Guarded by preflight `check_precondition_meta`.

## The pain (multi-persona)

108 protocols declare a `prerequisites:` block — "what must be true before
running this." Today it is PROSE shown to the AI and trusted. Nothing
verifies it. Seen from four seats:

* **Naive AI under context pressure** enters `guidance/analysis_plan` and
  starts running analysis before `workspace/methods.md` exists — because the
  prerequisite was a sentence it skimmed, not a checked fact. The work is
  built on a missing foundation.
* **Grad student** doesn't know the pipeline order, trusts the AI, and ends
  up with synthesis written before there was anything substantive to
  synthesize. They can't tell until a reviewer does.
* **PI (the reviewer-of-record)** needs the project to be *trustworthy*:
  steps done in a valid order, foundations in place. "The AI said it was
  ready" is not evidence.
* **Skeptical external reviewer** asks "did methods exist before the
  analysis ran?" There is no answer — only the AI's claim.

This is the same soft→hard gap the gate work closed, applied to the most
universal soft rule in the system: a protocol's own entry conditions.

## The fix (one sentence)

Let a protocol DECLARE its preconditions as machine-readable checks
(parallel to `enforcement.gates`), compile them into a sidecar, and have a
precondition verifier confirm them against the workspace before the
protocol's work proceeds — so "you must have done X first" becomes a
checked fact, not a trusted sentence.

## What stays soft (important)

Many prerequisites are genuinely fuzzy and SHOULD stay prose: "at least one
*substantive* artefact", "research_overview.md is *non-placeholder*".
"Substantive" is a judgement the AI must make — hardening it would be
exactly the over-reach the doctrine warns against. So the `requires:` block
is OPTIONAL and holds only the MECHANICALLY checkable subset:

  * a file exists / is non-empty
  * a prior protocol has been logged as completed
  * a state field has a value
  * a glob matches at least N files

The prose `prerequisites:` stays as the human/AI-facing rationale (and
carries the fuzzy ones). `requires:` is the enforceable floor underneath
it — same relationship as `mandatory_gates` prose ↔ `enforcement.gates`.

## The contract — `requires:` block on a protocol

```yaml
requires:
  checks:
    - kind: file_exists
      path: workspace/methods.md
      non_empty: true
      because: the analysis plan builds on recorded methods
    - kind: protocol_completed
      protocol: literature/literature_search
      because: the plan cites the literature it must first gather
    - kind: glob_min
      pattern: inputs/**/*
      min: 1
      because: synthesis needs at least one input artefact
    - kind: state_field
      field: research_question
      because: every plan answers a stated question
```

Check kinds (deliberately small, mechanical only):

| kind | passes when |
|---|---|
| `file_exists` | `<root>/path` exists (and is non-empty if `non_empty: true`) |
| `glob_min` | `<root>` glob matches ≥ `min` files |
| `protocol_completed` | the named protocol appears completed in the execution log |
| `state_field` | the named field in the research ledger is set + non-empty |

Every check carries `because:` — the reason surfaced to the AI when it
fails, so the next action is obvious ("run literature_search first").

## The compiler — `_protocols.bundle`

`scripts/build_protocols.py` scans every protocol's `requires.checks`,
validates, and folds them into the `preconditions` block of the single
`protocols/_protocols.bundle` (P1 — the same build that compiles routing
+ gates). It also verifies every referenced `protocol_completed` target
is a real protocol (no dangling references). `server/preconditions.py`
reads them via `ProtocolRegistry.get_preconditions()`. Preflight
`check_bundle_fresh` + `check_protocols_validate` guard freshness +
validity.

## The verifier — `server/preconditions.py` (reasoning side, no daemon import)

`unmet_preconditions(protocol_id, root) -> list[dict]` loads the compiled
checks for that protocol and evaluates each against the workspace. Pure
stdlib, fail-safe: an unreadable sidecar or workspace yields "no claim"
(empty list → nothing blocked), so a project without compiled preconditions
behaves exactly as today.

## Enforcement — two tiers, same fail-safe ladder as the gates

1. **Soft surfacing (always on, no daemon needed).** `load_protocol` /
   `sys_protocol_get` already returns `prerequisites`. It now also returns
   `unmet_preconditions` — the concrete failed checks — so even a stdio-only
   AI is told precisely what is missing instead of a vague sentence. This
   alone is a large UX win and breaks nothing.

2. **Hard gate when a daemon is enforcing.** SHIPPED as the
   `world_state: preconditions_met` gate predicate (parameterised form:
   `{kind: preconditions_met, protocol: <id>}`). A protocol can declare a
   floor gate on its own first mutating tool that fires when its
   preconditions are unmet — riding the existing consent authority, so the
   AI must satisfy the foundation or obtain a daemon-minted override. Reuses
   the gate machinery from the hybrid layer; no new enforcement code.

Tier 1 ships first (pure win, zero risk). Tier 2 composes the precondition
verdict into the declared-gate `world_state` predicate family
(`world_state: preconditions_met`), so it rides the rails already built.

## Backward compatibility

* No `requires:` block → today's behaviour exactly (prose only).
* No daemon → tier-1 surfacing only; nothing blocks.
* Fuzzy prerequisites stay in prose; only mechanical checks are declared.
* Additive sidecar + optional block; existing protocols untouched.

## Build order

1. This doc.
2. `server/preconditions.py`: check evaluator + `unmet_preconditions`
   (pure, stdlib, no daemon import).
3. `scripts/build_protocols.py` → `preconditions` block in
   `_protocols.bundle`.
4. Wire `load_protocol` to surface `unmet_preconditions` (tier 1).
5. Preflight `check_bundle_fresh` + `check_protocols_validate`.
6. Declare `requires:` on a high-traffic protocol (analysis_plan) as the
   first real example; verify surfacing works end to end.
7. Tier 2: `world_state: preconditions_met` predicate so a daemon can gate
   on it (reuses the consent authority).
8. Tests + full release gate.
