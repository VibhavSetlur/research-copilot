# Research OS — Public Contract (v2)

This is the **integrator contract**. It pins which parts of Research OS
are stable across releases, which can move under SemVer-MINOR, and
which are internal. If you wrap, embed, or build on top of Research OS
(another MCP client, a CI bot, a lab IDE, a hosted service), read this
before pinning to a version.

The contract is **part of the public API** — changes to this file are
themselves SemVer-gated. A change to the STABLE section here is a
MAJOR-bump signal.

**v2.0.0 status:** the surfaces in section A below are FROZEN for the
v2.0.x patch line and v2.x minor series. Pin `~= 2.0` and the listed
guarantees hold. The v2.0.0 release ships with a documented YELLOW
caveat on absolute quality targets (see
`CHANGELOG.md [2.0.0]`); none of the
deferred items affect the contract surface.

Versioning rules (see also [RELEASING.md](RELEASING.md)):

| Bump | Means |
|---|---|
| MAJOR (`2.x → 3.0.0`) | Anything in section A changed in a way that breaks an existing well-behaved client. |
| MINOR (`2.0.0 → 2.1.0`) | Section B changed — surface grew, no rename, no removal. |
| PATCH (`2.0.0 → 2.0.1`) | Section C changed — internals only. |

---

## A. STABLE surface (MAJOR-bump required to change)

If you depend on any of the below, you can pin a `~=X.Y` range and
trust nothing here moves under you.

### A.1 Public tool names and input schemas

Public tool-name prefixes:

* `sys_*` — system / state / config / packs / files / help / boot.
  Examples: `sys_boot`, `sys_state_get`, `sys_protocol_get`,
  `sys_tool_describe`, `sys_packs_installed`, `sys_help`, `sys_path`,
  `sys_config`, `sys_env`, `sys_active_tools`.
* `tool_*` — workflow tools (routing, audits, synthesis, viz, search,
  exec, pack-contributed). Examples: `tool_route`, `tool_synthesis_check`,
  `tool_audit`, `tool_audit_quality_full`, `tool_audit_findings`,
  `tool_plan`, `tool_data`, `tool_typst_compile`, `tool_figure_palette`,
  `tool_search`, `tool_lessons`, `tool_step`, `tool_step_pipeline`,
  `tool_protocols_list`, `tool_tools_list`, `tool_<pack>_*` for
  pack-contributed tools.
* `mem_*` — memory / log writers. Examples: `mem_log`,
  `mem_citations_generate`, `mem_intake_regenerate`,
  `mem_hypothesis_add`, `mem_hypothesis_list`.

Stability guarantee: a tool that ships in `vX.0` is callable by the
same name with the same required input schema for the rest of the
`vX` line. New optional kwargs may appear (MINOR). Renames or
required-field changes are MAJOR. Deprecated names live on as
aliases for one MAJOR line: v2.0.x dispatches 78 deprecated names
via `_DEPRECATED_ALIASES` + `_ALIAS_PARAM_INJECTION`; the v1.6.1
first-wave aliases (21 names — see Phase 14a in
`CHANGELOG.md [2.0.0]`) were hard-removed
in v2.0.0 after their 4-minor-version deprecation runway.

Every tool definition carries MAJOR-stable metadata fields; these
fields are stable across the public tool surface:

* `status` — `live` (visible in `list_tools`) / `alias` (back-compat
  pointer) / `deprecated` (callable, telemetry to
  `.os_state/deprecations.log`). `list_tools` returns `status='live'`
  only.
* `pack` — `core` or one of the domain packs (`humanities`,
  `qualitative`, `theory_math`, `wet_lab`, `engineering`) or the
  infrastructure adapters (`slurm`, `snakemake`, `nextflow`,
  `cytoscape`, `redcap`, `synapse`). Adding a new pack or adapter
  label is MINOR; renaming or removing an existing one is MAJOR.

