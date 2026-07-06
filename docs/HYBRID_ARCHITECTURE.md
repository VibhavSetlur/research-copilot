# Hybrid architecture — protocols declare, the daemon enforces

## The problem, stated precisely

Research-OS today has two layers that are good in isolation but talk past
each other:

* The **MCP + protocols** are excellent *reasoning scaffolds*. The
  protocol doctrine (`docs/PROTOCOL_DOCTRINE.md`) is right: a protocol
  names the questions, dimensions, grounding, and artefacts; it must NOT
  name the method, tool, threshold, or step sequence. That softness is a
  feature — reasoning generalises, recipes rot.

* The **daemon** is the enforcement kernel / agent layer: a process the
  agent does not control, which holds the things the agent must not be
  able to forge (see `UNSKIPPABLE_GATES.md`).

The friction the user named: *"protocols existing in the MCP only is not
good enough."* Some of what a protocol says is genuine reasoning scaffold
(keep it soft). But some of what a protocol says is **not reasoning at
all — it is a rule about the system** that is currently expressed as soft
prose and therefore skippable.

The sharpest example is `guidance/autopilot.yaml`. Its `mandatory_gates`
step is ~35 lines of prose listing 8 actions that MUST stop and ask. That
prose is duplicated, by hand, as Python in
`server/autopilot_gate.py` (`_ALWAYS_GATED`, `_gate_key`,
`_GATE_FLOOR`, `_requires_confirmation`). **Two sources of truth, synced
by a human, guaranteed to drift.** When they drift, either the prose
lies (a gate the engine doesn't enforce) or the engine surprises (a gate
the prose never documented). Both are silent corner-cutting risks.

