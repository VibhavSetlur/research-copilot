from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .shared import mutating_auth_error


def register_continuation(app, daemon) -> None:
    async def get_continuation(request):
        from pathlib import Path as _Path

        from .. import continuation as _cont

        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        if root is None:
            return JSONResponse({"available": True, "goal": None, "hops": 0, "active": False})
        state = _cont._read_loop_state(root)
        state["available"] = True
        return JSONResponse(state)

    async def post_continuation_start(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "body must be valid JSON", "code": "bad_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object", "code": "bad_request"}, status_code=400)
        goal = (body.get("goal") or "").strip()
        if not goal:
            return JSONResponse({"error": "goal is required", "code": "no_goal"}, status_code=400)
        from .. import continuation as _cont

        from pathlib import Path as _Path

        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        if root is None:
            return JSONResponse({"error": "no project root resolved", "code": "no_root"}, status_code=400)
        state = _cont.start_goal_loop(root, goal)
        return JSONResponse({"status": "started", "opted_in": bool(getattr(daemon.config, "continue_command", "") or ""), **state}, status_code=201)

    async def post_continuation_stop(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        from pathlib import Path as _Path

        from .. import continuation as _cont

        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        if root is None:
            return JSONResponse({"error": "no project root resolved", "code": "no_root"}, status_code=400)
        state = _cont.stop_goal_loop(root)
        return JSONResponse({"status": "stopped", **state})

    app.routes.extend(
        [
            Route("/v1/continuation", get_continuation, methods=["GET"]),
            Route("/v1/continuation/start", post_continuation_start, methods=["POST"]),
            Route("/v1/continuation/stop", post_continuation_stop, methods=["POST"]),
        ]
    )
