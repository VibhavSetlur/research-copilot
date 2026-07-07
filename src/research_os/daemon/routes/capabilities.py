from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_capabilities(app, daemon) -> None:
    async def get_capabilities(request):
        from .. import capabilities as _caps

        want_schemas = request.query_params.get("tools") == "full"
        root_q = request.query_params.get("root")
        target = daemon
        if root_q:
            target = daemon.registry.get(root_q) or daemon.registry.register(root_q)
        try:
            payload = _caps.build_capabilities(target, include_tool_schemas=want_schemas)
        except Exception as exc:
            return JSONResponse({"service": "research-os", "available": False, "error": str(exc)})
        return JSONResponse(payload)

    app.routes.append(Route("/v1/capabilities", get_capabilities, methods=["GET"]))
