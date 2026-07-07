from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_sandbox(app, daemon) -> None:
    async def get_sandbox(request):
        from .. import sandbox as _sb

        refresh = request.query_params.get("refresh", "false") == "true"
        try:
            caps = _sb.detect_sandbox(refresh=refresh)
            payload = caps.to_dict()
            payload["service"] = "research-os"
            payload["default_limits"] = _sb.ResourceLimits().to_dict()
            from .. import resource_budget as _budget

            root_q = request.query_params.get("root")
            root = root_q or getattr(daemon, "root", None)
            if root:
                payload["resource_budget"] = _budget.budget_summary(root)
                payload["effective_limits"] = _budget.resolve_run_limits(root, base=_sb.ResourceLimits()).to_dict()
        except Exception as exc:
            return JSONResponse({"service": "research-os", "available": False, "error": str(exc)})
        return JSONResponse(payload)

    app.routes.append(Route("/v1/sandbox", get_sandbox, methods=["GET"]))
