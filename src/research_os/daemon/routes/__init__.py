"""Daemon route registration modules."""
from __future__ import annotations

from .capabilities import register_capabilities
from .consent import register_consent
from .continuation import register_continuation
from .core import register_core
from .events import register_events
from .gates import register_gates
from .health import register_health
from .jobs import register_jobs
from .lineage import register_lineage
from .memory import register_memory
from .metrics import register_metrics
from .notifications import register_notifications
from .orient import register_orient
from .plans import register_plans
from .plugins import register_plugins
from .runs import register_runs
from .sandbox import register_sandbox
from .state import register_state
from .staleness import register_staleness
from .streams import register_streams
from .workflows import register_workflows

__all__ = [
    "register_capabilities",
    "register_consent",
    "register_continuation",
    "register_core",
    "register_events",
    "register_gates",
    "register_health",
    "register_jobs",
    "register_lineage",
    "register_memory",
    "register_metrics",
    "register_notifications",
    "register_orient",
    "register_plans",
    "register_plugins",
    "register_runs",
    "register_sandbox",
    "register_state",
    "register_staleness",
    "register_streams",
    "register_workflows",
]
