# Changelog

All notable changes to Research OS are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) ·
Versioning: [SemVer](https://semver.org).

---

## [5.0.1] — Documentation Drift Guard (2026-07-08)

### Added
- Added a generated documentation count reference and preflight drift guard for mutable tool/protocol/check/test counts.

### Improved
- Rewrote the 5.x roadmap around the daemon-backed enforcement, execution, and notification kernel trajectory.
- Updated maintainer and project templates to avoid stale hardcoded inventory counts.

### Fixed
- Replaced stale prose counts with references to generated count metadata or release-gate commands.

## [5.0.0] — The World-Class Architecture Overhaul (2026-07-06)

A MAJOR release. The headline: Research-OS is now unambiguously a **passive
tool provider** — it calls no LLM and has no gateway. The daemon is an
enforcement + execution + notification **kernel** fronting the MCP tools +
protocols + journaled state. The throughline is turning soft, trusted prose
into hard, verified structure while the reasoning layer stays soft. Delivered
across the P0–P8 phase plan (schema foundation → tool consolidation →
config/state simplification → memory overhaul → token engineering → daemon
core → daemon surface → ship).

See [`docs/MIGRATION.md`](docs/MIGRATION.md) for the complete breaking-change
table and one-command migration path.

### Added
- **Typed schema contract** (`schema/`): every protocol validates against a
  single `Protocol` model (`schema_version` 3.0); every tool call / result /
  routing decision travels in a typed `Envelope`. Full reference in
  [`docs/SCHEMA.md`](docs/SCHEMA.md).
- **Daemon kernel**: event bus (SSE `/v1/stream`, `/v1/events`),
  content-addressed store, environment snapshots, HITL/consent gates, a single
  execution path, resumable runs + crash recovery, notification spine, and a
  read-only `/v1/capabilities` agent front door (`daemon/capabilities.py`).
- **`docs/SCHEMA.md`** and **`docs/MIGRATION.md`** (new).

### Improved
- **Tool surface consolidated to 46 tools** across `sys_*` / `tool_*` /
  `mem_*`, with a lean routing handshake. Memory unified into `mem_log`
  (unified `kind`) + `mem_search` + `mem_hypothesis` (+ `mem_retrieve`).
- **Routing** moved INTO each protocol body (the old `_router_index.yaml` is
  gone); five sidecars collapsed into one `_protocols.bundle` built by
  `build_protocols.py`.
- **Docs rewritten to match the live system** — ARCHITECTURE, ROADMAP,
  PROTOCOL_DOCTRINE, TOOLS, templates/AGENTS — all state that RO never calls
  an LLM and has no gateway.

### Fixed / Removed
- **Removed the dead LLM chat gateway** (`daemon/gateway.py`,
  `POST /v1/chat/completions`, `enable_gateway` + all `gateway_*` config and
  their env readers). RO never proxied a model in normal use; the gateway was
  opt-in and off by default. Its read-only capabilities logic moved to
  `daemon/capabilities.py`.
- **Daemon auth decoupled from the gateway.** A single `auth_token_env`
  (default `RESEARCH_OS_DAEMON_TOKEN`) guards the mutating endpoints
  (`/v1/runs`, `/v1/gates/respond`, `/v1/consent/*`, …); open behind the
  `127.0.0.1` bind when unset. CLI `research-os daemon gateway` →
  `research-os daemon token`.
- **Python floor raised 3.10 → 3.11.**

### Migration
- 134 tools → 46: removed names return a one-release clear-error (a few remain
  as live aliases). See [`docs/TOOLS.md`](docs/TOOLS.md).
- `schema_version` 2.0 → 3.0: `research-os migrate protocols`.
- `researcher_config.yaml` simplified: `research-os init --migrate`.
- State / paths / workspace `.thoughts`+`.lessons`: `research-os migrate`
  (state/paths) + auto-migrated on first `sys_boot`.
- Daemon LLM gateway removed: point your IDE / AI client straight at the MCP
  tools. **No action for the default stdio path.** The pre-5.0
  `RESEARCH_OS_GATEWAY_TOKEN` env var is honored for one release.
- Upgrade Python to ≥ 3.11.
