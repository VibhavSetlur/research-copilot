from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_core(app, daemon) -> None:
    async def get_domain(request):
        from pathlib import Path as _Path

        from ..domains import detect

        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        if root is None:
            return JSONResponse({"available": False, "error": "no project root resolved"})
        result = detect(root)
        out = result.as_dict()
        out["root"] = str(root)
        out["available"] = True
        return JSONResponse(out)

    app.routes.append(Route("/v1/domain", get_domain, methods=["GET"]))
