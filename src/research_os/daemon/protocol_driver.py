"""Proactive protocol driver — §13.3.

Tracks a protocol as a resumable, persistence-backed plan.  Each plan is one
flat JSON file at ``<root>/.os_state/plans/<plan_id>.json``.

Design notes
------------
* NO LLM calls.  ``step()`` returns the NEXT step *data* for the client's AI
  to act on.  ``complete_step()`` records the client-supplied result and
  advances the index.  This module is a tracker, not an executor.
* Resumability: state lives on disk keyed by ``plan_id``.  A fresh
  ``ProtocolDriver(root)`` after a restart can ``step()``/``complete_step()``
  an existing plan without any in-memory state.
* Only the protocol *name* (not the ``Protocol`` object) is persisted.  The
  ``Protocol`` is rehydrated from the registry on every operation so plans
  survive protocol-bundle rebuilds and daemon restarts.
* The ``ProtocolRegistry`` import is lazy (inside function bodies) following
  the established daemon pattern: importing this module at the top level
  must stay cheap and must not pull in the full tools stack.
* SEAM: this file may import from ``research_os.tools`` and
  ``research_os.server`` (daemon → reasoning direction).  The reverse
  (server/tools importing daemon) is forbidden and caught by preflight.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── on-disk path constant (must agree with daemon_bridge.PLANS_DIR = "plans") ─
_PLANS_DIRNAME = "plans"


# ── module-level path helper (importable by preflight contract guard) ─────────

def plans_dir(root: Any) -> Path:
    """Canonical path to the plans state directory.

    Importable at module level so the preflight drift guard can verify the
    daemon-side path without constructing a full ``ProtocolDriver``.

    Args:
        root: Project root (str or Path).

    Returns:
        ``<root>/.os_state/plans`` as a ``Path``.
    """
    return Path(root) / ".os_state" / _PLANS_DIRNAME


# ── timestamp helper ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── atomic write (mirrors gates.py / consent.py style) ───────────────────────

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


# ── ProtocolDriver ────────────────────────────────────────────────────────────

class ProtocolDriver:
    """Step through a protocol as a tracked, resumable plan.

    State is persisted to ``<root>/.os_state/plans/<plan_id>.json`` so that
    a fresh ``ProtocolDriver`` instance on the same root can continue any
    existing plan after a daemon restart or reconnect.

    Parameters
    ----------
    root:
        Project workspace root (str or Path).
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        # Ensure the plans directory concept exists (lazy creation on first write).
        self._plans_dir: Path = plans_dir(self.root)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _plan_path(self, plan_id: str) -> Path:
        return self._plans_dir / f"{plan_id}.json"

    def _load_plan(self, plan_id: str) -> dict | None:
        """Read and parse a plan file.  Returns None on missing/corrupt."""
        path = self._plan_path(plan_id)
        try:
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return data
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _save_plan(self, plan: dict) -> None:
        """Persist the plan dict atomically."""
        plan["updated_at"] = _now_iso()
        _atomic_write_json(self._plan_path(plan["id"]), plan)

    @staticmethod
    def _rehydrate(protocol_name: str):  # -> Protocol
        """Load a Protocol by name from the registry.  Lazy import."""
        from research_os.tools.actions.protocol import ProtocolRegistry  # noqa: PLC0415
        return ProtocolRegistry.get_protocol(protocol_name)

    # ── public API ────────────────────────────────────────────────────────────

    def start(
        self,
        protocol_name: str,
        root: str | None = None,
        bus: Any = None,
    ) -> str:
        """Load a protocol, create a new plan, persist it, and return the plan_id.

        Parameters
        ----------
        protocol_name:
            Slash-separated protocol name (e.g. ``"guidance/project_startup"``).
        root:
            Ignored (kept for signature compatibility with the spec pseudocode;
            the root is already stored on the instance).
        bus:
            Optional :class:`~research_os.daemon.events.EventBus`.  If supplied,
            a ``protocol.step_started`` event is published for step 0.

        Returns
        -------
        str
            The new plan's UUID hex ``plan_id``.

        Raises
        ------
        research_os.server.errors.RoError
            When *protocol_name* does not exist in the registry.
        """
        # Validate — will raise RoError (clear typed error) if not found.
        protocol = self._rehydrate(protocol_name)

        plan_id = uuid.uuid4().hex
        now = _now_iso()
        plan: dict = {
            "id": plan_id,
            "protocol": protocol_name,
            "step_index": 0,
            "status": "active",
            "results": {},
            "created_at": now,
            "updated_at": now,
        }
        self._save_plan(plan)

        # Optional event publication — fail-open (never blocks start()).
        if bus is not None:
            try:
                from research_os.daemon.events import PROTOCOL_STEP_STARTED  # noqa: PLC0415
                step_id = (
                    protocol.steps[0].id if protocol.steps else None
                )
                bus.publish(
                    PROTOCOL_STEP_STARTED,
                    data={
                        "plan_id": plan_id,
                        "step_id": step_id,
                        "protocol_id": protocol_name,
                    },
                    root=str(self.root),
                )
            except Exception:  # noqa: BLE001
                pass  # bus errors never abort start()

        return plan_id

    def step(self, plan_id: str, bus: Any = None) -> dict:
        """Return the current step dict for *plan_id*.

        Does NOT advance the index — call :meth:`complete_step` when the
        client's AI has acted on the step.

        Parameters
        ----------
        plan_id:
            The plan identifier returned by :meth:`start`.
        bus:
            Optional :class:`~research_os.daemon.events.EventBus` for
            ``protocol.step_started`` events.

        Returns
        -------
        dict
            One of:

            * ``{id, name, description, index, total_steps}`` — the current step.
            * ``{"status": "completed", "plan_id": ..., "protocol": ...,
              "total_steps": ...}`` — terminal marker when the plan is done
              or *plan_id* is unknown (never raises for a missing plan).
        """
        plan = self._load_plan(plan_id)
        if plan is None:
            return {
                "status": "not_found",
                "plan_id": plan_id,
            }

        if plan.get("status") == "completed":
            return {
                "status": "completed",
                "plan_id": plan_id,
                "protocol": plan.get("protocol"),
                "total_steps": None,  # cheaply unknown without rehydrate
            }

        protocol = self._rehydrate(plan["protocol"])
        steps = protocol.steps
        idx = plan.get("step_index", 0)

        if idx >= len(steps):
            # Step index out of range — treat as completed (terminal).
            return {
                "status": "completed",
                "plan_id": plan_id,
                "protocol": plan.get("protocol"),
                "total_steps": len(steps),
            }

        s = steps[idx]
        result = {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "index": idx,
            "total_steps": len(steps),
        }

        # Optional event — fail-open.
        if bus is not None:
            try:
                from research_os.daemon.events import PROTOCOL_STEP_STARTED  # noqa: PLC0415
                bus.publish(
                    PROTOCOL_STEP_STARTED,
                    data={
                        "plan_id": plan_id,
                        "step_id": s.id,
                        "protocol_id": plan.get("protocol"),
                    },
                    root=str(self.root),
                )
            except Exception:  # noqa: BLE001
                pass

        return result

    def complete_step(self, plan_id: str, result: Any) -> dict:
        """Record the client-supplied result for the current step and advance.

        Parameters
        ----------
        plan_id:
            The plan identifier returned by :meth:`start`.
        result:
            Arbitrary serialisable value produced by the client's AI for the
            completed step.

        Returns
        -------
        dict
            Summary of the updated plan:
            ``{id, protocol, step_index, status, total_steps}``.

        Raises
        ------
        KeyError
            When *plan_id* is not found on disk (clear typed error).
        """
        plan = self._load_plan(plan_id)
        if plan is None:
            raise KeyError(f"Plan {plan_id!r} not found")

        protocol = self._rehydrate(plan["protocol"])
        steps = protocol.steps
        idx = plan.get("step_index", 0)

        # Record result keyed by the step's id (fall back to index string).
        step_key: str
        if idx < len(steps) and steps[idx].id:
            step_key = steps[idx].id
        else:
            step_key = str(idx)

        plan.setdefault("results", {})[step_key] = result
        plan["step_index"] = idx + 1

        if plan["step_index"] >= len(steps):
            plan["status"] = "completed"

        self._save_plan(plan)

        return {
            "id": plan["id"],
            "protocol": plan["protocol"],
            "step_index": plan["step_index"],
            "status": plan["status"],
            "total_steps": len(steps),
        }

    def get_plan(self, plan_id: str) -> dict | None:
        """Return the persisted plan dict, or None if missing/corrupt.

        Used by §13.5 ``GET /v1/plans/{id}``.
        """
        return self._load_plan(plan_id)

    def list_plans(self) -> list[dict]:
        """Return plan summaries for all plans under this root.

        Corrupt / unreadable files are silently skipped.  Used by §13.5
        ``GET /v1/plans``.

        Returns
        -------
        list[dict]
            Each entry: ``{id, protocol, step_index, status, created_at}``.
            ``total_steps`` is omitted to keep the listing cheap (no
            protocol rehydration).
        """
        summaries: list[dict] = []
        if not self._plans_dir.exists():
            return summaries
        for f in sorted(self._plans_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "id" not in data:
                    continue
                summaries.append(
                    {
                        "id": data.get("id"),
                        "protocol": data.get("protocol"),
                        "step_index": data.get("step_index"),
                        "status": data.get("status"),
                        "created_at": data.get("created_at"),
                    }
                )
            except Exception:  # noqa: BLE001
                pass  # skip corrupt files
        return summaries
