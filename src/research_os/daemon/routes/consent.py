from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .shared import mutating_auth_error


def register_consent(app, daemon) -> None:
    def _consent_store(request):
        from pathlib import Path as _Path

        from ..consent import ConsentStore

        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        return ConsentStore(root)

    async def get_consent_pending(request):
        store = _consent_store(request)
        return JSONResponse({"pending": store.list_pending()})

    async def get_consent_grants(request):
        store = _consent_store(request)
        include = request.query_params.get("include_spent") == "true"
        return JSONResponse({"grants": store.list_grants(include_spent=include)})

    async def post_consent_request(request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "body must be valid JSON", "code": "bad_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object", "code": "bad_request"}, status_code=400)
        gate_key = body.get("gate_key")
        fingerprint = body.get("arg_fingerprint")
        if not gate_key or not fingerprint:
            return JSONResponse({"error": "gate_key and arg_fingerprint are required", "code": "bad_request"}, status_code=400)
        store = _consent_store(request)
        req = store.request(gate_key=str(gate_key), tool=str(body.get("tool", "")), arg_fingerprint=str(fingerprint), reason=str(body.get("reason", "")))
        return JSONResponse({"request": req}, status_code=201)

    async def post_consent_approve(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "body must be valid JSON", "code": "bad_request"}, status_code=400)
        request_id = (body or {}).get("request_id")
        if not request_id:
            return JSONResponse({"error": "request_id is required", "code": "bad_request"}, status_code=400)
        store = _consent_store(request)
        ttl = (body or {}).get("ttl_seconds")
        kwargs = {}
        if isinstance(ttl, int) and ttl > 0:
            kwargs["ttl_seconds"] = ttl
        grant = store.approve(str(request_id), **kwargs)
        if grant is None:
            return JSONResponse({"error": "unknown or already-resolved request_id", "code": "not_found"}, status_code=404)
        return JSONResponse({"grant": grant}, status_code=201)

    async def post_consent_deny(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        request_id = (body or {}).get("request_id")
        if not request_id:
            return JSONResponse({"error": "request_id is required", "code": "bad_request"}, status_code=400)
        store = _consent_store(request)
        ok = store.deny(str(request_id))
        return JSONResponse({"denied": ok})

    async def post_consent_consume(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = (body or {}).get("token")
        if not token:
            return JSONResponse({"error": "token is required", "code": "bad_request"}, status_code=400)
        store = _consent_store(request)
        ok = store.consume(str(token))
        return JSONResponse({"consumed": ok})

    app.routes.extend(
        [
            Route("/v1/consent/pending", get_consent_pending, methods=["GET"]),
            Route("/v1/consent/grants", get_consent_grants, methods=["GET"]),
            Route("/v1/consent/request", post_consent_request, methods=["POST"]),
            Route("/v1/consent/approve", post_consent_approve, methods=["POST"]),
            Route("/v1/consent/deny", post_consent_deny, methods=["POST"]),
            Route("/v1/consent/consume", post_consent_consume, methods=["POST"]),
        ]
    )
