from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_state(app, daemon) -> None:
    async def get_state(request):
        root = request.query_params.get("root")
        if root:
            ws = daemon.registry.get(root) or daemon.registry.register(root)
            return JSONResponse({"root": ws.state()})
        return JSONResponse(daemon.registry.snapshot())

    async def get_supervision(request):
        from .. import health_notes as _h

        roots = list(daemon.registry.roots())
        if daemon.root is not None and str(daemon.root) not in roots:
            roots.append(str(daemon.root))
        return JSONResponse(_h.run_self_check_all(roots))

    app.routes.extend(
        [
            Route("/v1/state", get_state, methods=["GET"]),
            Route("/v1/supervision", get_supervision, methods=["GET"]),
        ]
    )
