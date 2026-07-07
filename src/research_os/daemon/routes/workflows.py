from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_workflows(app, daemon) -> None:
    async def get_workflows(request):
        from .. import workflows as _wf

        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        introspect = request.query_params.get("introspect", "true") != "false"
        try:
            payload = _wf.survey_workflows(root, introspect=introspect)
        except Exception as exc:
            return JSONResponse({"service": "research-os", "available": False, "error": str(exc)})
        return JSONResponse(payload)

    app.routes.append(Route("/v1/workflows", get_workflows, methods=["GET"]))
