"""Event spine — the daemon's append-only event bus (Phase 1.5).

JUDGE-phase insight (docs/ROADMAP.md §7): a research OS that owns
long-horizon work cannot be poll-only. Any connected client — an AI agent
watching a 6-hour simulation, a web dashboard, an MCP telemetry sidecar —
must be able to *subscribe* to what the daemon is doing, not hammer
/v1/state in a loop. The event bus is that substrate. Everything that
streams in later phases (SSE job logs, run/gate deltas, dashboard
live tiles) composes on top of this one primitive.

Design (deliberately small, correct, dependency-free):
  - Append-only, monotonic sequence numbers. Each event has a global `seq`
    so a reconnecting subscriber can resume with Last-Event-ID semantics.
  - Bounded ring buffer of recent events (replay/backfill on connect).
  - Thread-safe fan-out to live subscribers via per-subscriber queues.
  - stdlib only (threading, queue, collections.deque, time). Imports in
    core installs without the [daemon] extra. The SSE *encoding* lives in
    server.py (which owns starlette); this module stays transport-agnostic.

An Event is intentionally a plain dict-friendly record: a `kind`
(namespaced, e.g. "job.started", "state.changed", "run.completed"), an
optional `root` (which project it concerns), and a free-form `data` payload.
Consumers filter by kind/root; the bus itself stays domain-ignorant
(strangler-fig: it knows nothing about research).
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Generator

# Reuse the queue's JSON-safety helper so event payloads can never make a
# status/SSE read raise.
from .tasks import _jsonsafe


@dataclass
class Event:
    """One thing that happened in the daemon."""

    seq: int
    kind: str
    ts: float = field(default_factory=time.time)
    root: str | None = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "ts": self.ts,
            "root": self.root,
            "data": _jsonsafe(self.data),
        }


# ── Phase-6 canonical event kinds ────────────────────────────────────────────
# Callers must reference these constants, not string literals, so a rename
# stays a one-line fix and static analysis catches typos.
#
# kind                   payload fields
# ---                    --------------
# run.started            {run_id, command, cwd}
# run.completed          {run_id, exit_code, duration, artifacts}
# run.failed             {run_id, error, exit_code}
# protocol.step_started  {plan_id, step_id, protocol_id}
# gate.pending           {gate_id, protocol_id, step_id, question}
# gate.resolved          {gate_id, decision}
# memory.stored          {record_id, kind}

RUN_STARTED: str = "run.started"
RUN_COMPLETED: str = "run.completed"
RUN_FAILED: str = "run.failed"
PROTOCOL_STEP_STARTED: str = "protocol.step_started"
GATE_PENDING: str = "gate.pending"
GATE_RESOLVED: str = "gate.resolved"
MEMORY_STORED: str = "memory.stored"

PHASE6_EVENT_KINDS: frozenset[str] = frozenset(
    {
        RUN_STARTED,
        RUN_COMPLETED,
        RUN_FAILED,
        PROTOCOL_STEP_STARTED,
        GATE_PENDING,
        GATE_RESOLVED,
        MEMORY_STORED,
    }
)


class _Subscriber:
    """A live consumer. Holds a bounded queue; if the consumer can't keep up
    the oldest events are dropped (a slow dashboard must never block the
    daemon or wedge a job thread)."""

    __slots__ = ("queue", "kinds", "root", "dropped")

    def __init__(self, kinds: set[str] | None, root: str | None, maxsize: int) -> None:
        self.queue: Queue[Event] = Queue(maxsize=maxsize)
        self.kinds = kinds  # None = all kinds
        self.root = root    # None = all roots
        self.dropped = 0

    def wants(self, event: Event) -> bool:
        if self.root is not None and event.root != self.root:
            return False
        if self.kinds is not None and not _kind_matches(event.kind, self.kinds):
            return False
        return True

    def offer(self, event: Event) -> None:
        try:
            self.queue.put_nowait(event)
        except Exception:  # queue.Full
            # Drop the OLDEST to make room — recent state matters more than
            # a backlog for a live tile.
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(event)
            except Exception:
                self.dropped += 1


def _kind_matches(kind: str, patterns: set[str]) -> bool:
    """Match an event kind against a set of patterns. A pattern may be exact
    ("job.started") or a namespace prefix wildcard ("job.*" / "job")."""
    for p in patterns:
        if p == kind:
            return True
        if p.endswith(".*") and kind.startswith(p[:-1]):
            return True
        if p == kind.split(".", 1)[0]:  # bare namespace, e.g. "job"
            return True
    return False


class EventBus:
    """Append-only, bounded, fan-out event bus.

    publish() is non-blocking and safe to call from job threads, request
    handlers, anywhere. subscribe() yields a generator of live events with
    optional backfill of recent history.
    """

    def __init__(
        self,
        history: int = 1000,
        subscriber_buffer: int = 256,
        persist_path: Path | None = None,
    ) -> None:
        self._history = deque(maxlen=history)
        self._sub_buffer = subscriber_buffer
        self._subscribers: list[_Subscriber] = []
        self._lock = threading.RLock()
        self._seq = 0
        self._persist_path: Path | None = None
        if persist_path is not None:
            try:
                persist_path.parent.mkdir(parents=True, exist_ok=True)
                self._persist_path = persist_path
            except Exception:
                # Best-effort: if we can't create the directory, skip persistence
                # silently so the bus is always usable (fail-safe open).
                pass

    # ── internal helpers ──────────────────────────────────────────────
    def _append_persist(self, event: Event) -> None:
        """Append one event as a JSONL line. Best-effort: never raises."""
        if self._persist_path is None:
            return
        try:
            with self._persist_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict()) + "\n")
        except Exception:
            pass  # full disk, permission error, etc. — never wedge a job thread

    # ── publish ───────────────────────────────────────────────────────
    def publish(self, kind: str, data: dict | None = None, root: str | None = None) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(seq=self._seq, kind=kind, root=root, data=dict(data or {}))
            self._history.append(event)
            subs = list(self._subscribers)
        for sub in subs:
            if sub.wants(event):
                sub.offer(event)
        self._append_persist(event)
        return event

    # ── read history ──────────────────────────────────────────────────
    def recent(
        self,
        limit: int = 100,
        kinds: set[str] | None = None,
        root: str | None = None,
        after_seq: int = 0,
    ) -> list[Event]:
        """Return recent events (oldest-first) matching the filters."""
        with self._lock:
            events = list(self._history)
        out = []
        for e in events:
            if e.seq <= after_seq:
                continue
            if root is not None and e.root != root:
                continue
            if kinds is not None and not _kind_matches(e.kind, kinds):
                continue
            out.append(e)
        return out[-limit:]

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    # ── subscribe ─────────────────────────────────────────────────────
    def subscribe(
        self,
        kinds: set[str] | None = None,
        root: str | None = None,
        backfill: int = 0,
        after_seq: int = 0,
    ) -> Generator[Event, None, None]:
        """Yield live events as they are published.

        Optionally backfills up to ``backfill`` recent matching events (or
        every event after ``after_seq`` for reconnect/resume) before going
        live. The generator blocks waiting for new events; close it to
        unsubscribe (always do so in a finally).
        """
        sub = _Subscriber(kinds=kinds, root=root, maxsize=self._sub_buffer)
        with self._lock:
            self._subscribers.append(sub)
            # Snapshot backfill under the lock so we don't miss/duplicate
            # events racing with registration.
            history: list[Event] = []
            if after_seq:
                history = [e for e in self._history if e.seq > after_seq and sub.wants(e)]
            elif backfill:
                history = [e for e in self._history if sub.wants(e)][-backfill:]
        try:
            for e in history:
                yield e
            while True:
                try:
                    yield sub.queue.get(timeout=15.0)
                except Empty:
                    # Heartbeat sentinel so the SSE layer can emit a keepalive
                    # comment and detect dead connections.
                    yield Event(seq=-1, kind="heartbeat", root=root)
        finally:
            with self._lock:
                try:
                    self._subscribers.remove(sub)
                except ValueError:
                    pass

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def stats(self) -> dict:
        with self._lock:
            return {
                "last_seq": self._seq,
                "history": len(self._history),
                "history_cap": self._history.maxlen,
                "subscribers": len(self._subscribers),
            }


# ── Replay helper (§12 stream(since=...) semantics) ───────────────────────────


def replay(persist_path: Path, since: float | None = None) -> list[dict]:
    """Read a JSONL persist file and return event dicts.

    Args:
        persist_path: Path to the JSONL file written by EventBus.
        since: If set, only return events with ``ts > since``
               (wall-clock seconds, same unit as ``Event.ts``).

    Returns:
        List of event dicts in the order they appear in the file.
        Missing file → []. Malformed lines are skipped silently.
    """
    try:
        text = persist_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except Exception:
        return []

    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue  # malformed — skip
        if since is not None:
            try:
                if rec.get("ts", 0.0) <= since:
                    continue
            except Exception:
                continue
        out.append(rec)
    # Sort by seq so reconnecting subscribers get events in order regardless
    # of any write-order variation in the JSONL file. Best-effort: records
    # missing a seq key sort to the front (seq=0) rather than raising.
    out.sort(key=lambda e: e.get("seq", 0) or 0)
    return out
