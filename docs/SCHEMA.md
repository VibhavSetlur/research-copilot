# Schema reference — the typed contract (5.0.0)

> Every protocol, tool call, result, and durable record in Research-OS
> validates against a **Pydantic model** in `src/research_os/schema/`. This
> is the *contract*; YAML/JSON are just the *format*. The models harden the
> **transport and structure** while the *reasoning* they carry stays soft
> (see [`PROTOCOL_DOCTRINE.md`](PROTOCOL_DOCTRINE.md)).
>
> **Research-OS calls no LLM and has no gateway.** None of these models
> describe a chat/completions surface — they describe tools, protocols,
> state, provenance, and the on-disk `.os_state/` seam the daemon reads.

The models live in `schema/` and are re-exported from `schema/__init__.py`.
`schema_version` for protocols is **`'3.0'`** as of 5.0.0.

---

## `protocol.py` — the central Protocol model

A protocol validates against **`Protocol`**. Routing fields that once lived
in a separate `_router_index.yaml` (deleted in the P1 phase) now live INSIDE
each protocol body and are part of this model.

| Model | Purpose |
|---|---|
| `Protocol` | One reasoning scaffold. Identity + routing + steps + gates + preconditions + outputs. |
| `ScopeTags` | Flexible `domain` / `phase` / `tools` tagging (extra keys allowed). |
| `PreconditionCheck` | A precondition that must hold before the protocol may run (`id`, `description`, `check`, `required`). |
| `Gate` | An enforcement gate guarding progression (`id`, `name`, `description`, `blocking`). |
| `Step` | One step within a protocol (`id`, `name`, `description`, `substeps`). |

**`Protocol` fields (abridged):**

| Field | Type | Notes |
|---|---|---|
| `id`, `name`, `version` | `str` | `version` = the package release this protocol shipped with. |
| `schema_version` | `Literal["3.0","2.0"]` | `"3.0"` today; `"2.0"` YAMLs fail validation → run `research-os migrate protocols`. |
| `tier` | `str` | One of the seven `Tier` values (see `tiers.py`). |
| `intent_class`, `sub_intent` | `str \| None` | Routing classification (moved in from the old router index). |
| `triggers` | `list[str]` | Phrases that route to this protocol. |
| `summary`, `description` | `str` | Human/agent-facing prose. |
| `shortcut_tool`, `token_estimate` | `str \| None`, `int \| None` | Routing hints. |
| `decomposition` | `str` | Suggested step sequence (soft). |
| `modes`, `scope_tags`, `see_also` | lists / `ScopeTags` | Applicability + cross-refs. |
| `prerequisites`, `steps`, `requires`, `enforcement` | lists | Body: preconditions (`requires`), steps, gates (`enforcement`). |
| `expected_outputs`, `on_failure`, `next_protocol` | | Outcome + routing continuation (`next_protocol` resolves to a real protocol or `null`). |

Preflight validates all **158 protocols** against `Protocol`, then builds the
single `_protocols.bundle` sidecar (route-meta + gate-meta + precondition-meta)
from the YAMLs, plus `_embeddings.npz` for semantic routing.

---

## `envelope.py` — the typed transport envelope

Every tool call, result, and routing decision travels in a typed envelope.

| Model | Fields |
|---|---|
| `ToolCall` | `tool: str`, `args: dict`, `call_id: str \| None` |
| `ToolResult` | `call_id`, `ok: bool`, `output: Any`, `error: str \| None` |
| `RoutingDecision` | `protocol_id`, `tier`, `mode`, `rationale`, `confidence` |
| `Envelope` | `id`, `kind`, `payload`, `tool_calls[]`, `results[]`, `routing`, `metadata` |

This hardens *what a tool interaction looks like on the wire* — not what the
AI reasons. There is no message role, no model field, no completion: RO is a
passive tool provider.

---

## Enums — the controlled vocabularies

| Module | Enum | Values |
|---|---|---|
| `tiers.py` | `Tier` | `intake`, `plan`, `execute`, `ground`, `synthesize`, `review`, `finalize` |
| `intent.py` | `IntentClass` | `literature`, `exploration`, `analysis`, `synthesis`, `build`, `audit`, `guidance` |
| `modes.py` | `Mode` | `explore`, `build`, `analyze`, `write`, `review`, `present` |

> Note: `schema/tiers.py` holds the `Tier` **enum**. The tier *helper
> functions* (`TIERS`, `infer_tier`, `tier_position`, `is_valid_tier`,
> `TIER_INDEX`, `compare_tiers`) remain in `protocols/_tiers.py`, which the
> router and tier-state tools import.

---

## Records — memory, state, provenance, environment

| Module | Model | Purpose |
|---|---|---|
| `memory.py` | `MemoryRecord` | A unified memory entry (`kind`, `content`, `tags`, `created_at`). |
| `memory.py` | `Hypothesis` | A tracked hypothesis (`statement`, `status`, `confidence`, `evidence[]`). |
| `memory.py` | `EvidenceLink` | A typed edge (`source`, `target`, `relation`, `weight`). |
| `state.py` | `StateLedger` | The append-only ledger shell (`version`, `schema_version`, `entries[]`). |
| `artifact.py` | `Artifact` | A content-addressed output (`content_hash`, `path`, `media_type`, `size_bytes`). |
| `artifact.py` | `ArtifactManifest` | A run's artifact set. |
| `environment.py` | `EnvironmentSnapshot` | Captured env (`python_version`, `platform`, `packages`, `git_commit`). |
| `gates.py` | `GateRequest` | A pending HITL / consent gate (`gate_id`, `prompt`, `options`, `blocking`, `resolved`). |
| `config.py` | `ResearcherConfig` | Typed view of `researcher_config.yaml`. |
| `plugin.py` | `PluginManifest` | A registered plugin (`entrypoint`, `provides`, `requires`, `enabled`). |

---

## Where the models are used

- **Protocols** — validated by `scripts/preflight.py`; compiled into
  `_protocols.bundle`.
- **Envelopes** — the shape returned across `_handle_tool_call` and the
  daemon's HTTP endpoints.
- **Gates** — the daemon's consent/HITL authority (`daemon/consent.py`,
  `/v1/gates/*`, `/v1/consent/*`), read by shape through
  `server/daemon_bridge.py`.
- **Artifacts / EnvironmentSnapshot** — the run journal + provenance
  (`daemon/runstore.py`, `daemon/provenance.py`).

All cross-process reads go through the on-disk `.os_state/` contract — the
seam `server/` and `tools/` use to observe the daemon **without importing
`research_os.daemon`** (preflight-enforced).
