from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .shared import mutating_auth_error


def register_staleness(app, daemon) -> None:
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

    async def get_staleness(request):
        from .. import provenance as _prov
        from .. import staleness as _stale

        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"available": False, "error": "no run journal for this root"})
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        hash_file = _prov.hash_fn_for_root(root)
        report = _stale.assess(manifests, hash_file)
        report["available"] = True
        return JSONResponse(report)

    async def get_rebuild_plan(request):
        if daemon.runstore is None and not request.query_params.get("root"):
            return JSONResponse({"available": False, "error": "no run journal resolved"})
        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"available": False, "error": "no run journal for this root"})
        limit, err = _limit_param(request)
        if err is not None:
            return err
        from .. import provenance as _prov
        from .. import staleness as _stale
        from ..lineage import build_lineage, topo_order

        manifests = store.recent_manifests(limit=limit or 200)
        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        hash_file = _prov.hash_fn_for_root(root)
        report = _stale.assess(manifests, hash_file)
        stale_ids = set(report["stale"])
        if stale_ids:
            graph = build_lineage(manifests)
            plan = topo_order(graph, stale_ids)
        else:
            plan = []
        return JSONResponse({"available": True, "plan": plan, "counts": {"stale": len(stale_ids), "planned": len(plan)}, "note": "dry-run only; POST rebuild requires auth (not yet enabled)"})

    async def post_staleness_verdict(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        from .. import provenance as _prov
        from .. import staleness as _stale

        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"error": "no run journal for this root", "code": "not_found"}, status_code=404)
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        if not root:
            return JSONResponse({"error": "no project root resolved", "code": "bad_request"}, status_code=400)
        hash_file = _prov.hash_fn_for_root(root)
        report = _stale.assess(manifests, hash_file)
        path = _stale.write_verdict(root, report)
        verdict = _stale.verdict_from_report(report)
        return JSONResponse({"verdict": verdict, "path": str(path)}, status_code=201)

    app.routes.extend([Route("/v1/staleness", get_staleness, methods=["GET"]), Route("/v1/rebuild/plan", get_rebuild_plan, methods=["GET"]), Route("/v1/staleness/verdict", post_staleness_verdict, methods=["POST"])])
