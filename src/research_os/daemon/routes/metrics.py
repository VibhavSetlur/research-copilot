from __future__ import annotations

from starlette.responses import PlainTextResponse
from starlette.routing import Route


_METRIC_NAMES = (
    "research_os_daemon_up",
    "research_os_daemon_roots",
    "research_os_daemon_jobs",
    "research_os_daemon_runs",
)


def register_metrics(app, daemon) -> None:
    async def get_metrics(request):
        roots = list(daemon.registry.roots())
        jobs_snapshot = daemon.tasks.snapshot(root=None, limit=0)
        runs = 0
        if getattr(daemon, "runstore", None) is not None:
            try:
                runs = len(daemon.runstore.list_runs(limit=1000))
            except Exception:
                runs = 0
        lines = [
            "# HELP research_os_up Daemon availability.",
            "# TYPE research_os_up gauge",
            "research_os_up 1",
            "# HELP research_os_roots Registered project roots.",
            "# TYPE research_os_roots gauge",
            f"research_os_roots {len(roots)}",
            "# HELP research_os_jobs Current daemon jobs.",
            "# TYPE research_os_jobs gauge",
            f"research_os_jobs {len(jobs_snapshot.get('jobs') or [])}",
            "# HELP research_os_runs_total Stored runs.",
            "# TYPE research_os_runs_total gauge",
            f"research_os_runs_total {runs}",
            "# HELP research_os_events_total Stored events.",
            "# TYPE research_os_events_total gauge",
            f"research_os_events_total {getattr(daemon.events, 'last_seq', 0)}",
        ]
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    app.routes.append(Route("/v1/metrics", get_metrics, methods=["GET"]))