The canonical, machine-readable list is whatever
`sys_tool_describe`, `tool_tools_list`, and the MCP `tools/list`
handshake return for the running server — a core set plus tools
contributed by the domain packs and infrastructure adapters above.
Query the running server rather than relying on a hand-maintained
inventory.

### A.2 Audit-finding JSON schema

`src/research_os/schemas/audit_finding.schema.json` (JSON Schema
draft-07). Every audit emits a list of objects validated against
this schema. Required fields — `id`, `audit_name`, `severity`,
`dimension`, `generated_at`, `ro_version` — are part of the stable
contract; adding a new optional field is MINOR, renaming or removing
any of the above is MAJOR. `severity` enum is fixed at
`block | warn | info`.

### A.3 `researcher_config.yaml` field names

The canonical schema lives in
`templates/researcher_config.yaml`. The following top-level
sections are stable in v2:

* `researcher`
* `licenses`
* `project_name`
* `workspace`
* `research_goal`
* `interaction`
* `gate_strictness`
* `project_tier`
* `model_profile`
* `ai`
* `writing_preferences`
* `runtime`
* `compute`
* `daemon`
* `figures`
* `synthesis`
* `api_keys`

Adding a new top-level section or a new key under an existing one is
**MINOR**. Renaming or removing any of the above is **MAJOR**.
Enums on `gate_strictness` (`light | normal | strict | auto`),
`project_tier` (`throwaway | sketch | production`),
`model_profile` (`small | medium | large`), `ai.model_profile`
(`small | medium | large`), and `ai.context_class` (`short | long`)
are stable.

### A.4 Workspace directory layout

Every project on disk has a fixed shape. Integrations may read or
write any of these paths.

```
<project>/
├── inputs/                      # source-of-truth + AI-maintained intake
│   ├── raw_data/                # soft-guarded after intake (force=true to overwrite)
│   ├── literature/              # soft-guarded after intake (force=true to overwrite)
│   ├── researcher_config.yaml   # see A.3
│   ├── intake.md                # filled by tool_intake_autofill
│   └── …
├── workspace/                   # all derived work
│   ├── 00_<step>/               # per-step subdirs
│   ├── methods.md
│   ├── analysis.md
│   ├── logs/                    # override_log.md, drafter_loops/, etc.
│   └── …
├── docs/
│   └── research_overview.md
└── .os_state/                   # private engine state — do not hand-edit
    ├── state.json
    ├── manifest.json
    ├── protocol_execution_log.jsonl
    ├── active_plan.json
    └── …
```

Renaming or relocating any of these directories is MAJOR. Adding a
new sibling directory or a new file inside `.os_state/` is MINOR.

### Protocol routing `intent_class` enum

`tool_route` resolves a researcher prompt down to one of ten L1
intent classes. The enum is fixed in v2:

```
session | discover | plan | execute | synthesize | audit_wrap |
methodology | literature | memory | review
```

Adding a new value is MAJOR (existing dispatch tables would not
handle it). Renaming or removing one is MAJOR. The `sub_intent` L2
vocabulary is intent-class-scoped and additions there are MINOR.

### Protocol `tier` enum

Every protocol carries a `tier:` annotation (v2.0.0 new) placing it
in the project lifecycle. The enum is fixed in v2:

```
intake | plan | execute | ground | synthesize | review | finalize
```

`tool_route` echoes the resolved protocol's tier in `why_matched` /
the response envelope. Adding a new tier or reordering is MAJOR.
The `current_tier` advance machinery in `tool_step_complete` reads
this enum.

### Tool response envelope contract

Every tool handler returns a v2.1.0 envelope (the helper
`research_os.server.envelopes._success` / `_error` produces it; every
handler funnels through these). The shape is part of the stable
surface — adding fields is MINOR; renaming or removing fields is MAJOR.

