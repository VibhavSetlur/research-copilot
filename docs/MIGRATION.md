# Migration guide — 4.x → 5.0.0

> 5.0.0 is **The World-Class Architecture Overhaul** — a MAJOR release with
> breaking changes. This guide lists every breaking change and its migration
> path. Most migrations are automated by `research-os migrate` / `init`.

**The headline:** Research-OS is now unambiguously a **passive tool
provider** — it calls no LLM and has no gateway. If you were (unusually)
using the opt-in chat gateway, point your IDE / AI client straight at the
MCP tools instead. The default stdio path is unaffected.

---

## Breaking changes

| Breaking change | Migration path |
|---|---|
| **134 tools → 46**; old names removed | Old names return a one-release clear-error pointing at the replacement (a few remain as live aliases). See the alias/removed lists in `docs/TOOLS.md` + `CHANGELOG.md`. |
| **`_router_index.yaml` deleted** | Routing fields (`intent_class`, `sub_intent`, `triggers`, `decomposition`, `tier`) moved INTO each protocol YAML. `research-os migrate protocols` does the merge. |
| **`schema_version` 2.0 → 3.0** | Old protocol YAMLs fail validation. Migrate with `research-os migrate protocols`. |
| **3 build scripts → 1** | `build_gate_meta.py` + `build_precondition_meta.py` + the route-meta half of `build_embeddings.py` collapsed into `build_protocols.py`. Internal — only matters for custom build pipelines. (`build_embeddings.py` still builds the semantic-search embeddings.) |
| **5 sidecars → `_protocols.bundle`** | Internal — the sidecars (`_gate_meta.json`, `_precondition_meta.json`, `_route_meta.json`, …) were private. |
| **Python floor 3.10 → 3.11** | 3.10 nears EOL (Oct 2026). Upgrade your interpreter; `requires-python` is now `>=3.11`. |
| **`researcher_config.yaml` simplified** | Auto-migrated by `research-os init --migrate`. |
| **Memory system consolidated** | `mem_hypothesis_*`, `tool_lessons` sub-ops, and per-kind log tools → **`mem_log`** (unified `kind` param) + **`mem_search`** + **`mem_hypothesis`** (+ `mem_retrieve`). Old names alias for one release. |
| **`_LEGACY_*` fallback tables removed** where obsolete | The bundle is committed + build-verified. Deliberate fail-safe tables that still activate when a sidecar is missing are **kept** by design. |
| **State auto-migration removed from the hot path** where safe | `research-os migrate state` performs the one-time migration. 4.x state is otherwise read via the retained compatibility shim. |
| **`data/input/` path fallback removed** | `research-os migrate paths` renames to `data/past_step_input/`. |
| **Workspace `.thoughts/` and `.lessons/` moved** | Auto-migrated on first `sys_boot` in 5.0.0. |
| **Daemon v1 → v2 endpoint layout** | v1 endpoints redirect with a deprecation header for one release. |
| **Daemon LLM gateway removed** (`/v1/chat/completions`, `enable_gateway`, and all `gateway_*` config) | RO never proxied a model in normal use; the gateway was opt-in and **off by default**. Point your IDE / AI client straight at the MCP tools. **No user action for the default (stdio) path.** The bearer-token auth that guarded the *non-gateway* mutating endpoints is retained (see below). |

---

## Daemon auth — what changed

The gateway removal decoupled the daemon's write-authorization from the
(deleted) `enable_gateway` flag:

- **Config:** the `gateway_*` fields (`enable_gateway`,
  `gateway_upstream_base_url`, `gateway_upstream_model`, `gateway_api_key_env`,
  `gateway_token_env`, `gateway_max_tool_rounds`, `gateway_timeout`) are gone.
  A single field replaces the auth knob: **`auth_token_env`** (default env var
  **`RESEARCH_OS_DAEMON_TOKEN`**).
- **Behavior:** the daemon's *mutating* endpoints (`/v1/runs`,
  `/v1/gates/respond`, `/v1/consent/*`, …) require a bearer token **when one is
  configured**; when no token is set they stay open behind the `127.0.0.1`
  localhost bind. Provision with `research-os daemon token --mint-token`.
- **Back-compat:** for one release the client honors the old
  `RESEARCH_OS_GATEWAY_TOKEN` env var if `RESEARCH_OS_DAEMON_TOKEN` is unset.
- **CLI:** `research-os daemon gateway` → **`research-os daemon token`**.

The read-only `/v1/capabilities` agent front door is retained (now backed by
`daemon/capabilities.py`, not the gateway).

---

## The one-command path

For most projects:

```bash
research-os migrate          # protocols + state + paths, idempotent
research-os init --migrate   # refresh researcher_config.yaml + templates
```

Then run the release gate to confirm everything is green:

```bash
python scripts/preflight.py
python -m pytest -q
```

If you maintained a custom build pipeline that called the old build scripts,
replace those calls with `python scripts/build_protocols.py` (protocols +
bundle) and keep `python scripts/build_embeddings.py` (semantic embeddings).
