from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..dag_executor import DAGExecutor
from ..protocol_driver import ProtocolDriver


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

    async def post_execute(request: Request):
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)

        if not isinstance(payload, dict):
            return JSONResponse({"error": "request body must be a JSON object"}, status_code=400)

        protocol_id = payload.get("protocol_id")
        if not isinstance(protocol_id, str) or not protocol_id.strip():
            return JSONResponse({"error": "protocol_id is required and must be a non-empty string"}, status_code=400)

        inputs = payload.get("inputs", {})
        if inputs is None:
            inputs = {}
        if not isinstance(inputs, dict):
            return JSONResponse({"error": "inputs must be a JSON object"}, status_code=400)

        try:
            driver = ProtocolDriver(getattr(daemon, "root", None))
            protocol = driver.load_protocol(protocol_id)
            executor = DAGExecutor()
            dag = executor.compile(protocol)
            result = await executor.execute(dag, root=getattr(daemon, "root", None))
        except (ValueError, TypeError, KeyError) as exc:
            return JSONResponse({"error": str(exc), "protocol_id": protocol_id}, status_code=422)
        except Exception as exc:  # pragma: no cover - standard daemon 500 path
            return JSONResponse({"error": str(exc), "protocol_id": protocol_id}, status_code=500)

        return JSONResponse({"service": "research-os", "protocol_id": protocol_id, "inputs": inputs, "status": "completed", "result": result})

    app.routes.append(Route("/v1/workflows", get_workflows, methods=["GET", "HEAD"]))
    app.routes.append(Route("/v1/workflows/execute", post_execute, methods=["POST"]))
