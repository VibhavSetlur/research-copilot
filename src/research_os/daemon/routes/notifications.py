from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_notifications(app, daemon) -> None:
    async def get_notifications(request):
        from .. import notifications as _ntfy

        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        if not root:
            return JSONResponse({"available": False, "error": "no project root resolved"})
        undelivered = request.query_params.get("undelivered") == "true"
        raw_limit = request.query_params.get("limit")
        try:
            limit = max(0, int(raw_limit)) if raw_limit else 100
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        records = _ntfy.read_outbox(root, undelivered_only=undelivered, limit=limit)
        return JSONResponse({"available": True, "notifications": records, "count": len(records)})

    app.routes.append(Route("/v1/notifications", get_notifications, methods=["GET"]))
