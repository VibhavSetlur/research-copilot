"""Research OS daemon — the multi-protocol gateway.

A persistent, headless, localhost daemon that owns the master execution state
machine and exposes Research OS to any client (IDE, web UI, CLI, MCP sidecar)
at once.

DESIGN STANCE (read docs/ARCHITECTURE.md before extending this):

* Strangler-fig. The daemon WRAPS the existing engine functions
  (``router.route_request``, ``ResearchLedger``, ``dispatch._handle_tool_call``)
  — it never re-implements routing, state, or protocol logic.
* Additive + opt-in. The stdio MCP server (``research_os.server``) keeps
  working untouched. Nothing in core imports this package at load time.
* Lazy heavy deps. The web/serving stack lives in the optional
  ``research-os[daemon]`` extra and is imported lazily inside the methods
  that need it, so ``import research_os.daemon`` stays cheap and never
  fails on a core-only install.

What it provides: a multi-root state registry, a background task queue, a
universal subprocess + scheduler (SLURM) runner, a durable run journal with
crash recovery, provenance / lineage / staleness / reproduce, resumable runs,
sandbox tiers + resource budgets, a notification spine, consent / hard gates,
an event bus, orientation, and HTTP endpoints (read-only + auth-gated mutating,
including an opt-in OpenAI-compatible gateway). A read-only web dashboard is the
one surface still to come.
"""
from __future__ import annotations

from .artifacts import diff as artifacts_diff
from .artifacts import snapshot as artifacts_snapshot
from .compare import compare_runs
from .config import DaemonConfig
from .core import Daemon, DaemonStatus
from .domains import (
    GENERIC,
    DetectionResult,
    DomainProfile,
    all_profiles,
    detect,
    get_profile,
)
from .events import Event, EventBus
from .lineage import (
    ancestors,
    build_lineage,
    descendants,
    lineage_to_mermaid,
    topo_order,
)
from .registry import Workspace, WorkspaceRegistry
from .reproduce import compare_artifacts
from .runners import DockerRunner, RunResult, SubprocessRunner, docker_available
from .runstore import RunJournal, RunStore, build_manifest
from .schedulers import SchedulerResult, SchedulerRunner, SlurmAdapter, get_adapter
from .staleness import assess as assess_staleness
from .staleness import check_input_staleness
from .tasks import Job, JobStatus, TaskQueue
from .protocol_driver import ProtocolDriver
from .workflow import DAGExecutor, Digraph

__all__ = [
    "Daemon",
    "DaemonConfig",
    "DaemonStatus",
    "WorkspaceRegistry",
    "Workspace",
    "TaskQueue",
    "Job",
    "JobStatus",
    "EventBus",
    "Event",
    "SubprocessRunner",
    "DockerRunner",
    "docker_available",
    "RunResult",
    "RunStore",
    "RunJournal",
    "build_manifest",
    "artifacts_snapshot",
    "artifacts_diff",
    "compare_artifacts",
    "compare_runs",
    "build_lineage",
    "lineage_to_mermaid",
    "ancestors",
    "descendants",
    "topo_order",
    "assess_staleness",
    "check_input_staleness",
    "SchedulerRunner",
    "SchedulerResult",
    "SlurmAdapter",
    "get_adapter",
    "DomainProfile",
    "DetectionResult",
    "detect",
    "get_profile",
    "all_profiles",
    "GENERIC",
    "DAGExecutor",
    "Digraph",
    "ProtocolDriver",
]