| Field | Type | Stability | Notes |
|---|---|---|---|
| `status` | `"success" \| "warning" \| "error"` | MAJOR-stable enum | |
| `payload` | dict (tool-specific) | MAJOR-stable name, MINOR-mutable content | new canonical key |
| `data` | dict (alias of `payload`) | DEPRECATED — removal slated for v3.0.0 | back-compat for v2.0 callers |
| `audit_findings` | list (default `[]`) | MAJOR-stable name | structured findings per A.2 schema |
| `next_recommended_call` | string \| null | MAJOR-stable name | literal next-tool-call hint (saves a round-trip) |
| `next_recommended_call_structured` | dict \| null | MAJOR-stable name | `{"tool": str, "arguments": dict}`; auto-derived from `next_recommended_call` when parseable, `null` for free-form hints. Strict tool-loop clients dispatch this directly. |
| `tier_transition` | string \| null | MAJOR-stable name | e.g. `"tier_execute -> tier_synthesize"` |
| `tokens_estimate` | int (≥ 0) | MAJOR-stable name | heuristic for client routing |
| `ro_version` | string (semver) | MAJOR-stable name | matches `research_os.__version__` |
| `error` | string | error envelopes only | composed WHAT/WHY/NEXT sentence |

Error envelopes additionally surface `payload.what`, `payload.why`,
`payload.next_action` for clients that want the parts separately, and
`payload.next_action` is promoted to envelope-level
`next_recommended_call` unless the caller overrides.

**Pack and adapter tools conform via a dispatcher-level normalizer.**
The legacy `{"status": "success", "data": {...}}` / `{"status": "error",
"error": "..."}` shape that bundled packs (humanities, qualitative,
theory_math, wet_lab, engineering) and bundled adapters (slurm,
snakemake, nextflow, cytoscape, redcap, synapse) historically returned
is upgraded to the v2.1.0 envelope by
`research_os.server.envelopes._normalize_envelope`, invoked once in
`dispatch._handle_tool_call` after the handler returns. New pack /
adapter code should call `research_os.server.envelopes._success` /
`_error` directly — see [`PLUGIN_AUTHORING.md`](PLUGIN_AUTHORING.md) —
but the normalizer guarantees no pack-tool response reaches a client
without the full envelope.

### A.6.2 RoError exception contract

Internal layers raise `research_os.server.errors.RoError(what, why=None,
next_action=None)`. The server dispatcher catches it and renders the
v2.1.0 error envelope above. The class + signature are MAJOR-stable
for plugin authors.

### A.7 `tool_route` response envelope (v2.0.0)

The `tool_route` response is part of the stable surface:

| Field | Type | Stability |
|---|---|---|
| `primary_protocol` | string \| null | MAJOR-stable |
| `recommended_action` | string | MAJOR-stable (literal next-call string) |
| `why_matched` | string | MINOR-mutable wording, MAJOR-stable presence |
| `tier` | string (one of A.6) \| null | MAJOR-stable |
| `alternatives` | list of `{primary_protocol, recommended_action, why_matched, tier}` | MAJOR-stable shape |
| `decomposition` | list of step dicts | MAJOR-stable shape |
| `complexity` | `low \| high` | MAJOR-stable enum |
| `ask_user` | string \| null | MAJOR-stable |
| `shortcut_tool` | string \| null | MAJOR-stable |

### A.8 MCP `instructions` field

The server emits an `instructions` field at MCP `initialize` time
naming the canonical boot ritual
(`sys_boot → tool_route → sys_protocol_get(format=summary) →
sys_active_tools`). The presence of the field is MAJOR-stable; the
prose is MINOR-mutable.

### A.9 Audit findings ledger location + format

The cross-audit append-only ledger lives at
`workspace/logs/.audit_findings.jsonl`. Schema, content, and read API
are stable in v2:

* Each row validates against
  `src/research_os/schemas/audit_finding.schema.json` (A.2).
* `id` is a stable UUIDv5 — re-emitting an unchanged finding does not
  create a new id.
* `tool_audit_findings(operation='query' | 'diff')` is the
  MAJOR-stable read API; querying with `severity='block'` returns
  the latest snapshot per stable id.
* The ledger path is the read surface; do not write to it from
  integrators.

---

## B. MINOR-changeable (additions OK; renames PATCH)

