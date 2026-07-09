from __future__ import annotations

import os

from starlette.responses import JSONResponse


def bearer_token(authorization: str) -> str:
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def mutating_auth_error(request, daemon):
    cfg = daemon.config
    expected = os.environ.get(getattr(cfg, "auth_token_env", ""), "")
    if not expected:
        return None
    presented = bearer_token(request.headers.get("authorization", ""))
    if presented != expected:
        return JSONResponse({"error": "invalid or missing bearer token", "code": "unauthorized"}, status_code=401)
    return None
