"""Persistent HITL gate queue — the daemon's human-in-the-loop parking lot.

Why this exists
---------------
A protocol driver that reaches a decision point it cannot resolve autonomously
must NOT call ``input()`` or block a thread waiting for a human.  Instead it
*parks* the gate: serialises the question to disk, publishes a ``gate.pending``
event, and exits.  The researcher's CLI polls ``GET /v1/gates/pending``; the
5.1 dashboard subscribes via SSE (``gate.pending`` / ``gate.resolved``).  When
the human answers, ``resolve()`` rewrites the file and fires ``gate.resolved``.
Because the state lives on disk the queue survives a daemon restart — the
protocol driver can look up its gate by id at any time and find the human's
answer.

Relationship to consent
-----------------------
``GateQueue`` is a SEPARATE primitive from ``ConsentStore``.  Consent
*authorises* a mutating HTTP action (one-shot TTL'd token bound to a specific
tool + arguments).  A gate *parks a protocol driver* waiting for a human
decision on an open question (``question`` is free-form prose, not a tool
call).  Do not merge them: they carry different semantics, different lifetimes,
and different clients.

On-disk layout
--------------
``<root>/.os_state/gates/<id>.json``  — one file per gate, updated in place on
resolve (the filename never changes, so the driver finds its parked gate by id
after a restart).

Atomic writes (temp + os.replace), stdlib only.  The daemon is the single
writer; no locking beyond atomic rename is needed.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── path helper (importable by preflight contract check) ──────────────────────

def gates_dir(root: Any) -> Path:
    """Canonical path to the gates state directory.

    Importable at module level so the preflight drift guard can verify the
    daemon-side path without constructing a full ``GateQueue``.

    Args:
        root: Project root (str or Path).

    Returns:
        ``<root>/.os_state/gates`` as a ``Path``.
    """
    return Path(root) / ".os_state" / "gates"


# ── timestamp helpers (match consent.py / runstore.py idiom) ─────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── GateRequest dataclass ────────────────────────────────────────────────────

@dataclass
class GateRequest:
    """One parked human-in-the-loop decision.

    Fields
    ------
    id          : Stable identifier.  Generated as ``uuid4().hex[:16]`` if not
                  provided.  Used as the filename ``<id>.json`` — never changes,
                  even after resolve.
    protocol_id : The protocol that parked this gate (optional; for display).
    step_id     : The step within that protocol (optional; for display).
    question    : The free-form question the human must answer.
    status      : ``"pending"`` → ``"approved"`` | ``"rejected"``.
    created_at  : ISO timestamp (UTC) when the gate was enqueued.
    resolved_at : ISO timestamp (UTC) when the gate was resolved, or None.
    decision    : The raw decision string passed to ``resolve()`` (e.g.
                  ``"approve"`` or ``"reject"``), or None.
    root        : Project root, carried for observability / SSE filtering.
    """

    id: str
    protocol_id: str | None
    step_id: str | None
    question: str
    status: str = "pending"
    created_at: str = ""
    resolved_at: str | None = None
    decision: str | None = None
    root: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "protocol_id": self.protocol_id,
            "step_id": self.step_id,
            "question": self.question,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "decision": self.decision,
            "root": self.root,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GateRequest":
        return cls(
            id=d.get("id", ""),
            protocol_id=d.get("protocol_id"),
            step_id=d.get("step_id"),
            question=d.get("question", ""),
            status=d.get("status", "pending"),
            created_at=d.get("created_at", ""),
            resolved_at=d.get("resolved_at"),
            decision=d.get("decision"),
            root=d.get("root"),
        )


# ── atomic write helper (mirrors consent.py / runstore.py) ───────────────────

def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write *payload* to *path* atomically (temp sibling + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ── GateQueue ─────────────────────────────────────────────────────────────────

class GateQueue:
    """Persistent HITL gate queue.  Survives daemon restart.

    Each gate is stored as ``<root>/.os_state/gates/<id>.json``.  The file is
    *updated in place* on resolve (filename is stable), so the protocol driver
    can always look up its parked gate by id after a daemon restart.

    ``event_bus`` is optional — the queue works headless in tests and when the
    daemon bus is not yet initialised.  All bus interactions are best-effort:
    if publish raises, the gate operation still succeeds.
    """

    def __init__(self, root: Any, event_bus: Any = None) -> None:
        self._dir = gates_dir(root)
        # Lazy mkdir: create the directory only on first write (enqueue/resolve)
        # so constructing a GateQueue does NOT create .os_state/ prematurely —
        # that would break the project_initialized check (which tests for the
        # presence of .os_state/).
        self._bus = event_bus

    # ── enqueue ───────────────────────────────────────────────────────────────

    def enqueue(self, request: GateRequest) -> str:
        """Persist *request* and publish ``gate.pending``.

        If ``request.id`` is empty or None, a new 16-hex-char id is generated.
        ``created_at`` is set to now (UTC) if not already populated.

        Returns:
            The stable gate id (filename stem).
        """
        # Normalise id
        if not request.id:
            request.id = uuid.uuid4().hex[:16]
        # Stamp creation time if absent
        if not request.created_at:
            request.created_at = _now_iso()

        path = self._dir / f"{request.id}.json"
        _atomic_write_json(path, request.to_dict())

        # Best-effort publish — must never raise
        try:
            if self._bus is not None:
                from .events import GATE_PENDING
                self._bus.publish(
                    GATE_PENDING,
                    data={
                        "gate_id": request.id,
                        "protocol_id": request.protocol_id,
                        "step_id": request.step_id,
                        "question": request.question,
                    },
                    root=request.root,
                )
        except Exception:  # noqa: BLE001
            pass

        return request.id

    # ── resolve ───────────────────────────────────────────────────────────────

    def resolve(self, gate_id: str, decision: str) -> bool:
        """Resolve a gate with *decision* (``"approve"`` → approved, else rejected).

        Loads the gate file, sets ``status``, ``resolved_at``, and ``decision``,
        rewrites atomically, and publishes ``gate.resolved``.

        Returns:
            ``True`` if the decision was ``"approve"`` (approved), ``False``
            otherwise (including unknown gate id — never raises).
        """
        path = self._dir / f"{gate_id}.json"
        if not path.exists():
            return False

        # Load gate
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False

        status = "approved" if decision == "approve" else "rejected"
        raw["status"] = status
        raw["resolved_at"] = _now_iso()
        raw["decision"] = decision

        _atomic_write_json(path, raw)

        # Best-effort publish
        try:
            if self._bus is not None:
                from .events import GATE_RESOLVED
                self._bus.publish(
                    GATE_RESOLVED,
                    data={"gate_id": gate_id, "decision": decision},
                    root=raw.get("root"),
                )
        except Exception:  # noqa: BLE001
            pass

        return status == "approved"

    # ── pending ───────────────────────────────────────────────────────────────

    def pending(self) -> list[GateRequest]:
        """Return all gates whose ``status`` field is ``"pending"``.

        Reads each ``.json`` file and filters by status — NOT by filename
        (filename never changes after resolve; filtering by name would be
        fragile).  Unreadable / corrupt files are skipped silently.
        """
        if not self._dir.exists():
            return []
        out: list[GateRequest] = []
        for p in sorted(self._dir.glob("*.json")):
            gr = self._load_file(p)
            if gr is not None and gr.status == "pending":
                out.append(gr)
        return out

    # ── get ───────────────────────────────────────────────────────────────────

    def get(self, gate_id: str) -> GateRequest | None:
        """Look up a single gate by id.  Returns ``None`` if missing or corrupt."""
        path = self._dir / f"{gate_id}.json"
        if not path.exists():
            return None
        return self._load_file(path)

    # ── all ───────────────────────────────────────────────────────────────────

    def all(self, limit: int = 100) -> list[GateRequest]:
        """Return up to *limit* gates, newest first (by ``created_at``).

        Intended for observability endpoints — status is unrestricted.
        Unreadable / corrupt files are skipped silently.
        """
        if not self._dir.exists():
            return []
        out: list[GateRequest] = []
        for p in self._dir.glob("*.json"):
            gr = self._load_file(p)
            if gr is not None:
                out.append(gr)
        # Sort newest first; fall back to empty string for missing created_at
        out.sort(key=lambda g: g.created_at or "", reverse=True)
        return out[:limit]

    # ── internal helpers ──────────────────────────────────────────────────────

    def _load_file(self, path: Path) -> GateRequest | None:
        """Load and deserialise one gate file.  Returns None on any error."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return GateRequest.from_dict(raw)
        except Exception:  # noqa: BLE001
            return None