Anything in this section may grow without warning between MINOR
releases. Wrap defensively if you care.

* **Tool argument optional kwargs.** New optional kwargs may appear
  on any public tool. Default values are picked to preserve prior
  behaviour. Renaming an existing optional kwarg is **PATCH** during
  a pre-release window and **MAJOR** after one full MINOR line.
* **Audit prose wording.** The free-text `message` and
  `suggested_fix` fields on `AuditFinding` are MINOR-mutable. Don't
  parse them with regex; group on the stable `audit_name` +
  `dimension` + `severity` tuple instead.
* **Protocol body prose.** The `description`, `editorial_voice`, and
  step-`description` fields inside protocol YAMLs are MINOR-mutable.
  Stable: the protocol's `id`, `name`, fully-qualified address
  (`<category>/<name>`), step `id`s, and `expected_outputs` paths.
* **New protocols + new tools.** Always MINOR. The router may pick a
  new protocol for a phrase your client previously saw routed to an
  older one — that's expected. Pin on tool names + the router's
  returned `primary_protocol` if you need determinism.

## C. PATCH-changeable / internal

Anything below may move at any time, including within a PATCH bump.
Do not depend on it.

* **Internal module structure.** Imports from
  `research_os.tools.actions.*`, `research_os.project_ops`, helper
  classes inside `research_os.utils.*`, the internal layout of
  `research_os.server.*` (v2.0.0 dissolved `server.py` into a
  package; the top-level re-exports from `research_os.server`
  remain stable). Re-exports from `research_os.plugins` (the names
  listed in `__all__`) are stable.
* **Test fixtures, dev scripts.** Anything under `tests/`,
  `scripts/`, `tools/dev/` is dev-only and may be reorganised
  without notice. CI scripts under `.github/workflows/` are
  maintainer-owned.
* **Embeddings cache + on-disk index formats.** Files like
  `_embeddings.npz`, `.os_state/route_cache.sqlite`, plan-state
  internals — rebuilt on first server start of a new version.
* **CLI sub-command flags marked `(deprecated)`** — the wizard's
  `--workspace`, `--legacy-prompt`, etc.
* **`research-os doctor` check IDs and output prose.** The exit
  code (0 / 1 / 2) is MAJOR-stable; the per-check identifiers and
  human-readable messages may evolve under PATCH.

---

## D. OUT-OF-SCOPE (Research OS will NOT do)

These are non-goals. Don't file issues asking for them; build them
as adapter packs or external services that talk to Research OS.

* **LLM provider management.** Research OS never holds an Anthropic /
  OpenAI / Google / vLLM API key, never makes an inference call, and
  never streams a chat completion. The IDE owns model access.
* **Cloud infrastructure provisioning.** No Terraform, no Helm, no
  Pulumi, no "spin up an EC2 box for me." Use your infra tools.
* **Long-running compute scheduling.** Research OS will not run a
  three-day GPU job inside its own process. Use the `slurm`,
  `nextflow`, or `snakemake` adapter pack to dispatch + poll; the
  adapter speaks the contract on both ends.
* **Live collaboration.** No CRDTs, no presence, no real-time
  document editing. Two researchers should each operate their own
  Research OS workspace and merge via git.

---

## Reporting a contract violation

If a release breaks something in section A without a MAJOR bump,
that's a release-process bug. Open an issue tagged `contract` with:

1. The version that broke it.
2. The previous version that worked.
3. The exact failing tool call / config field / path.
4. A minimal repro (a YAML or a `tool_*` invocation).

The maintainer will yank the broken version and re-release with the
correct bump.

---

## E. Freeze snapshot reference

The release-time inventory snapshot is documented in
[`docs/_STALE_COUNTS_REFERENCE.md`](./_STALE_COUNTS_REFERENCE.md). Section A
forbids changing the structure that produced it under a MINOR / PATCH bump;
growth (e.g. adding a tool to `pack='theory_math'`) is MINOR.

Refer to the stale-counts reference for the current canonical counts and
historical snapshot notes.
