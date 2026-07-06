"""Run journal — the durable, queryable record of every run.

JUDGE-2 (docs/ROADMAP.md §8): three needs collapse into one primitive.
The RunStore persists each run to ``<root>/.os_state/runs/<run_id>/`` as:

  - ``run.json``  — the manifest: spec + provenance + status transitions +
                    result + artifacts. Written atomically (temp+rename) on
                    every lifecycle transition so a crash never corrupts it.
  - ``log.txt``   — the full captured stdout/stderr (the bounded tail in
                    run.json is for quick reads; this is the complete log).

This makes jobs survive a daemon restart (durability), makes every run
reproducible (provenance), and gives the gateway/dashboard a permanent,
queryable history (observability) — all from one file format.

stdlib only (json, os, time, pathlib, tempfile). No locking beyond atomic
rename: each run owns its own directory, so concurrent runs never touch
the same files.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RUNS_DIRNAME = "runs"
MANIFEST_NAME = "run.json"
LOG_NAME = "log.txt"


class RunStore:
    """Read/write the durable run journal under a project root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        # FIX 6: per-store lock guards read_manifest+write_manifest in
        # patch_manifest() so the env-snapshot background thread and the
        # journal pump thread can never clobber each other's writes.
        self._manifest_lock = threading.Lock()

    @property
    def runs_dir(self) -> Path:
        return self.root / ".os_state" / RUNS_DIRNAME

    def _run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    # ── writing ────────────────────────────────────────────────────────
    def patch_manifest(self, run_id: str, patch_fn) -> bool:
        """Atomically apply ``patch_fn(manifest) → None`` under the store lock.

        Reads the current manifest, calls ``patch_fn`` (which mutates it
        in-place), then writes it back — all under ``_manifest_lock``.  This
        prevents the env-snapshot background thread from clobbering fields
        written by the journal pump thread (or vice versa).

        FIX 6: the env-snapshot thread uses this instead of a bare
        read→mutate→write so the transition never loses ``result``,
        ``duration_s``, or any other field written concurrently.

        Returns ``True`` if the patch was applied, ``False`` if the manifest
        didn't exist or the write failed.  Never raises.
        """
        with self._manifest_lock:
            try:
                manifest = self.read_manifest(run_id)
                if manifest is None:
                    return False
                patch_fn(manifest)
                self._write_manifest_unlocked(run_id, manifest)
                return True
            except Exception:  # noqa: BLE001 - best-effort, never raises
                return False

    def write_manifest(self, run_id: str, manifest: dict) -> "Path":
        """Atomically write a run's manifest under the store lock.

        Wraps the internal ``_write_manifest_unlocked`` so callers that
        already hold ``_manifest_lock`` (e.g. ``patch_manifest``) can call
        the unlocked variant, while all other callers get the lock for free.
        """
        with self._manifest_lock:
            return self._write_manifest_unlocked(run_id, manifest)

    def _write_manifest_unlocked(self, run_id: str, manifest: dict) -> "Path":
        """Write a run's manifest without acquiring the lock (caller holds it)."""
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / MANIFEST_NAME
        fd, tmp = tempfile.mkstemp(dir=str(run_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2, default=str)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        return target

    def append_log(self, run_id: str, line: str) -> None:
        """Append one line to a run's full log. Best-effort, never raises."""
        run_dir = self._run_dir(run_id)
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            with (run_dir / LOG_NAME).open("a", encoding="utf-8") as fh:
                fh.write(line.rstrip("\n") + "\n")
        except OSError:
            pass

    # ── reading ────────────────────────────────────────────────────────
    def read_manifest(self, run_id: str) -> dict | None:
        """Read one run's manifest, or None if missing/corrupt."""
        target = self._run_dir(run_id) / MANIFEST_NAME
        if not target.exists():
            return None
        try:
            with target.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    def read_log(self, run_id: str, *, tail: int | None = None) -> list[str]:
        """Read a run's full log (or the last ``tail`` lines)."""
        target = self._run_dir(run_id) / LOG_NAME
        if not target.exists():
            return []
        try:
            with target.open(encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            return []
        if tail is not None and tail >= 0:
            return lines[-tail:]
        return lines

    def list_runs(self, *, limit: int = 50) -> list[dict]:
        """List run manifests, newest first (by submitted_at, then dir mtime).

        Returns lightweight summaries (no full provenance/result) so a list
        call stays cheap even with thousands of runs.
        """
        if not self.runs_dir.exists():
            return []
        entries: list[tuple[float, dict]] = []
        for child in self.runs_dir.iterdir():
            if not child.is_dir():
                continue
            # Per-record fault isolation: a single malformed manifest must NOT
            # sink the whole list (which would silently abandon every orphan in
            # detect_orphans). Skip the bad one, keep the rest.
            try:
                manifest = self.read_manifest(child.name)
                if manifest is None:
                    continue
                sort_key = manifest.get("submitted_at")
                if not isinstance(sort_key, (int, float)):
                    try:
                        sort_key = child.stat().st_mtime
                    except OSError:
                        sort_key = 0.0
                entries.append((float(sort_key), self._summarize(manifest)))
            except Exception:  # noqa: BLE001 - one bad record can't break recovery
                logger.warning("skipping unreadable run manifest %s", child.name, exc_info=True)
                continue
        entries.sort(key=lambda e: e[0], reverse=True)
        return [summary for _key, summary in entries[:limit]]

    @staticmethod
    def _summarize(manifest: dict) -> dict:
        """Lightweight view for list endpoints. Type-defensive: a manifest whose
        `result` isn't a dict or `artifacts` isn't a list must not raise (a bad
        record would otherwise sink list_runs → detect_orphans → all recovery)."""
        result = manifest.get("result")
        result = result if isinstance(result, dict) else {}
        artifacts = manifest.get("artifacts")
        artifacts = artifacts if isinstance(artifacts, list) else []
        return {
            "id": manifest.get("id"),
            "name": manifest.get("name"),
            "kind": manifest.get("kind"),
            "status": manifest.get("status"),
            "submitted_at": manifest.get("submitted_at"),
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "duration_s": manifest.get("duration_s"),
            "root": manifest.get("root"),
            "returncode": result.get("returncode"),
            "artifact_count": len(artifacts),
        }

    # ── rehydration ────────────────────────────────────────────────────
    def recent_manifests(self, *, limit: int = 100) -> list[dict]:
        """Full manifests for the most recent runs (for restart rehydration)."""
        summaries = self.list_runs(limit=limit)
        out: list[dict] = []
        for s in summaries:
            rid = s.get("id")
            if not rid:
                continue
            full = self.read_manifest(rid)
            if full is not None:
                out.append(full)
        return out

    def detect_orphans(self) -> list[str]:
        """Run ids whose last persisted status was non-terminal AND not paused.

        After an unclean shutdown these runs were RUNNING/QUEUED but the
        process died — they can never resume, so the daemon should mark them
        INTERRUPTED on startup rather than leave them looking live forever.

        ``paused`` is deliberately treated as terminal-for-recovery: a paused
        run is a USER INTENT, not a crash artifact, so it must NOT be rewritten
        to ``interrupted`` on restart (that would lose the pause and make the
        watchdog nag to resume a run the researcher intentionally held).
        """
        orphans: list[str] = []
        terminal = {"succeeded", "failed", "cancelled", "interrupted", "paused"}
        for s in self.list_runs(limit=10_000):
            status = (s.get("status") or "").lower()
            if status and status not in terminal:
                rid = s.get("id")
                if rid:
                    orphans.append(rid)
        return orphans

    def detect_stalled_runs(self, stall_seconds: float = 1800.0) -> list[dict]:
        """Running runs whose log hasn't advanced in ``stall_seconds``.

        A long job wedged mid-run (deadlock, silent hang, lost scheduler) looks
        identical to a healthy one until it goes terminal. By comparing each
        RUNNING run's ``log.txt`` mtime to now, the daemon can flag "this job
        hasn't produced output in N minutes — it may be stuck" so the researcher
        isn't waiting on a dead job. Read-only, best-effort.

        Returns [{id, name, idle_seconds}] for each stalled run.
        """
        stalled: list[dict] = []
        now = time.time()
        terminal = {"succeeded", "failed", "cancelled", "interrupted", "paused"}
        for s in self.list_runs(limit=10_000):
            status = (s.get("status") or "").lower()
            if not status or status in terminal:
                continue
            rid = s.get("id")
            if not rid:
                continue
            try:
                log_path = self._run_dir(rid) / "log.txt"
                # Use the log mtime if present, else the manifest's; a run that
                # has produced no output yet falls back to its start time.
                if log_path.exists():
                    last = log_path.stat().st_mtime
                else:
                    last = float(s.get("started_at") or s.get("submitted_at") or 0)
                if last <= 0:
                    continue
                idle = now - last
                if idle >= stall_seconds:
                    stalled.append({
                        "id": rid, "name": s.get("name"),
                        "idle_seconds": round(idle),
                    })
            except Exception:  # noqa: BLE001 - a stall probe must never raise
                continue
        return stalled

    def mark_interrupted(self, run_id: str) -> None:
        """Rewrite an orphaned run's manifest as INTERRUPTED. Best-effort."""
        manifest = self.read_manifest(run_id)
        if manifest is None:
            return
        manifest["status"] = "interrupted"
        manifest.setdefault("finished_at", time.time())
        transitions = manifest.setdefault("transitions", [])
        transitions.append({"status": "interrupted", "at": time.time(),
                             "note": "daemon restarted while run was active"})
        try:
            self.write_manifest(run_id, manifest)
        except OSError:
            pass


def build_manifest(
    *,
    run_id: str,
    name: str,
    kind: str,
    status: str,
    root: str | None,
    spec: dict | None = None,
    provenance: dict | None = None,
    submitted_at: float | None = None,
    environment: dict | None = None,
    **extra: Any,
) -> dict:
    """Construct a fresh run manifest with the standard fields.

    ``environment`` is the optional environment snapshot produced by
    :func:`research_os.daemon.provenance.capture_environment`.  It is
    captured once at submit time and threaded here so the manifest carries
    a restorable record of the exact Python/pip/conda state.  Callers that
    do not pass it get ``None`` (omitted from the manifest) so existing
    callers and tests are unaffected.
    """
    manifest: dict = {
        "id": run_id,
        "name": name,
        "kind": kind,
        "status": status,
        "root": root,
        "submitted_at": submitted_at if submitted_at is not None else time.time(),
        "spec": spec or {},
        "provenance": provenance or {},
        "transitions": [{"status": status, "at": time.time()}],
        "artifacts": [],
    }
    # Only include the environment key when a snapshot was actually captured,
    # so manifests produced by existing callers remain unchanged.
    if environment is not None:
        manifest["environment"] = environment
    manifest.update(extra)
    return manifest


def archive_artifacts_to_cas(
    root: str | Path | None,
    run_id: str,
    artifacts: list[dict],
) -> list[dict]:
    """Copy each recorded output artifact into the CAS and annotate its entry.

    For each artifact whose file exists on disk, calls ``CASStore.store`` and
    writes the returned blob id back onto the artifact dict as ``blob_id``
    (plus ``blob_oversize=True`` when the file exceeded the size cap).
    Existing artifact fields are preserved; no field is removed.

    This is a *pure helper* extracted from the terminal-transition handler so
    it is independently unit-testable.  It must NEVER raise: all errors are
    swallowed and the original artifact list is returned intact (possibly with
    fewer ``blob_id`` annotations than expected, but never corrupt).

    Args:
        root:      Project root that owns the CAS store.  When ``None`` the
                   function returns ``artifacts`` unchanged (no root = no CAS).
        run_id:    The run whose artifacts are being archived.
        artifacts: The list of artifact dicts from the run manifest.  Each
                   dict has at least ``path`` (relative to root) and ``change``
                   (``"created"`` | ``"modified"``).  The list is mutated
                   in-place *and* returned so callers can chain or discard the
                   return value.

    Returns:
        The same ``artifacts`` list, annotated with ``blob_id`` where blobs
        were stored successfully.
    """
    if not root or not artifacts:
        return artifacts
    try:
        from .cas import CASStore
        cas = CASStore(root)
        root_path = Path(root)
        for art in artifacts:
            try:
                rel = art.get("path")
                if not rel:
                    continue
                abs_path = root_path / rel
                if not abs_path.is_file():
                    continue
                cas_artifact = cas.store(abs_path, run_id)
                if cas_artifact is not None:
                    art["blob_id"] = cas_artifact.id
                    if cas_artifact.oversize:
                        art["blob_oversize"] = True
            except Exception:  # noqa: BLE001 - per-file failure must not abort the pass
                continue
    except Exception:  # noqa: BLE001 - CAS failure must never break a run
        pass
    return artifacts


class RunJournal:
    """Drives a RunStore from the event bus — the strangler-fig bridge.

    The task queue already emits ``job.{submitted,started,succeeded,failed,
    cancelled}`` (each carrying a full job snapshot) and ``job.log`` line
    events. RunJournal subscribes to those and persists them to the durable
    store, so the queue needs zero knowledge of the journal. Wiring is a
    single ``daemon.bus.subscribe`` consumed on a background thread.

    Each run is keyed by job id. The first event for a job writes the
    manifest (with provenance from the job spec); subsequent transitions
    rewrite it; ``job.log`` lines append to the full log file and grow the
    bounded ``log_tail``.
    """

    LOG_TAIL_MAX = 200

    def __init__(self, store: RunStore, bus: Any = None) -> None:
        self.store = store
        self._bus = bus
        self._tails: dict[str, list[str]] = {}
        # Optional callback the daemon sets to react to a run reaching a
        # terminal state (e.g. autonomous continuation). Signature:
        # on_terminal(manifest: dict) -> None. Best-effort, never blocks the
        # journal — kept out of RunJournal so the journal stays config-free.
        self.on_terminal: Any = None

    def handle(self, event: Any) -> None:
        """Process one event object (must have .kind and .data). Never raises."""
        try:
            kind = getattr(event, "kind", None)
            data = getattr(event, "data", None) or {}
            if kind == "job.log":
                self._on_log(data)
            elif kind == "job.pid":
                self._on_pid(data)
            elif isinstance(kind, str) and kind.startswith("job."):
                self._on_transition(kind, data)
        except Exception:  # noqa: BLE001 - journal must never break the bus
            pass

    def _on_pid(self, data: dict) -> None:
        """Persist the child PID (+ host) so crash-recovery can check liveness."""
        job_id = data.get("job_id") or data.get("id")
        pid = data.get("pid")
        if not job_id or pid is None:
            return
        manifest = self.store.read_manifest(job_id)
        if manifest is None:
            return
        import socket
        manifest["pid"] = pid
        manifest["host"] = socket.gethostname()
        try:
            self.store.write_manifest(job_id, manifest)
        except OSError:
            pass

    def _on_log(self, data: dict) -> None:
        job_id = data.get("job_id") or data.get("id")
        line = data.get("line")
        if not job_id or line is None:
            return
        self.store.append_log(job_id, str(line))
        tail = self._tails.setdefault(job_id, [])
        tail.append(str(line))
        if len(tail) > self.LOG_TAIL_MAX:
            del tail[: len(tail) - self.LOG_TAIL_MAX]

    def _on_transition(self, kind: str, data: dict) -> None:
        snap = data.get("job") or {}
        job_id = data.get("job_id") or snap.get("id")
        if not job_id:
            return
        status = (snap.get("status") or data.get("status") or "").lower()
        existing = self.store.read_manifest(job_id)
        # Terminal-once idempotency guard: if this run is ALREADY terminal, a
        # second terminal event (bus replay / duplicate emit) must be a no-op —
        # otherwise it double-appends a transition and double-fires on_terminal
        # (which double-advances autonomous continuation, spending compute/tokens
        # twice). Non-terminal → terminal still proceeds normally.
        _TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
        if existing is not None:
            prev = (existing.get("status") or "").lower()
            if prev in _TERMINAL and status in _TERMINAL:
                return
        _is_new_manifest = existing is None
        if _is_new_manifest:
            manifest = build_manifest(
                run_id=job_id,
                name=snap.get("name", "run"),
                kind=snap.get("kind", "callable"),
                status=status or "queued",
                root=snap.get("root"),
                spec=snap.get("spec") or {},
                provenance=snap.get("provenance") or {},
                submitted_at=snap.get("submitted_at"),
            )
        else:
            manifest = existing
            manifest["status"] = status or manifest.get("status")
            manifest.setdefault("transitions", []).append(
                {"status": status, "at": time.time()}
            )
        # Timing + result mirror the snapshot.
        for fld in ("started_at", "finished_at", "duration_s", "error"):
            if snap.get(fld) is not None:
                manifest[fld] = snap[fld]
        if snap.get("result") is not None:
            manifest["result"] = snap["result"]
        result = snap.get("result")
        # Hoist output artifacts to the top level so list summaries and the
        # provenance record surface them without digging into result.
        if isinstance(result, dict) and result.get("artifacts"):
            manifest["artifacts"] = result["artifacts"]
            if result.get("artifacts_truncated"):
                manifest["artifacts_truncated"] = True
        # Reconcile command success with run success: a subprocess job that
        # *ran* (job status "succeeded") but whose command exited nonzero is a
        # FAILED run from the researcher's point of view. Cancelled runs keep
        # their cancelled status.
        if (
            status == "succeeded"
            and isinstance(result, dict)
            and result.get("returncode") not in (None, 0)
        ):
            if result.get("cancelled"):
                manifest["status"] = "cancelled"
            else:
                manifest["status"] = "failed"
            status = manifest["status"]
        tail = self._tails.get(job_id)
        if tail:
            manifest["log_tail"] = list(tail)
        # ── CAS archiving (terminal runs only) ──────────────────────────────
        # Copy each recorded output artifact into the content-addressed store
        # and annotate the artifact entry with its blob id.  Runs only at
        # terminal transitions so we archive the FINAL artifact list, not an
        # intermediate one.  All best-effort: CAS failure must NEVER fail or
        # corrupt the run — the write_manifest call below still runs.
        _terminal_statuses = {"succeeded", "failed", "cancelled"}
        if status in _terminal_statuses:
            try:
                run_root = manifest.get("root")
                arts = manifest.get("artifacts")
                if run_root and isinstance(arts, list) and arts:
                    manifest["artifacts"] = archive_artifacts_to_cas(
                        run_root, job_id, arts
                    )
            except Exception:  # noqa: BLE001 - CAS pass must not break the journal
                pass
        # ── run.completed / run.failed events (additive, best-effort) ───────
        # Publish high-level run lifecycle events on the bus after CAS so the
        # payload includes the final artifact list.  Separate from job.* events
        # — these are the Phase-6 canonical run surface the SSE /v1/stream
        # exposes.  Guard: bus may be None (headless / test mode).
        if status in _terminal_statuses and self._bus is not None:
            try:
                from .events import RUN_COMPLETED, RUN_FAILED
                result_obj = manifest.get("result") or {}
                exit_code = result_obj.get("returncode") if isinstance(result_obj, dict) else None
                arts_field = manifest.get("artifacts") or []
                artifact_count = len(arts_field) if isinstance(arts_field, list) else 0
                artifact_paths = [
                    a.get("path") or a.get("blob_id", "")
                    for a in arts_field
                    if isinstance(a, dict)
                ][:50]  # bounded: never dump file contents
                if status == "succeeded":
                    self._bus.publish(
                        RUN_COMPLETED,
                        {
                            "run_id": job_id,
                            "exit_code": exit_code,
                            "duration": manifest.get("duration_s"),
                            "artifacts": artifact_paths if artifact_paths else artifact_count,
                        },
                    )
                else:
                    self._bus.publish(
                        RUN_FAILED,
                        {
                            "run_id": job_id,
                            "error": str(manifest.get("error") or status),
                            "exit_code": exit_code,
                        },
                    )
            except Exception:  # noqa: BLE001 - bus failure must never break journaling
                pass
        self.store.write_manifest(job_id, manifest)
        # ── async environment snapshot (new manifests only) ──────────────────
        # pip freeze + conda export are slow (seconds on large envs).  We fire
        # them on a daemon thread so the pump thread is NEVER blocked.  When
        # the snapshot is ready, it is merged back into the manifest with a
        # second atomic write.  If the run is already terminal by the time the
        # snapshot lands (common for short jobs), the manifest is still updated
        # because it was already written above and we simply patch it.
        # Best-effort: any failure is silently swallowed.
        if _is_new_manifest:
            def _patch_env(_jid=job_id, _store=self.store):
                try:
                    from . import provenance as _prov
                    env_snap = _prov.capture_environment()
                    # FIX 6: use patch_manifest (read+apply+write under the
                    # store lock) so this background thread can never clobber
                    # fields written concurrently by the journal pump thread
                    # (result, duration_s, CAS-annotated artifacts, etc.).
                    def _apply(m):
                        if "environment" not in m:
                            m["environment"] = env_snap
                    _store.patch_manifest(_jid, _apply)
                except Exception:  # noqa: BLE001 - env patch must never break anything
                    pass

            threading.Thread(
                target=_patch_env,
                name=f"ro-env-snap-{job_id}",
                daemon=True,
            ).start()
        # Free the in-memory tail once the run is terminal.
        if status in _terminal_statuses:
            self._tails.pop(job_id, None)
            # Staleness refresh stays inline (it's fast + cheap and the
            # reasoning-side gate reads it right after a run finishes).
            try:
                self._refresh_staleness_verdict()
            except Exception:  # noqa: BLE001
                pass
            # The terminal HOOK is dispatched to a SEPARATE thread (F-5): the
            # autonomous-continuation hook may run a continue_command for up to
            # continue_timeout seconds, and the journal has a SINGLE pump thread.
            # Running it inline would block journaling of every OTHER run's
            # events for that whole window (head-of-line blocking — observability
            # + durability degrade exactly when a long autonomous job finishes).
            # The hook is contractually "never blocks the journal"; this makes
            # the implementation match.
            hook = self.on_terminal
            if hook is not None:
                def _fire_hook(_m=manifest, _hook=hook):
                    try:
                        _hook(_m)
                    except Exception:  # noqa: BLE001 - hook must not break the journal
                        pass

                threading.Thread(
                    target=_fire_hook,
                    name=f"ro-terminal-{job_id}",
                    daemon=True,
                ).start()

    def _refresh_staleness_verdict(self) -> None:
        """Recompute + persist the freshness verdict from the run journal.

        Runs after every terminal run so the on-disk verdict the staleness
        floor gate reads (.os_state/staleness/verdict.json) stays current
        without requiring an explicit authenticated call. Pure best-effort.
        """
        try:
            from . import provenance as _prov
            from . import staleness as _stale

            root = getattr(self.store, "root", None)
            if root is None:
                return
            manifests = self.store.recent_manifests(limit=200)
            if not manifests:
                return
            hash_file = _prov.hash_fn_for_root(root)
            report = _stale.assess(manifests, hash_file)
            _stale.write_verdict(root, report)
        except Exception:  # noqa: BLE001 - verdict refresh must never break the journal
            logger.debug("staleness verdict refresh failed", exc_info=True)
