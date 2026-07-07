from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .shared import mutating_auth_error


def register_gates(app, daemon) -> None:
    async def get_gates_pending(request):
        if daemon.gates is None:
            return JSONResponse({"gates": [], "available": False})
        return JSONResponse({"gates": [g.to_dict() for g in daemon.gates.pending()], "available": True})

    async def post_gates_respond(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "request body must be valid JSON", "code": "bad_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object", "code": "bad_request"}, status_code=400)
        gate_id = body.get("gate_id")
        decision = body.get("decision")
        if not gate_id or not isinstance(gate_id, str):
            return JSONResponse({"error": "body must include 'gate_id' (a string)", "code": "bad_request"}, status_code=400)
        if not decision or not isinstance(decision, str):
            return JSONResponse({"error": "body must include 'decision' (a string)", "code": "bad_request"}, status_code=400)
        decision_normalized = decision.strip().lower()
        if decision_normalized not in {"approve", "reject"}:
            return JSONResponse({"error": "decision must be 'approve' or 'reject'", "code": "bad_request"}, status_code=400)
        if daemon.gates is None:
            return JSONResponse({"error": "gate queue unavailable", "code": "unavailable"}, status_code=503)
        if daemon.gates.get(gate_id) is None:
            return JSONResponse({"error": "gate not found", "code": "not_found"}, status_code=404)
        approved = daemon.gates.resolve(gate_id, decision_normalized)
        return JSONResponse({"gate_id": gate_id, "decision": decision_normalized, "approved": approved, "status": "resolved"})

    app.routes.extend(
        [
            Route("/v1/gates/pending", get_gates_pending, methods=["GET"]),
            Route("/v1/gates/respond", post_gates_respond, methods=["POST"]),
        ]
    )
