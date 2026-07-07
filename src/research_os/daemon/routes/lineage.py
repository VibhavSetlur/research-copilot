from __future__ import annotations

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route


def register_lineage(app, daemon) -> None:
    def _runstore_or_none(request):
        root_q = request.query_params.get("root")
        if root_q:
            from ..runstore import RunStore

            try:
                store = RunStore(root_q)
            except Exception:
                store = None
        else:
            store = daemon.runstore
        return store

    def _limit_param(request, default=200):
        raw = request.query_params.get("limit")
        if raw is None:
            return default, None
        try:
            return max(0, int(raw)), None
        except ValueError:
            return None, JSONResponse({"error": "limit must be an integer"}, status_code=400)

    async def get_lineage(request):
        from ..lineage import ancestors, build_lineage, descendants

        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"available": False, "error": "no run journal for this root"})
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        graph = build_lineage(manifests)
        rid = request.query_params.get("run_id")
        if rid:
            graph = dict(graph)
            graph["focus"] = {"run_id": rid, "ancestors": sorted(ancestors(graph, rid)), "descendants": sorted(descendants(graph, rid))}
        graph["available"] = True
        return JSONResponse(graph)

    async def get_lineage_mermaid(request):
        from ..lineage import build_lineage, lineage_to_mermaid

        store = _runstore_or_none(request)
        if store is None:
            return PlainTextResponse("flowchart LR\n  empty[\"(no run journal)\"]")
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        return PlainTextResponse(lineage_to_mermaid(build_lineage(manifests)))

    app.routes.extend([Route("/v1/lineage", get_lineage, methods=["GET"]), Route("/v1/lineage.mermaid", get_lineage_mermaid, methods=["GET"])])
