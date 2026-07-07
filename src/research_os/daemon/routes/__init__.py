"""Daemon route registration modules."""
from __future__ import annotations

from .capabilities import register_capabilities
from .consent import register_consent
from .core import register_core
from .events import register_events
from .gates import register_gates
from .health import register_health
from .jobs import register_jobs
from .lineage import register_lineage
from .memory import register_memory
from .notifications import register_notifications
from .plans import register_plans
from .runs import register_runs
from .sandbox import register_sandbox
from .state import register_state
from .staleness import register_staleness
from .streams import register_streams
from .workflows import register_workflows

__all__ = [
    "register_capabilities",
    "register_consent",
    "register_core",
    "register_events",
    "register_gates",
    "register_health",
    "register_jobs",
    "register_lineage",
    "register_memory",
    "register_notifications",
    "register_plans",
    "register_runs",
    "register_sandbox",
    "register_state",
    "register_staleness",
    "register_streams",
    "register_workflows",
]
