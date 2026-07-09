from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_orient(app, daemon) -> None:
    async def get_orient(request):
        from .. import orient as _orient

        root_q = request.query_params.get("root")
        limit_raw = request.query_params.get("limit")
        limit = None
        if limit_raw is not None:
            try:
                limit = max(0, int(limit_raw))
            except ValueError:
                return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        try:
            payload = _orient.build_orientation(daemon, root=root_q, limit=limit or 50)
        except Exception as exc:  # noqa: BLE001 - orientation must never 500
            return JSONResponse({"service": "research-os", "available": False, "error": str(exc)})
        return JSONResponse(payload)

    app.routes.append(Route("/v1/orient", get_orient, methods=["GET"]))