The doctrine already draws the exact line we need (PROTOCOL_DOCTRINE.md
§"When prescription IS the right answer" and §"Tools verify recorded
work"):

> prescription about WHO uses what tool is bad; prescription about HOW
> the system records [and gates] the work is good.

So the partition is not "move protocols into the daemon." It is:

* **Reasoning content stays soft prose in the MCP.** The AI must keep
  filling in method/threshold/sequence per project. Hardening this would
  destroy the system's value.
* **System rules (gates, floors, required artefacts, consent points)
  become machine-readable structure** that the protocol *declares* and
  the daemon/engine *enforces* — one source of truth, authored where the
  domain knowledge lives (the protocol), enforced where it can't be
  forged (the engine, and the daemon when present).

This is the hybrid: the protocol is still the author of intent; the
engine compiles the enforceable subset out of it; the daemon makes that
subset un-skippable. No prose/code drift, because the prose IS the code's
source.

## The contract — `enforcement:` block on a protocol

A protocol MAY carry a top-level `enforcement:` block. It is OPTIONAL
(every existing protocol without one behaves exactly as today). It is the
*machine-readable* statement of the protocol's hard rules. Shape:

```yaml
enforcement:
  gates:
    - key: tool_audit:reproducibility   # stable identity for this gate
      tool: tool_audit                  # tool this gate intercepts
      when:                             # arg-match predicate (all must hold)
        scope: step
        dimension: reproducibility
      floor: normal                     # light|normal|strict (adaptive tier)
      reason: reproducibility audits are slow + expensive
    - key: tool_package_install
      tool: tool_package_install
      when: {}                          # empty = always, regardless of args
      floor: light
      reason: installs mutate the environment irreversibly
```

`when` predicate semantics (deliberately small — only what the existing
floor needs, so it stays a *declaration* not a DSL):

| Predicate form | Meaning |
|---|---|
| `key: value` | `str(args.get(key)) == value` |
| `key: [v1, v2]` | `str(args.get(key)) in {v1, v2}` |
| `key: {truthy: true}` | `bool(args.get(key)) is True` |
| `key: {path_prefix: synthesis/, exists: true, when_arg: force}` | the synthesis-force-write special case: `force` truthy AND target under `synthesis/` AND already exists |
| `when: {}` | always fires for this tool |

`floor` is the adaptive-strictness tier the gate fires at, identical to
today's `_GATE_FLOOR` semantics (`light` ⊂ `normal` ⊂ `strict`).

## The compiler — `_protocols.bundle`

After Protocol Unification (P1) there is ONE build step
(`scripts/build_protocols.py`) that scans every protocol's
`enforcement.gates`, validates them against the `Protocol` model, and
folds the compiled gate list into the single msgpack bundle:

```
src/research_os/protocols/_protocols.bundle   (gates: [...] block)
```

Each gate entry:

```json
{"key": "...", "tool": "...", "when": {...}, "floor": "...",
 "reason": "...", "source_protocol": "guidance/autopilot"}
```

The engine reads the compiled bundle via `ProtocolRegistry.get_gates()`
— NOT the YAML at runtime, and no separate `_gate_meta.json` sidecar.
Cheap, no YAML parse on the dispatch hot path, deterministic.

## Engine refactor — autopilot_gate reads the compiled gates

`server/autopilot_gate.py` keeps its public surface
(`enforce_autopilot_gate`, `_gate_key`, `_requires_confirmation`,
`_GATE_FLOOR`) so nothing downstream breaks, but the hand-maintained
constant tables become *derived* from the compiled bundle:

* `_load_gate_meta()` reads the gates from `ProtocolRegistry.get_gates()`
  (bundle-backed, cached), fails SAFE to `[]` if the bundle is
  missing/garbage.
* `_gate_key`, `_requires_confirmation`, `_GATE_FLOOR` are computed from
  the loaded gates via the small `when`-predicate evaluator.
* The synthesis-force-write existence check (needs `root`) stays a
  predicate kind, evaluated against the live args + root.

Net effect: the 8 floor gates are now declared once, in
`guidance/autopilot.yaml`, and the engine + daemon enforce exactly what
the protocol declares. Edit the protocol, rebuild the bundle, the floor
moves with it. The prose and the floor can no longer disagree, because a
preflight check asserts the compiled gates match what the engine resolves
AND that the gate keys referenced in prose exist in the block.

## Drift guard — preflight

The preflight checks (`scripts/preflight.py`) assert:

1. `_protocols.bundle` is in sync with the protocol YAMLs
   (`check_bundle_fresh`: source-hash match → rebuild leaves no diff).
2. Every protocol validates against the `Protocol` model
   (`check_protocols_validate`), so a bad gate floor / check kind can't
   ship.

Preflight already gates every release; these make prose/code drift
impossible to merge.

## Why this is the right merge (and not over-reach)

* **It does not harden reasoning.** Only the `enforcement:` subset — the
  "system rules" the doctrine already says should be prescriptive — gets
  compiled. Method/threshold/sequence stay soft. We are formalising the
  part that was *already* hard-coded in Python, just moving its source of
  truth to where the intent lives.
* **It does not break existing flows.** The block is optional; protocols
  without it are untouched. The engine falls back to today's exact tables
  if the sidecar is absent. When no daemon runs, the gate still degrades
  to `confirmed=true` (UNSKIPPABLE_GATES.md constraint #2). stdio-only
  users see zero change.
* **It makes the daemon a true enforcement layer over the MCP.** The
  daemon already mints consent tokens for floor gates (UNSKIPPABLE_GATES).
  Now the *set* of floor gates is itself declared by protocols and
  compiled — so as the protocol library grows, new hard gates a protocol
  declares are automatically enforced + made un-skippable by the daemon,
  with no second edit to Python.
* **It removes a whole class of bugs.** Prose/code drift on gates is
  gone. One source, compiled, drift-guarded by preflight.

## Future protocols can declare gates too

Once the contract exists, any protocol — not just autopilot — can declare
an `enforcement.gates` entry for an action that protocol considers a hard
floor (e.g. a clinical protocol that must gate an irreversible data
purge). It compiles into the same sidecar and is enforced + made
un-skippable for free. This is the growth path: the MCP stays the place
domain experts write rules; the daemon stays the place those rules are
enforced.

## Build order

1. This doc.
2. `enforcement:` schema + the `when`-predicate evaluator (pure stdlib,
   `server/gate_spec.py`, no daemon import — same seam as consent).
3. `scripts/build_protocols.py` compiler → the `gates` block in
   `_protocols.bundle`.
4. Add `enforcement.gates` to `guidance/autopilot.yaml` declaring all 8
   gates; rebuild; assert the compiled set == today's legacy tables byte
   for byte (the safety proof: zero behaviour change).
5. Refactor `autopilot_gate.py` to derive from the sidecar, legacy tables
   kept as fail-safe fallback.
6. Preflight drift guard.
7. Tests + full release gate + live verify identical behaviour.
```
