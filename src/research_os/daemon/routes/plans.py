from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .shared import mutating_auth_error


def register_plans(app, daemon) -> None:
    def _protocol_driver_for(request):
        from pathlib import Path as _Path

        from ..protocol_driver import ProtocolDriver

        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        if root is None:
            return None, JSONResponse({"error": "no project root resolved", "code": "no_root"}, status_code=400)
        return ProtocolDriver(root), None

    async def get_plans(request):
        driver, err = _protocol_driver_for(request)
        if err is not None:
            return err
        return JSONResponse({"plans": driver.list_plans()})

    async def get_plan(request):
        driver, err = _protocol_driver_for(request)
        if err is not None:
            return err
        plan_id = request.path_params["plan_id"]
        plan = driver.get_plan(plan_id)
        if plan is None:
            return JSONResponse({"error": "plan not found"}, status_code=404)
        return JSONResponse(plan)

    async def post_plans(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "request body must be valid JSON", "code": "bad_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object", "code": "bad_request"}, status_code=400)
        protocol_name = body.get("protocol")
        if not protocol_name or not isinstance(protocol_name, str):
            return JSONResponse({"error": "body must include 'protocol' (a string)", "code": "bad_request"}, status_code=400)
        from pathlib import Path as _Path
        from ..protocol_driver import ProtocolDriver

        root_q = body.get("root") or request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        if root is None:
            return JSONResponse({"error": "no project root resolved", "code": "no_root"}, status_code=400)
        driver = ProtocolDriver(root)
        try:
            plan_id = driver.start(protocol_name)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            is_not_found = "not found" in msg.lower() or "unknown" in msg.lower()
            return JSONResponse({"error": msg, "code": "not_found" if is_not_found else "bad_request"}, status_code=404 if is_not_found else 400)
        return JSONResponse({"plan_id": plan_id}, status_code=201)

    async def post_plan_step(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        driver, err = _protocol_driver_for(request)
        if err is not None:
            return err
        plan_id = request.path_params["plan_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = (body or {}).get("result")
        try:
            summary = driver.complete_step(plan_id, result)
        except KeyError as exc:
            return JSONResponse({"error": str(exc), "code": "not_found"}, status_code=404)
        return JSONResponse(summary)

    app.routes.extend([Route("/v1/plans", get_plans, methods=["GET"]), Route("/v1/plans", post_plans, methods=["POST"]), Route("/v1/plans/{plan_id}", get_plan, methods=["GET"]), Route("/v1/plans/{plan_id}/step", post_plan_step, methods=["POST"])])
