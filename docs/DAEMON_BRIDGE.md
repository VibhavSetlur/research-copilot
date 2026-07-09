# Daemon bridge — one canonical MCP↔daemon contract

## The pain (consistency, not a missing feature)

Research OS gives the reasoning layer (MCP / `server/`, `tools/`) several
ways to talk to the daemon WITHOUT importing it — all via on-disk
contracts read "by shape": consent ledger, notification outbox, staleness
verdict, the daemon discovery descriptor, the HTTP probe. Each was added
in its own feature commit, and each re-implemented the same two primitives:

* **Descriptor read + PID-liveness** ("is a daemon running for this root?").
  Duplicated in `server/consent.py::daemon_present`,
  `server/notify_sink.py::_daemon_present`,
  `server/handlers/meta_workspace.py` (inline), and referenced from
  `staleness_state.py`. Four copies of the same `os.kill(pid, 0)` dance,
  each with subtly its own error handling.
* **The `.os_state/` contract paths.** `daemon.json`, `consent/granted.json`,
  `notifications/outbox.jsonl`, `staleness/verdict.json`, `runs/` — string
  literals scattered across a dozen files. A rename in one place silently
  drifts from the daemon side.

This is a real liability: the MCP↔daemon contract is the load-bearing seam
of the daemon layer, but it exists as N near-identical copies. A bug fixed in one copy
isn't fixed in the others; a path changed on the daemon side has no single
mirror to update. The system WORKS, but its togetherness is accidental.

## The fix (one sentence)

Introduce one canonical `server/daemon_bridge.py` that defines the
`.os_state/` contract paths and the single true `daemon_present()` +
descriptor reader + HTTP probe; every reasoning-side reader delegates to
it — so the seam is ONE thing, defined once, not N copies.

## What it is (and isn't)

* It IS the reasoning side's single, stdlib-only, fail-safe view of the
  daemon: where the contract files live, whether a daemon is alive, and a
  localhost HTTP GET helper. No behaviour change — it's the superset of the
  existing copies, taking the most careful version of each.
* It is NOT a daemon import. `daemon_bridge` lives in `server/` and never
  imports `research_os.daemon` (preflight-enforced seam). It reads the
  daemon's self-advertised descriptor + sidecars by shape, exactly as the
  copies did. The daemon remains an opaque local service.
* It preserves the v5 safety split: **daemon absent means degrade-open** for
  ordinary stdio MCP users (the tool surface behaves as it did before); **daemon
  present but enforcement ambiguous means fail-safe closed** for hard gates (no
  silent pass, no forged approval). This aligns with
  [UNSKIPPABLE_GATES.md](UNSKIPPABLE_GATES.md), [PRECONDITION_GATE.md](PRECONDITION_GATE.md),
  and [STALENESS_GATE.md](STALENESS_GATE.md).

## Contents

```
server/daemon_bridge.py
  # Canonical contract paths (relative to a project root):
  STATE_DIR            = ".os_state"
  DAEMON_DESCRIPTOR    = ".os_state/daemon.json"
  CONSENT_GRANTED      = ".os_state/consent/granted.json"
  CONSENT_SPENT        = ".os_state/consent/spent.json"
  NOTIFICATIONS_OUTBOX = ".os_state/notifications/outbox.jsonl"
  STALENESS_VERDICT    = ".os_state/staleness/verdict.json"
  RUNS_DIR             = ".os_state/runs"
  def state_path(root, *parts) -> Path        # join helper

  # The single daemon-presence + descriptor primitives:
  def read_descriptor(root) -> dict | None    # parsed daemon.json or None
  def daemon_present(root) -> bool            # descriptor + live PID
  def daemon_base_url(root) -> str | None     # from a live descriptor
  def http_get(base_url, path, timeout) -> dict | None   # stdlib urllib GET
```

## Migration (additive, behaviour-preserving)

1. Add `server/daemon_bridge.py` (superset of the existing copies — the
   careful consent.py PID logic; the meta_workspace stdlib HTTP GET).
2. Re-point the existing readers at it, keeping their public names as thin
   wrappers so nothing downstream breaks:
   * `consent.daemon_present` → delegates to `daemon_bridge.daemon_present`;
     `_consent_path` / `_daemon_descriptor_path` use the bridge constants.
   * `notify_sink._daemon_present` / `_outbox_path` → bridge.
   * `staleness_state._verdict_path` / descriptor reads → bridge.
   * `meta_workspace` `_daemon_http_get` → `daemon_bridge.http_get`; the
     inline descriptor read → `daemon_bridge.read_descriptor`.
3. Every existing test stays green (same behaviour); add focused tests for
   the bridge itself.

## Why this makes the WHOLE system better

* One definition of "is the daemon here?" — fix it once, every gate /
  notification / staleness read benefits. No more drift between copies.
* One definition of the contract paths — the daemon side and the reasoning
  side point at the same constants; a future path change is a one-line edit
  mirrored by a (future) shared check.
* New daemon-backed features get a ready-made, correct primitive instead of
  copy-pasting the PID dance a fifth time. The reusable pattern now has a
  reusable IMPLEMENTATION.
* The seam stays exactly as strong (preflight still proves server/ never
  imports daemon/); we've just made the seam coherent instead of scattered.

## Build order

1. This doc.
2. `server/daemon_bridge.py` (constants + primitives, stdlib, no daemon import).
3. Re-point consent / notify_sink / staleness_state / meta_workspace.
4. Tests for the bridge + full suite green (no behaviour change) + seam green.
