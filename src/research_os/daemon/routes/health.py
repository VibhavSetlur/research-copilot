from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_health(app, daemon) -> None:
    async def healthz(request):
        from research_os import __version__

        return JSONResponse(
            {
                "status": "ok",
                "service": "research-os-daemon",
                "version": __version__,
                "serving": daemon.serving,
                "roots": daemon.registry.roots(),
            }
        )

    async def get_healthz_v1(request):
        return await healthz(request)

    app.routes.extend(
        [
            Route("/healthz", healthz, methods=["GET"]),
            Route("/v1/healthz", get_healthz_v1, methods=["GET"]),
        ]
    )
