"""Daemon core — the central serving object and status report.

The :class:`Daemon` is the live daemon: it resolves the project root using the
SAME resolver the stdio MCP server uses, carries a :class:`DaemonConfig`, owns
the background task queue, multi-root state registry, event spine, and durable
run journal, serves the localhost HTTP surface, and produces a
:class:`DaemonStatus` snapshot from the existing :class:`ResearchLedger` and
active plan.

Everything here reuses existing engine functions — no routing, state, or
protocol logic is re-implemented (strangler-fig; see docs/ARCHITECTURE.md).
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .config import DaemonConfig
from .events import EventBus
from .gates import GateQueue
from .registry import WorkspaceRegistry
from .runstore import RunStore
from .tasks import TaskQueue

logger = logging.getLogger("research-os.daemon")


@dataclass
class DaemonStatus:
    """A point-in-time, read-only snapshot of daemon + project state.

    Serializable to a plain dict for the future ``/v1/state`` endpoint and
    the ``research-os daemon status`` CLI.
    """

    serving: bool
    version: str
    config: dict
    root: str | None
    project_initialized: bool
    active_protocol: str | None = None
    progress: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    roots: list = field(default_factory=list)
    jobs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "serving": self.serving,
            "version": self.version,
            "config": self.config,
            "root": self.root,
            "project_initialized": self.project_initialized,
            "active_protocol": self.active_protocol,
            "progress": self.progress,
            "notes": self.notes,
            "roots": self.roots,
            "jobs": self.jobs,
        }


class Daemon:
    """The Research OS gateway daemon — the live serving core.

    Construct with an explicit root + config, or use :meth:`for_root` /
    :meth:`autoresolve` to build one the way the MCP server resolves its
    workspace.
    """

    def __init__(self, root: Path | None, config: DaemonConfig) -> None:
        self.root = Path(root) if (root is not None and not isinstance(root, Path)) else root
        self.config = config
        # Set True by serve() once the process is actually listening.
        self._serving = False
        # Event spine (Phase 1.5): append-only bus the task queue, gateway,
        # dashboard, and MCP sidecar all publish to / subscribe from. This is
        # the substrate that makes the daemon observable in real time instead
        # of poll-only. stdlib-only, import-cheap.
        self.events = EventBus()
        # Multi-root state registry + background task queue (Phase 1).
        # Both are stdlib-only and import-cheap; constructing them here keeps
        # status() and serve() working off the same engine seams. The queue
        # publishes job lifecycle events to the bus.
        self.registry = WorkspaceRegistry(cache_ttl=config.state_cache_ttl)
        self.tasks = TaskQueue(
            max_workers=config.task_workers,
            bus=self.events,
            notify_command=getattr(config, "notify_command", "") or "",
        )
        # Durable run journal (Phase 1.7): persists every run to
        # <root>/.os_state/runs/ as a provenance manifest + full log, driven
        # off the event bus so the queue stays journal-agnostic. Only active
        # when we have a concrete root to write under.
        self.runstore = RunStore(root) if root is not None else None
        # Persistent HITL gate queue (§12.4), None when no root, like runstore.
        self.gates = GateQueue(root, event_bus=self.events) if root is not None else None
        self._journal = None
        self._journal_thread = None
        if root is not None:
            self.registry.register(root)

    # ── construction helpers ──────────────────────────────────────────
    @classmethod
    def autoresolve(cls, **overrides: object) -> "Daemon":
        """Build a daemon for the auto-resolved project root.

        Reuses the server's resolver (``RESEARCH_OS_WORKSPACE`` env ->
        nearest ``.os_state`` -> cwd) so the daemon and the MCP server
        always agree on which project is active.
        """
        root = _resolve_root()
        return cls.for_root(root, **overrides)

    @classmethod
    def for_root(cls, root: Path | str | None, **overrides: object) -> "Daemon":
        # Normalize to Path early so config resolution, status(), and the
        # registry all get a real Path (callers may pass a str).
        if root is not None and not isinstance(root, Path):
            root = Path(root)
        config = DaemonConfig.resolve(root=root, **overrides)
        return cls(root=root, config=config)

    # ── introspection ─────────────────────────────────────────────────
    @property
    def serving(self) -> bool:
        return self._serving

    def status(self) -> DaemonStatus:
        """Produce a read-only status snapshot from existing engine state.

        Never raises: any read failure is captured as a note so the status
        endpoint/CLI stays robust even on a half-initialized project.
        """
        from research_os import __version__

        notes: list = []
        root = self.root
        initialized = bool(root and (root / ".os_state").exists())
        active_protocol: str | None = None
        progress: dict = {}

        if initialized and root is not None:
            active_protocol = _safe_active_protocol(root, notes)
            progress = _safe_progress(root, notes)
        elif root is None:
            notes.append("no project root resolved")
        else:
            notes.append("root has no .os_state (run 'research-os init')")

        return DaemonStatus(
            serving=self._serving,
            version=__version__,
            config={
                "host": self.config.host,
                "port": self.config.port,
                "base_url": self.config.base_url,
                "enable_gateway": self.config.enable_gateway,
                "enable_dashboard": self.config.enable_dashboard,
                "sandbox_mode": self.config.sandbox_mode,
                "task_workers": self.config.task_workers,
                "state_cache_ttl": self.config.state_cache_ttl,
            },
            root=str(root) if root else None,
            project_initialized=initialized,
            active_protocol=active_protocol,
            progress=progress,
            notes=notes,
            roots=self.registry.roots(),
            jobs=self.tasks.snapshot(limit=10),
        )

    # ── execution ─────────────────────────────────────────────────────
    def run_command(
        self,
        cmd: "str | list[str]",
        *,
        name: str | None = None,
        cwd: str | None = None,
        env: dict | None = None,
        root: str | None = None,
        shell: bool = False,
        inputs: "list[str] | None" = None,
        track_packages: "list[str] | None" = None,
        track_artifacts: bool = True,
        requested_mem_mb: int | None = None,
        extra_spec: dict | None = None,
    ) -> str:
        """Submit an external command as a background job and return its id.

        This is the "any language" entry point: anything with a CLI
        (Rscript, julia, bash, snakemake, nextflow, sbatch, …) runs through
        the SubprocessRunner, streaming output as ``job.log`` events on the
        bus and recording a bounded result handle. Defaults ``cwd`` to the
        daemon's root so commands run in the project by default.

        Provenance (git commit, environment, input hashes) is captured at
        submit time and recorded on the job so the durable run journal can
        make the run reproducible. Capture is best-effort and never blocks.
        """
        from . import provenance as _prov
        from . import resource_budget as _budget
        from .runners import SubprocessRunner

        effective_cwd = cwd or (str(self.root) if self.root else None)
        effective_root = root or (str(self.root) if self.root else None)
        # Resolve the sandbox tier so the run is actually BOUNDED. Without
        # this the resource_budget never binds and a runaway long job can
        # take down a shared node (it just spawned an unbounded subprocess).
        # The tier is derived from the daemon's sandbox_mode + the project's
        # runtime block (shared_server / compute_environment); on a shared
        # HPC box this resolves to the universal resource floor (rlimits +
        # wallclock) instead of a futile container/userns probe.
        budget_root = effective_root or effective_cwd or "."
        sandbox_tier = _budget.resolve_sandbox_tier(
            budget_root,
            sandbox_mode=getattr(self.config, "sandbox_mode", "auto"),
        )
        runner = SubprocessRunner(
            cmd,
            cwd=effective_cwd,
            env=env,
            shell=shell,
            track_artifacts=track_artifacts,
            sandbox=sandbox_tier,
            budget_root=budget_root,
            requested_mem_mb=requested_mem_mb,
        )
        job_name = name or (cmd if isinstance(cmd, str) else " ".join(cmd))
        prov = _prov.capture(
            effective_root or effective_cwd or ".",
            inputs=inputs,
            packages=track_packages,
        )
        spec = {
            "cmd": cmd,
            "cwd": effective_cwd,
            "shell": shell,
            "env_overrides": sorted(env.keys()) if env else [],
        }
        if extra_spec:
            spec.update(extra_spec)
        # Ensure the durable journal is capturing before we submit, so even
        # programmatic use (no serve()) gets a persistent record.
        self._start_journal()
        # Lazy-start the worker pool too: run_command is a valid entry point
        # without a full serve() (programmatic use + the HTTP POST /v1/jobs
        # path), and submit() refuses on a cold queue. start() is idempotent.
        self.tasks.start()
        job_id = self.tasks.submit(
            runner,
            name=job_name[:120],
            root=effective_root,
            kind="subprocess",
            spec=spec,
            provenance=prov,
        )
        try:
            from .events import RUN_STARTED
            # FIX 4: cap the command representation in the event payload to
            # ~512 chars so event JSONL stays bounded. The full argv lives in
            # the run manifest/spec — this is observability only.
            _cmd_repr = cmd if isinstance(cmd, str) else " ".join(str(a) for a in cmd)
            if len(_cmd_repr) > 512:
                _cmd_repr = _cmd_repr[:509] + "..."
            self.events.publish(
                RUN_STARTED,
                {"run_id": job_id, "command": _cmd_repr, "cwd": effective_cwd},
                root=effective_root,
            )
        except Exception:  # noqa: BLE001 - a bus failure must never break submit
            pass
        return job_id

    def run_container(
        self,
        image: str,
        command: "str | list[str]",
        *,
        name: str | None = None,
        cwd: str | None = None,
        env: dict | None = None,
        root: str | None = None,
        gpus: str | None = None,
        network: bool = False,
        inputs: "list[str] | None" = None,
        track_packages: "list[str] | None" = None,
        track_artifacts: bool = True,
    ) -> str:
        """Run a command inside a container image as a tracked background job.

        For reproducible long runs shipped as a Docker/Podman image (or a step
        of a containerised pipeline). Same tracking + provenance contract as
        run_command — journaled, artifact-captured, cancellable — plus the run
        records the exact image (and its content digest) so it is recreatable
        bit-for-bit. The project root is mounted into the container so outputs
        land back in the workspace and get auto-provenanced.

        Returns the daemon job id immediately. Raises if no container CLI is
        available (caller can fall back to run_command for a native run).
        """
        from . import provenance as _prov
        from .runners import DockerRunner

        effective_cwd = cwd or (str(self.root) if self.root else None)
        effective_root = root or (str(self.root) if self.root else None)
        mount = effective_root or effective_cwd or os.getcwd()
        runner = DockerRunner(
            image,
            command,
            cwd=effective_cwd,
            mount_root=mount,
            env=env,
            gpus=gpus,
            network=network,
            track_artifacts=track_artifacts,
        )
        prov = _prov.capture(
            effective_root or effective_cwd or ".",
            inputs=inputs,
            packages=track_packages,
            snapshot_env=True,  # long/containerised jobs: pin the env for repro
        )
        prov["container_image"] = image
        spec = {
            "image": image,
            "command": command,
            "cwd": effective_cwd,
            "gpus": gpus,
            "network": network,
            "env_overrides": sorted(env.keys()) if env else [],
        }
        self._start_journal()
        self.tasks.start()
        job_name = name or f"docker:{image}"
        return self.tasks.submit(
            runner,
            name=job_name[:120],
            root=effective_root,
            kind="container",
            spec=spec,
            provenance=prov,
        )

    def submit_job(
        self,
        script: str,
        *,
        scheduler: str = "slurm",
        name: str | None = None,
        cwd: str | None = None,
        env: dict | None = None,
        root: str | None = None,
        inputs: "list[str] | None" = None,
        track_packages: "list[str] | None" = None,
        track_artifacts: bool = True,
        poll_interval: float = 5.0,
    ) -> str:
        """Submit a job to an HPC scheduler (SLURM, …) as a background run.

        This is the "HPC-native" entry point (JUDGE-6): ``script`` is either
        a batch script path or an inline command. It is submitted via the
        scheduler adapter (``sbatch``), and a daemon worker thread owns the
        wait — polling the scheduler until the cluster job is terminal and
        streaming each state transition as a ``job.log`` event. Returns the
        daemon job id immediately; the scheduler's own job id appears in the
        run's result + journal once submitted.

        Same provenance + artifact capture as run_command, so scheduler jobs
        get the full journal/reproduce treatment. ``submit_job`` does NOT
        block: the cluster job may run for hours.
        """
        from . import provenance as _prov
        from .schedulers import SchedulerRunner

        effective_cwd = cwd or (str(self.root) if self.root else None)
        effective_root = root or (str(self.root) if self.root else None)
        runner = SchedulerRunner(
            script,
            scheduler=scheduler,
            cwd=effective_cwd,
            env=env,
            poll_interval=poll_interval,
            track_artifacts=track_artifacts,
        )
        job_name = name or f"{scheduler}:{script}"
        prov = _prov.capture(
            effective_root or effective_cwd or ".",
            inputs=inputs,
            packages=track_packages,
            snapshot_env=True,  # HPC jobs: pin the exact env for reproducibility
        )
        spec = {
            "cmd": [script],
            "script": script,
            "scheduler": scheduler,
            "cwd": effective_cwd,
            "shell": False,
            "env_overrides": sorted(env.keys()) if env else [],
        }
        self._start_journal()
        self.tasks.start()  # idempotent; allow submit_job without a full serve()
        return self.tasks.submit(
            runner,
            name=job_name[:120],
            root=effective_root,
            kind="scheduler",
            spec=spec,
            provenance=prov,
        )

    # ── run journal (durable, Phase 1.7) ──────────────────────────────
    def _start_journal(self) -> None:
        """Begin persisting runs to the durable journal off the event bus.

        Idempotent. Also rehydrates: any run whose last persisted status was
        non-terminal (the daemon died mid-run) is marked INTERRUPTED so the
        history reflects reality instead of showing a phantom live run.
        """
        if self.runstore is None or self._journal is not None:
            return
        import threading as _threading

        from .runstore import RunJournal

        # Rehydrate: mark orphaned (non-terminal) runs from a prior crash.
        # Collect what we interrupt so the researcher is told their in-flight
        # work didn't finish (the "walked away, box rebooted" case) the moment
        # they reconnect, instead of silently finding a phantom-dead run later.
        interrupted_ids: list[str] = []
        try:
            for rid in self.runstore.detect_orphans():
                self.runstore.mark_interrupted(rid)
                interrupted_ids.append(rid)
        except Exception:  # noqa: BLE001 - rehydration must not block startup
            logger.warning("run journal rehydration failed", exc_info=True)
        if interrupted_ids and self.root is not None:
            try:
                from . import notifications as _ntfy

                _ntfy.emit_runs_interrupted(
                    self.root,
                    interrupted_ids,
                    notify_command=getattr(self.config, "notify_command", "") or "",
                )
            except Exception:  # noqa: BLE001 - notification must never block startup
                logger.debug("interrupted-runs notification failed", exc_info=True)

        journal = RunJournal(self.runstore, bus=self.events)
        self._journal = journal

        # Wire the autonomous-continuation hook (opt-in via config.continue_
        # command). When a run reaches terminal, maybe_continue decides whether
        # to re-prompt the researcher's agent toward the active goal. No-op
        # unless the researcher opted in; hop-limited; never blocks the journal.
        if self.root is not None:
            _root = self.root

            def _on_terminal_run(manifest: dict) -> None:
                try:
                    from . import continuation as _cont

                    summary = {
                        "id": manifest.get("id"),
                        "name": manifest.get("name"),
                        "status": manifest.get("status"),
                        "returncode": (manifest.get("result") or {}).get("returncode"),
                    }
                    _cont.maybe_continue(
                        _root, config=self.config, finished_run=summary
                    )
                except Exception:  # noqa: BLE001 - continuation must not break journal
                    logger.debug("autonomous continuation hook failed", exc_info=True)

            journal.on_terminal = _on_terminal_run

        def _pump() -> None:
            # Backfill any events already on the bus (defensive — the journal
            # starts before HTTP accepts requests, but a programmatic submit
            # could race), then stream live. Skip heartbeat sentinels.
            for event in self.events.subscribe(backfill=1000):
                if getattr(event, "kind", None) == "heartbeat":
                    continue
                journal.handle(event)

        thread = _threading.Thread(
            target=_pump, name="ro-daemon-journal", daemon=True
        )
        self._journal_thread = thread
        thread.start()
        logger.debug("run journal started under %s", self.runstore.runs_dir)

    # ── reproduce (Phase 1.10) ────────────────────────────────────────
    def reproduce_run(
        self,
        run_id: str,
        *,
        cwd: str | None = None,
        timeout: float | None = None,
        poll_interval: float = 0.15,
    ) -> dict:
        """Re-execute a recorded run and compare its outputs to the original.

        Reads the recorded manifest, re-runs its exact command in its
        recorded working directory (overridable via ``cwd``), waits for the
        new run to finish, then compares the fresh artifacts to the recorded
        ones by path + sha256. Returns a report:

            {
              "original_id": ..., "repro_id": ...,
              "original_status": ..., "repro_status": ...,
              "comparison": {verdict, matched, changed, missing, ...},
              "verdict": reproduced | diverged | incomplete,
            }

        Raises ValueError if the run is unknown or has no recorded command.
        """
        import time as _time

        from . import reproduce as _repro

        if self.runstore is None:
            raise ValueError("no workspace resolved — cannot reproduce a run")
        manifest = self.runstore.read_manifest(run_id)
        if manifest is None:
            raise ValueError(f"no recorded run: {run_id}")
        spec = manifest.get("spec") or {}
        cmd = spec.get("cmd") or spec.get("command")
        if not cmd:
            raise ValueError(
                f"run {run_id} has no recorded command to reproduce "
                "(only subprocess runs are reproducible)"
            )
        recorded_artifacts = manifest.get("artifacts") or []
        run_cwd = cwd or spec.get("cwd")
        shell = bool(spec.get("shell", False))

        # Propagate the original run's input paths so the re-run records its
        # own provenance.inputs — otherwise the reproduced run drops out of
        # the lineage graph and freshness checks (it would read as "no
        # recorded inputs"). Recorded paths may be relative to the run's cwd,
        # so resolve them to absolute against run_cwd before re-hashing (the
        # daemon process cwd is not necessarily the run's cwd). Paths are
        # re-hashed fresh against current disk.
        import os as _os
        recorded_inputs = ((manifest.get("provenance") or {}).get("inputs") or {})
        base = run_cwd or "."
        input_paths = [
            p if _os.path.isabs(p) else _os.path.join(base, p)
            for p in recorded_inputs
        ] or None

        # Make sure the queue + journal are live so the re-run is recorded.
        self.tasks.start()
        self._start_journal()
        repro_id = self.run_command(
            cmd,
            name=f"reproduce:{run_id}",
            cwd=run_cwd,
            shell=shell,
            inputs=input_paths,
        )

        # Wait for the re-run to reach a terminal state.
        deadline = None if timeout is None else _time.time() + timeout
        while True:
            job = self.tasks.get(repro_id)
            status = job.status.value if job else None
            if status in ("succeeded", "failed", "cancelled"):
                break
            if deadline is not None and _time.time() > deadline:
                break
            _time.sleep(poll_interval)

        # Let the journal flush the terminal manifest, then read it back.
        _time.sleep(0.3)
        repro_manifest = self.runstore.read_manifest(repro_id) or {}
        fresh_artifacts = repro_manifest.get("artifacts") or []

        comparison = _repro.compare_artifacts(recorded_artifacts, fresh_artifacts)
        return {
            "original_id": run_id,
            "repro_id": repro_id,
            "original_status": manifest.get("status"),
            "repro_status": repro_manifest.get("status"),
            "command": cmd,
            "cwd": run_cwd,
            "comparison": comparison,
            "verdict": comparison["verdict"],
        }

    # ── resume (Phase 4: resumable runs) ──────────────────────────────
    def resume_run(
        self,
        run_id: str,
        *,
        cwd: str | None = None,
    ) -> dict:
        """Resume an interrupted/paused run by re-launching its recorded spec.

        The "user walked away, the box rebooted, the long job didn't finish"
        recovery lever. orient recommends ``resume_interrupted``; this is the
        API that acts on it.

        We can't snapshot arbitrary process memory, so resume is a *contract*,
        not magic: the original run's spec (cmd / cwd / shell / inputs) is
        re-submitted as a FRESH journaled run, linked to the original via
        ``resumed_from`` so lineage stays intact. For checkpoint-AWARE jobs
        (the common case for multi-hour compute — they periodically write their
        own checkpoint and accept a resume flag), the daemon exports:

          * ``RO_RESUME=1`` — tells the program this is a resume, not a cold
            start, so it should pick up from its last checkpoint.
          * ``RO_RESUME_FROM=<original_run_id>`` — the run being resumed.
          * ``RO_CHECKPOINT_DIR=<run_dir>/checkpoint`` — a stable per-run dir
            the program can read/write its checkpoint to across resumes.

        A program that ignores these simply restarts cleanly (no data lost,
        just recomputed) — so resume is always safe, and *seamless* for jobs
        that opt in. Returns the new run id + linkage. Raises ValueError if the
        run is unknown or has no recorded command.
        """
        if self.runstore is None:
            raise ValueError("no workspace resolved — cannot resume a run")
        manifest = self.runstore.read_manifest(run_id)
        if manifest is None:
            raise ValueError(f"no recorded run: {run_id}")
        status = (manifest.get("status") or "").lower()
        if status not in ("interrupted", "paused", "failed", "cancelled"):
            raise ValueError(
                f"run {run_id} is '{status}', not resumable "
                "(only interrupted/paused/failed/cancelled runs can be resumed)"
            )

        # Liveness guard (BLOCK-2 / F-4): if the original run's recorded process
        # is STILL ALIVE on this host, refuse to re-spawn — a duplicate would
        # double-write / double-compute / corrupt outputs. Only applies when the
        # PID was recorded on this same host (cross-host PIDs are meaningless).
        import os as _os_live
        import socket as _socket_live
        rec_pid = manifest.get("pid")
        rec_host = manifest.get("host")
        if rec_pid and (rec_host in (None, _socket_live.gethostname())):
            try:
                _os_live.kill(int(rec_pid), 0)
                alive = True
            except (OSError, ValueError, TypeError):
                alive = False
            if alive:
                raise ValueError(
                    f"run {run_id} still has a live process (pid={rec_pid}) — "
                    "refusing to resume and spawn a duplicate. Stop the original "
                    "first, then resume."
                )

        spec = manifest.get("spec") or {}
        # Scheduler-aware resume (MAJOR-3): a SLURM/HPC run MUST be re-dispatched
        # through the scheduler (sbatch), NOT re-launched as a local subprocess
        # on the daemon/login node. Branch on the recorded kind/scheduler before
        # falling through to the local run_command path below.
        kind = (manifest.get("kind") or "").lower()
        scheduler = spec.get("scheduler")
        if kind == "scheduler" or scheduler:
            script = spec.get("script") or spec.get("cmd") or spec.get("command")
            if isinstance(script, (list, tuple)):
                script = script[0] if script else None
            if not script:
                raise ValueError(
                    f"scheduler run {run_id} has no recorded script to resume"
                )
            self.tasks.start()
            self._start_journal()
            new_id = self.submit_job(
                script,
                scheduler=scheduler or "slurm",
                name=f"resume:{run_id}",
                cwd=cwd or spec.get("cwd"),
                root=spec.get("root"),
            )
            return {
                "resumed_from": run_id,
                "new_run_id": new_id,
                "command": script,
                "cwd": cwd or spec.get("cwd"),
                "scheduler": scheduler or "slurm",
            }

        cmd = spec.get("cmd") or spec.get("command")
        if not cmd:
            raise ValueError(
                f"run {run_id} has no recorded command to resume "
                "(only subprocess runs are resumable)"
            )
        run_cwd = cwd or spec.get("cwd")
        shell = bool(spec.get("shell", False))

        # Re-resolve recorded inputs to absolute (mirrors reproduce_run) so the
        # resumed run keeps its place in the lineage graph.
        import os as _os

        recorded_inputs = ((manifest.get("provenance") or {}).get("inputs") or {})
        base = run_cwd or "."
        input_paths = [
            p if _os.path.isabs(p) else _os.path.join(base, p)
            for p in recorded_inputs
        ] or None

        # A stable checkpoint dir for THIS run lineage (keyed on the original
        # so successive resumes share one checkpoint location).
        ckpt_dir = str(self.runstore.runs_dir / run_id / "checkpoint")
        try:
            _os.makedirs(ckpt_dir, exist_ok=True)
        except OSError:
            pass
        resume_env = {
            "RO_RESUME": "1",
            "RO_RESUME_FROM": run_id,
            "RO_CHECKPOINT_DIR": ckpt_dir,
        }

        self.tasks.start()
        self._start_journal()
        new_id = self.run_command(
            cmd,
            name=f"resume:{run_id}",
            cwd=run_cwd,
            env=resume_env,
            shell=shell,
            inputs=input_paths,
            extra_spec={"resumed_from": run_id},
        )
        return {
            "resumed_from": run_id,
            "new_run_id": new_id,
            "command": cmd,
            "cwd": run_cwd,
            "checkpoint_dir": ckpt_dir,
            "note": (
                "Resumed as a fresh journaled run. Checkpoint-aware programs "
                "continue from RO_CHECKPOINT_DIR; others restart cleanly."
            ),
        }

    def rebuild_stale(
        self,
        *,
        limit: int = 200,
        dry_run: bool = False,
        timeout: float | None = None,
    ) -> dict:
        """Re-run exactly the stale sub-DAG, in dependency order.

        A minimal ``make`` built on data already captured: assess
        staleness over the lineage graph, take every input-stale or
        transitive-stale run, topologically sort it (producers before
        consumers), and reproduce each in order. After each rebuild the
        freshness is re-assessed, so fixing an upstream result clears the
        transitive staleness of its descendants — a descendant only
        rebuilds if it is still stale by the time its turn comes.

        ``dry_run`` returns the plan (ordered ids + why) without executing.
        Returns:
            {
              "plan":     [run_id, ...],          # topo-ordered stale set
              "rebuilt":  [{run_id, repro_id, verdict}, ...],
              "skipped":  [{run_id, reason}, ...], # fixed transitively / no cmd
              "dry_run":  bool,
              "counts":   {planned, rebuilt, skipped},
            }
        """
        from . import lineage as _lineage
        from . import staleness as _stale

        if self.runstore is None:
            raise ValueError("no workspace resolved — cannot rebuild")

        def _hash(path: str) -> "str | None":
            import os

            from . import provenance as _prov
            root = getattr(self, "root", None)
            p = path if os.path.isabs(path) else os.path.join(root or ".", path)
            try:
                return _prov.hash_file(p)
            except Exception:
                return None

        manifests = self.runstore.recent_manifests(limit=limit)
        graph = _lineage.build_lineage(manifests)
        report = _stale.assess(manifests, _hash)
        stale_set = set(report["stale"])
        plan = [r for r in _lineage.topo_order(graph, stale_set) if r in stale_set]

        if dry_run:
            return {
                "plan": plan,
                "rebuilt": [],
                "skipped": [],
                "dry_run": True,
                "counts": {"planned": len(plan), "rebuilt": 0, "skipped": 0},
            }

        rebuilt: list[dict] = []
        skipped: list[dict] = []
        for rid in plan:
            # Re-assess: an earlier rebuild may have cleared this one's
            # transitive staleness (its upstream is now fresh).
            fresh_manifests = self.runstore.recent_manifests(limit=limit)
            cur = _stale.assess(fresh_manifests, _hash)
            if rid not in set(cur["stale"]):
                skipped.append({"run_id": rid, "reason": "no longer stale"})
                continue
            try:
                result = self.reproduce_run(rid, timeout=timeout)
                rebuilt.append({
                    "run_id": rid,
                    "repro_id": result["repro_id"],
                    "verdict": result["verdict"],
                })
            except ValueError as exc:
                skipped.append({"run_id": rid, "reason": str(exc)})

        return {
            "plan": plan,
            "rebuilt": rebuilt,
            "skipped": skipped,
            "dry_run": False,
            "counts": {
                "planned": len(plan),
                "rebuilt": len(rebuilt),
                "skipped": len(skipped),
            },
        }

    # ── lifecycle ─────────────────────────────────────────────────────
    def serve(self) -> None:
        """Start the persistent daemon: task queue + read-only HTTP server.

        Blocks until interrupted. The HTTP layer (starlette/uvicorn) is in
        the optional ``[daemon]`` extra and imported lazily; if it's absent
        this raises a clear "install research-os[daemon]" error rather than
        a bare ImportError.

        The stdio MCP server is untouched — this is a separate, additive,
        opt-in surface (strangler-fig).
        """
        from . import server as _server

        # Fail fast with the actionable hint BEFORE we start the queue, so a
        # missing extra doesn't leave a worker pool dangling.
        _server._require_web_stack()
        self.tasks.start()
        self._start_journal()
        self._serving = True
        # Startup self-check: look at the project, note any problems (structure
        # drift, interrupted runs, unframed intake), and leave an AI-facing
        # note at .os_state/daemon_notes.md so the next agent turn (or an
        # autonomous loop) sees + addresses them. Best-effort — never blocks
        # serving.
        if self.root is not None:
            try:
                from . import health_notes as _health

                _health.write_notes(self.root)
            except Exception:  # noqa: BLE001 - self-check must not stop the daemon
                logger.debug("startup self-check failed", exc_info=True)
        # Discovery handshake: advertise this daemon to the MCP surface and
        # any local client by dropping a descriptor in the project's
        # .os_state/. Best-effort — a write failure must not stop serving.
        #
        # Cleanup contract: the finally block below removes the descriptor on
        # a clean in-process return, but uvicorn's own SIGTERM/SIGINT handling
        # can terminate the process WITHOUT unwinding back here (and SIGKILL
        # never can). So the descriptor is NOT a reliable liveness signal on
        # its own — the READER (sys_daemon / any client) is the source of
        # truth: it confirms the advertised PID is actually alive before
        # treating the daemon as running, and reports a stale descriptor
        # otherwise. A leftover file is therefore harmless.
        self._write_discovery()
        # Periodic self-check tick (B1): keep daemon_notes fresh DURING the
        # session, not just at startup, so a condition the daemon detects an
        # hour into a long run actually reaches the AI on its next turn (the
        # reasoning side reads the refreshed sidecar by-shape). Background daemon
        # thread; stopped in the finally block. interval<=0 disables it.
        self._stop_self_check = threading.Event()
        self._self_check_thread: threading.Thread | None = None
        interval = getattr(self.config, "self_check_interval", 0) or 0
        if self.root is not None and interval > 0:
            def _self_check_loop() -> None:
                from . import health_notes as _h
                while not self._stop_self_check.wait(interval):
                    # Iterate EVERY registered project, not just self.root, so a
                    # daemon fronting several projects (e.g. a PI supervising
                    # multiple students) refreshes notes + escalation for all of
                    # them — supervision is multi-root.
                    roots: list = []
                    try:
                        roots = list(self.registry.roots())
                    except Exception:  # noqa: BLE001
                        roots = []
                    if self.root is not None and str(self.root) not in roots:
                        roots.append(str(self.root))
                    for r in roots:
                        try:
                            _h.write_notes(r)
                        except Exception:  # noqa: BLE001 - never kill the daemon
                            logger.debug("periodic self-check failed for %s", r,
                                         exc_info=True)
            self._self_check_thread = threading.Thread(
                target=_self_check_loop, name="ro-self-check", daemon=True,
            )
            self._self_check_thread.start()
        try:
            _server.serve(self)
        finally:
            self._serving = False
            if getattr(self, "_stop_self_check", None) is not None:
                self._stop_self_check.set()
            self._clear_discovery()
            self.tasks.shutdown(wait=False)

    # ── discovery handshake (Phase 3) ─────────────────────────────────
    def _write_discovery(self) -> None:
        """Advertise the running daemon via <root>/.os_state/daemon.json."""
        if self.root is None:
            return
        try:
            from datetime import datetime, timezone

            from research_os import __version__ as _v

            from .discovery import write_discovery

            write_discovery(
                self.root,
                host=self.config.host,
                port=self.config.port,
                version=str(_v),
                started_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:  # pragma: no cover - best-effort
            logger.debug("discovery write failed: %s", exc)

    def _clear_discovery(self) -> None:
        """Remove the discovery descriptor on shutdown (best-effort)."""
        if self.root is None:
            return
        try:
            from .discovery import clear_discovery

            clear_discovery(self.root)
        except Exception as exc:  # pragma: no cover - best-effort
            logger.debug("discovery clear failed: %s", exc)


# ── private helpers: reuse the existing engine, never reimplement ──────
def _resolve_root() -> Path | None:
    """Resolve the active project root the same way the MCP server does."""
    try:
        from research_os.server.entry import _resolve_project_root
        return _resolve_project_root()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("root resolution failed: %s", exc)
        return None


def _safe_active_protocol(root: Path, notes: list) -> str | None:
    """Read the active plan's protocol via the existing router helper."""
    try:
        from research_os.tools.actions.router import _load_active_plan
        plan = _load_active_plan(root) or {}
        proto = plan.get("protocol") or plan.get("protocol_name")
        return str(proto) if proto else None
    except Exception as exc:
        notes.append(f"active-plan read skipped: {type(exc).__name__}")
        return None


def _safe_progress(root: Path, notes: list) -> dict:
    """Read a compact progress digest via existing engine state.

    Tries the planning progress digest first; falls back to a minimal
    ledger summary. Always returns a dict.
    """
    try:
        from research_os.tools.actions.research.planning import progress_digest
        digest = progress_digest(root)
        if isinstance(digest, dict):
            return digest
    except Exception as exc:
        notes.append(f"progress digest skipped: {type(exc).__name__}")
    return {}
