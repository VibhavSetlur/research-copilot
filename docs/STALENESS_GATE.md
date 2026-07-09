# Staleness gate — don't let the AI ship a result built on changed data

## The pain (concrete, named)

A computational researcher's worst silent failure: a figure or table in
the final paper was computed from an input file that has since changed on
disk. The number in the PDF no longer matches the data. Nobody notices
until a reviewer (or worse, a reader) can't reproduce it.

Research-OS already *detects* this. The daemon's lineage + staleness
modules (`daemon/lineage.py`, `daemon/staleness.py`) hash every run's
recorded inputs and flag a run as **input-stale** (a direct input changed)
or **transitive-stale** (an upstream run it depends on is stale). The
`/v1/staleness` endpoint and the `staleness` CLI surface the verdict.

But detection is *passive*. Nothing stops the AI from running
`tool_typst_compile` on the final paper while results are stale. The
`guidance/autopilot.yaml` `final_deliverable_gate` step is prose:
"tool_synthesis_check passes, citations audit passes" — it never mentions
staleness, and even if it did, prose is skippable (the exact problem the
hybrid gate layer fixed for *action* gates).

This is failure mode #4 (silent corner-cutting & data tampering) in its
purest form: the system *knows* the result is built on changed data and
lets it ship anyway.

## The fix (one sentence)

Make "no stale inputs feed this deliverable" a HARD, declared floor gate
on the final-deliverable compile — so when a daemon is enforcing, the AI
literally cannot compile a paper built on data that changed, until the
staleness is resolved (re-run the affected steps) or explicitly
overridden through the daemon consent authority.

## Why this is the natural next step

The hybrid gate layer (HYBRID_ARCHITECTURE.md) made *action* gates
declarative: "is THIS action dangerous?" (compile, install, rollback…).
This feature generalises the gate from the action to the **world state**:
"is the world in a safe state for this action?" Same machinery — a
declared gate in a protocol, compiled into `_gate_meta.json`, enforced by
the engine and made un-skippable by the daemon — but the predicate now
consults *detected world state* (the staleness verdict) instead of only
the call's arguments.

## The contract — a daemon-owned staleness verdict sidecar

The gate runs in-process (reasoning side) and must NOT import the daemon
(the preflight-enforced seam). The staleness assessment needs the run
journal + on-disk hashing, which lives on the daemon side. So we use the
same on-disk-contract pattern as consent:

  .os_state/staleness/verdict.json   (daemon-written, gate-read)

Shape:

```json
{
  "schema": 1,
  "assessed_at": "2026-06-23T...Z",
  "status": "stale" | "fresh",
  "counts": {"total": N, "stale": K, "fresh": M, "unknown": U},
  "stale_runs": ["run_id", ...],
  "stale_outputs": ["workspace/03_.../figure.png", ...]
}
```

The daemon writes this whenever it assesses staleness (via a bearer-token-gated
mutating daemon endpoint; the existing read-only `GET /v1/staleness` is
unchanged). This is daemon job/status plumbing, not an LLM gateway. The gate
reads it by SHAPE, fail-safe.

### Fail-safe direction — the subtle part

For *consent*, fail-safe = closed (no token → refuse). For *staleness*
the safe default is the OPPOSITE in one specific way, and we must be
deliberate:

* If the verdict sidecar is ABSENT or unreadable → the gate does NOT fire.
  Rationale: most projects never run a daemon; a freshness gate that fired
  on every project that never computed a verdict would brick the default
  flow and violate the backward-compat constraint. Absence of a verdict =
  "no staleness claim available" = don't block. This matches the
  daemon-present/absent degrade everywhere else across the system.
* If the verdict sidecar EXISTS and says `status: stale` → the gate FIRES.
  A daemon has affirmatively determined results are stale; shipping anyway
  is the failure we're preventing.
* A stale verdict that is itself OLD (older than the newest run) is
  ignored — it predates the current state and can't be trusted. The
  reader treats a verdict older than the freshest run manifest as absent
  (no claim), so a resolved-then-recomputed project isn't blocked by a
  stale *verdict*. (Freshness-of-the-freshness-check.)

So: the gate only blocks when a daemon has *currently* determined the
project is stale. That is a high-signal, low-false-positive trigger.

## The predicate — `world_state` kind in gate_spec

`server/gate_spec.py` gains one predicate clause kind:

```yaml
when:
  world_state: no_stale_inputs
```

`world_state: no_stale_inputs` matches (gate fires) when the staleness
reader returns a CURRENT verdict with `status == "stale"`. It does NOT
match (gate does not fire) when the verdict is absent/old/fresh. The
reader lives in `server/staleness_state.py` (stdlib, no daemon import,
mirrors `server/consent.py`).

## The declaration — autopilot.yaml

Add one gate to the `enforcement.gates` block:

```yaml
- key: tool_typst_compile:stale_inputs
  tool: tool_typst_compile
  when:
    world_state: no_stale_inputs
  floor: normal
  reason: >-
    the final deliverable would embed results built from inputs that
    changed on disk; re-run the affected steps (or override) first
```

Note `tool_typst_compile` already has an unconditional `normal` gate
(every final compile pauses). This second gate is ADDITIVE and orthogonal:
the unconditional one asks "is the researcher ready to make this
shareable?"; the staleness one asks "is the underlying data still valid?".
Two distinct keys, two distinct reasons in the consent prompt, so the AI
(and the human approving) sees exactly *why* it stopped. A gate key may
be globally unique (compiler enforces) — these two differ
(`tool_typst_compile` vs `tool_typst_compile:stale_inputs`).

When the staleness gate fires under a daemon, clearing it requires a
daemon-minted consent token bound to the stale-inputs gate key — i.e. a
human explicitly says "yes, ship it anyway" — OR the researcher resolves
the staleness (re-runs the steps), the daemon re-assesses, the verdict
flips to fresh, and the gate stops firing on its own. Both paths are
honest; neither is the AI grading its own homework.

## Backward compatibility

* No daemon, no verdict file → zero change (gate never fires; today's
  flow exactly).
* Daemon present but project never assessed → no verdict → gate doesn't
  fire (no false positives).
* Existing `tool_typst_compile` unconditional gate untouched.
* `world_state` is a new optional predicate kind; every existing gate is
  unaffected. Unknown predicate kinds already fail closed in gate_spec
  (no accidental new gates).

## Build order

1. This doc.
2. `daemon/staleness.py`: `write_verdict(root, report)` — atomic write of
   the sidecar from an `assess()` report. `POST /v1/staleness/verdict`
   endpoint that assesses + persists + returns the verdict.
3. `server/staleness_state.py`: reader (`current_stale_verdict(root)`)
   that loads the sidecar, drops it if older than the freshest run, returns
   status. Fail-safe to "no claim".
4. `server/gate_spec.py`: `world_state` predicate kind → consult reader.
5. `autopilot.yaml`: declare the staleness gate; rebuild `_gate_meta.json`.
6. Tests + live daemon round-trip + full release gate.
```
