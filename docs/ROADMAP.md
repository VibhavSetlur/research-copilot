# Research OS — 5.x Roadmap

> **The 5.x roadmap treats Research OS as a daemon-backed enforcement,
> execution, and notification kernel in front of MCP/protocol reasoning
> scaffolds.** The daemon hardens the operational surface; protocols remain the
> soft reasoning layer. This document captures the durable architecture and the
> direction of travel for the 5.x line.

---

## 5.x thesis

Research OS is moving toward a split-brain architecture:

- **Daemon/kernel layer:** enforcement, execution, notifications, freshness,
  resource budgeting, provenance, and cross-process coordination.
- **MCP/protocol layer:** reasoning scaffolds, routing, decomposition, and
  human-readable guidance.

The goal is to turn soft intent into hard, verified structure without putting
LLM calls inside Research OS. The daemon stays the single operational kernel;
server/ and tools/ remain on the safe side of the seam and never import
daemon internals directly.

---

## Core invariants

1. **No LLM calls inside RO.** Research OS does not host a model gateway and
   does not proxy provider calls.
2. **Seam is mandatory.** `server/` and `tools/` must not import
   `research_os.daemon`; cross-process communication flows through the on-disk
   `.os_state/` contract and `server/daemon_bridge.py`.
3. **Fail-safe closed, degrade-open.** If the daemon is absent, behavior must
   match today’s stdio workflow. If enforcement is ambiguous, do not silently
   pass a gate and do not falsely block.
4. **Reasoning stays soft.** Protocols and agent guidance can remain flexible,
   but enforcement, provenance, and notification state must be explicit and
   verified.
5. **Release gates are command-based only.** Use the current gate commands at
   release time; do not pin counts in prose.

Related architecture notes: [`DAEMON_BRIDGE.md`](DAEMON_BRIDGE.md),
[`NOTIFICATION_SPINE.md`](NOTIFICATION_SPINE.md),
[`RESOURCE_BUDGET.md`](RESOURCE_BUDGET.md),
[`PRECONDITION_GATE.md`](PRECONDITION_GATE.md),
[`STALENESS_GATE.md`](STALENESS_GATE.md),
[`HYBRID_ARCHITECTURE.md`](HYBRID_ARCHITECTURE.md),
[`PROTOCOL_DOCTRINE.md`](PROTOCOL_DOCTRINE.md),
[`_STALE_COUNTS_REFERENCE.md`](./_STALE_COUNTS_REFERENCE.md).

---

## 5.0 — Foundation

The foundation release establishes the daemon/kernel seam and the core hard
signals:

- daemon bridge and canonical `.os_state/` contract paths
- precondition, resource, and staleness enforcement
- gate outcomes that can fail-safe closed when needed and degrade-open when the
  daemon is unavailable
- notification plumbing that reports state without coupling clients to daemon
  internals
- explicit cross-process boundaries for server and tool code

Definition of done: the daemon can be present or absent without breaking the
stdio path, and enforcement decisions are grounded in explicit bridge state.

---

## 5.1 — Event bus and notification spine

Build the notification backbone that lets the daemon surface asynchronous
state to clients and operators:

- event bus for background jobs, gate outcomes, and freshness changes
- notification delivery across clients and sessions
- durable event journaling for later inspection
- consistent presentation of daemon alerts and background work

The spine should remain implementation-agnostic enough to support multiple
front-ends while keeping the daemon as the source of truth.

---

## 5.2 — CAS/content-addressed artifacts and lineage

Add a content-addressed artifact layer so outputs can be verified, reused, and
traced:

- immutable artifact identities
- lineage from inputs to outputs
- deduplication by content rather than name
- audit-friendly references from protocols, tasks, and generated artifacts

The intent is to make provenance first-class without forcing protocol authors
into low-level storage mechanics.

---

## 5.3 — Environment capture and replay

Make runs reproducible by capturing enough environment detail to replay them:

- execution environment snapshots
- dependency and configuration capture
- replay hooks for past runs
- clear distinction between captured state and mutable working state

This layer should support both local development and daemon-managed execution
without assuming a single runtime model.

---

## 5.4 — Air-gapped and shared-HPC mode

Support constrained environments where the daemon must still be useful:

- air-gapped operation with minimal external assumptions
- shared-HPC coordination and scheduling awareness
- bounded resource use and explicit execution placement
- degraded behavior when only part of the full stack is available

This phase emphasizes resilience in restricted infrastructure rather than adding
new reasoning features.

---

## 5.5 — Protocol DAG and resumable plans

Move from linear protocol stepping to richer execution graphs:

- protocol DAG representation
- resumable plans with explicit continuation points
- dependency-aware execution order
- recovery from partial completion without losing provenance

The daemon should manage execution state while protocols continue to provide the
reasoning structure that decides what the graph should be.

---

## 5.6 — Generic model-agnostic agent layer

Expose the kernel to multiple client and model setups without locking the
system to one provider or one interface:

- model-agnostic client integration
- shared operational state across heterogeneous front-ends
- clean routing between reasoning clients and daemon-managed work
- consistent enforcement regardless of which agent initiated the task

This is not a model gateway; it is a coordination layer around the kernel.

---

## Later 5.x work

After the foundation pieces are stable, the remaining 5.x space is for
operational polish and trust-building:

- dashboards and inspection UIs
- richer auditability and operator review paths
- policy packs for project-specific enforcement
- provenance review workflows
- additional surface hardening where repeated use reveals friction

These are intentionally sequenced after the core kernel pieces so the system
can stay trustworthy while growing outward.

---

## Working rules for 5.x

- Keep the daemon/kernel seam strict.
- Never add hidden LLM behavior inside RO.
- Prefer explicit bridge state over inference.
- Treat ambiguous enforcement as unsafe to auto-pass.
- Keep non-generated markdown free of mutable count claims.

For implementation and protocol details, consult the linked architecture docs
and the generated stale-count reference only when a current inventory is needed.
