from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .shared import mutating_auth_error


def register_memory(app, daemon) -> None:
    async def get_memory_search(request):
        from pathlib import Path as _Path

        q = request.query_params.get("q", "").strip()
        if not q:
            return JSONResponse({"error": "query parameter 'q' is required", "code": "bad_request"}, status_code=400)
        raw_limit = request.query_params.get("limit")
        try:
            limit = max(1, int(raw_limit)) if raw_limit else 5
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        from research_os.memory import MemoryRetriever

        retriever = MemoryRetriever(root)
        hits_raw = retriever.search(q, k=limit or 5)
        hits = []
        for score, record in hits_raw:
            try:
                d = record.model_dump(mode="json")
            except Exception:
                d = {}
            hits.append({"score": score, **d})
        return JSONResponse({"query": q, "hits": hits})

    async def post_memory_record(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "request body must be valid JSON", "code": "bad_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object", "code": "bad_request"}, status_code=400)
        kind = body.get("kind")
        content = body.get("content")
        if not kind:
            return JSONResponse({"error": "'kind' is required", "code": "bad_request"}, status_code=400)
        if not content:
            return JSONResponse({"error": "'content' is required", "code": "bad_request"}, status_code=400)
        from pathlib import Path as _Path

        root_q = body.get("root") or request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        from research_os.memory import MemoryRecord, MemoryRetriever

        project_slug = _Path(root).name if root is not None else "unknown"
        try:
            record = MemoryRecord(kind=kind, content=str(content), summary=str(body.get("summary", "")), project=project_slug)
        except Exception as exc:
            return JSONResponse({"error": f"invalid record: {exc}", "code": "bad_request"}, status_code=400)
        retriever = MemoryRetriever(root)
        stored = retriever.store(record)
        return JSONResponse({"stored": True, "id": stored.id, "kind": stored.kind}, status_code=201)

    app.routes.extend([Route("/v1/memory/search", get_memory_search, methods=["GET"]), Route("/v1/memory/record", post_memory_record, methods=["POST"])])
