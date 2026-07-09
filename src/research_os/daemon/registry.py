"""Workspace registry — one daemon, many project roots (read path).

Design decision (docs/ROADMAP.md §6): ONE daemon serves MANY project
roots, keyed by absolute path, because the daemon already resolves the
root per-request. This module is the registry: given a root, it produces a
read-only state view by calling the SAME engine read helpers the stdio MCP
server and the Phase 0 Daemon.status() use. No routing/state logic is
reimplemented here (strangler-fig).

Phase 1 scope: read only. The registry caches lightweight handles
(resolved root + last status) but every state read goes straight to the
live ledger/plan so a status call never serves stale data. A short TTL
cache exists only to avoid hammering the filesystem under rapid polling
(e.g. a dashboard refreshing every second).

stdlib only — must import without the [daemon] extra.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("research-os.daemon.registry")


class Workspace:
    """A registered project root and its cached read-only state view."""

    def __init__(self, root: Path, cache_ttl: float = 1.0) -> None:
        self.root = root.resolve()
        self._cache_ttl = cache_ttl
        self._cached: dict | None = None
        self._cached_at: float = 0.0
        self._lock = threading.Lock()

    @property
    def initialized(self) -> bool:
        return (self.root / ".os_state").exists()

    def state(self, force: bool = False) -> dict:
        """Read-only state view: initialized flag, active protocol, progress,
        and a compact ledger summary. Cached for ``cache_ttl`` seconds.

        Never raises — every sub-read is guarded and any failure is recorded
        as a note (mirrors Daemon.status() robustness)."""
        now = time.time()
        with self._lock:
            if (
                not force
                and self._cached is not None
                and (now - self._cached_at) < self._cache_ttl
            ):
                return self._cached
        view = self._read_state()
        with self._lock:
            self._cached = view
            self._cached_at = time.time()
        return view

    def _read_state(self) -> dict:
        notes: list[str] = []
        initialized = self.initialized
        view: dict = {
            "root": str(self.root),
            "initialized": initialized,
            "active_protocol": None,
            "progress": {},
            "ledger": {},
            "notes": notes,
        }
        if not initialized:
            notes.append("root has no .os_state (run 'research-os init')")
            return view
        view["active_protocol"] = _safe_active_protocol(self.root, notes)
        view["progress"] = _safe_progress(self.root, notes)
        view["ledger"] = _safe_ledger_summary(self.root, notes)
        return view


class WorkspaceRegistry:
    """Thread-safe registry of project roots the daemon is serving."""

    def __init__(self, cache_ttl: float = 1.0) -> None:
        self._cache_ttl = cache_ttl
        self._workspaces: dict[str, Workspace] = {}
        self._lock = threading.Lock()

    def register(self, root: Path | str) -> Workspace:
        """Register (or return the existing) workspace for ``root``."""
        resolved = Path(root).expanduser().resolve()
        key = str(resolved)
        with self._lock:
            ws = self._workspaces.get(key)
            if ws is None:
                ws = Workspace(resolved, cache_ttl=self._cache_ttl)
                self._workspaces[key] = ws
                logger.debug("registered workspace %s", key)
            return ws

    def get(self, root: Path | str) -> Workspace | None:
        key = str(Path(root).expanduser().resolve())
        with self._lock:
            return self._workspaces.get(key)

    def roots(self) -> list[str]:
        with self._lock:
            return sorted(self._workspaces.keys())

    def snapshot(self) -> dict:
        """Read-only multi-root view for /v1/state (no root filter)."""
        with self._lock:
            workspaces = list(self._workspaces.values())
        return {
            "roots": [ws.state() for ws in workspaces],
            "count": len(workspaces),
        }


# ── private read helpers: reuse the existing engine, never reimplement ──
def _safe_active_protocol(root: Path, notes: list) -> str | None:
    try:
        from research_os.tools.actions.router import _load_active_plan

        plan = _load_active_plan(root) or {}
        proto = plan.get("protocol") or plan.get("protocol_name")
        return str(proto) if proto else None
    except Exception as exc:  # noqa: BLE001
        notes.append(f"active-plan read skipped: {type(exc).__name__}")
        return None


def _safe_progress(root: Path, notes: list) -> dict:
    try:
        from research_os.tools.actions.research.planning import progress_digest

        digest = progress_digest(root)
        if isinstance(digest, dict):
            return digest
    except Exception as exc:  # noqa: BLE001
        notes.append(f"progress digest skipped: {type(exc).__name__}")
    return {}


def _safe_ledger_summary(root: Path, notes: list) -> dict:
    """Compact ledger view via the ResearchLedger public read API."""
    try:
        from research_os.state.state_ledger import ResearchLedger

        ledger = ResearchLedger(root / ".os_state" / "state_ledger.json")
        data = ledger.get()
        if not isinstance(data, dict):
            return {}
        # Whitelist a few high-signal fields; the full ledger can be large
        # and we don't want to dump everything to a status endpoint.
        return {
            k: data[k]
            for k in ("current_phase", "phase", "step", "current_path", "tokens_used")
            if k in data
        }
    except Exception as exc:  # noqa: BLE001
        notes.append(f"ledger summary skipped: {type(exc).__name__}")
        return {}
