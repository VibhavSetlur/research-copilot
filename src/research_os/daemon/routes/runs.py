from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route

from .shared import mutating_auth_error


def register_runs(app, daemon) -> None:
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

    async def get_runs(request):
        if daemon.runstore is None:
            return JSONResponse({"runs": [], "available": False})
        limit_raw = request.query_params.get("limit", "50")
        try:
            limit = max(0, int(limit_raw))
        except ValueError:
            return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        return JSONResponse({"runs": daemon.runstore.list_runs(limit=limit), "available": True})

    async def get_run(request):
        if daemon.runstore is None:
            return JSONResponse({"error": "run journal unavailable"}, status_code=404)
        run_id = request.path_params["run_id"]
        manifest = daemon.runstore.read_manifest(run_id)
        if manifest is None:
            return JSONResponse({"error": "run not found"}, status_code=404)
        if request.query_params.get("log"):
            tail_raw = request.query_params.get("tail")
            tail = None
            if tail_raw is not None:
                try:
                    tail = max(0, int(tail_raw))
                except ValueError:
                    return JSONResponse({"error": "tail must be an integer"}, status_code=400)
            manifest = dict(manifest)
            manifest["log"] = daemon.runstore.read_log(run_id, tail=tail)
        return JSONResponse(manifest)

    async def post_runs(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "request body must be valid JSON", "code": "bad_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object", "code": "bad_request"}, status_code=400)
        cmd = body.get("cmd")
        if not cmd or not isinstance(cmd, (str, list)):
            return JSONResponse({"error": "body must include 'cmd' (a string or argv list)", "code": "bad_request"}, status_code=400)
        env = body.get("env")
        if env is not None and not isinstance(env, dict):
            return JSONResponse({"error": "'env' must be an object of string overrides", "code": "bad_request"}, status_code=400)
        inputs = body.get("inputs")
        if inputs is not None and not (isinstance(inputs, list) and all(isinstance(x, str) for x in inputs)):
            return JSONResponse({"error": "'inputs' must be a list of path strings", "code": "bad_request"}, status_code=400)
        try:
            job_id = daemon.run_command(
                cmd,
                name=body.get("name"),
                cwd=body.get("cwd"),
                env={str(k): str(v) for k, v in env.items()} if env else None,
                root=body.get("root"),
                shell=bool(body.get("shell", False)),
                inputs=inputs,
                track_packages=body.get("track_packages"),
                track_artifacts=bool(body.get("track_artifacts", True)),
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"failed to submit run: {exc}", "code": "submit_failed"}, status_code=500)
        return JSONResponse({"run_id": job_id, "status": "submitted"}, status_code=201)

    async def post_run_resume(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        run_id = request.path_params["run_id"]
        try:
            result = daemon.resume_run(run_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc), "code": "not_resumable"}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": f"failed to resume run: {exc}", "code": "resume_failed"}, status_code=500)
        return JSONResponse(result, status_code=201)

    async def post_run_rerun(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        run_id = request.path_params["run_id"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "request body must be valid JSON", "code": "bad_request"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "body must be a JSON object", "code": "bad_request"}, status_code=400)
        overrides = body.get("overrides") or {}
        cwd = body.get("cwd") or None
        try:
            result = daemon.rerun_run(run_id, overrides, cwd=cwd)
        except ValueError as exc:
            msg = str(exc)
            if "no recorded run" in msg or "no workspace" in msg:
                return JSONResponse({"error": msg, "code": "not_found"}, status_code=404)
            return JSONResponse({"error": msg, "code": "bad_request"}, status_code=400)
        return JSONResponse(result)

    async def post_run_reproduce(request):
        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        run_id = request.path_params["run_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        cwd = (body or {}).get("cwd") or None
        timeout_raw = (body or {}).get("timeout")
        timeout = float(timeout_raw) if timeout_raw is not None else None
        try:
            result = daemon.reproduce_run(run_id, cwd=cwd, timeout=timeout)
        except ValueError as exc:
            msg = str(exc)
            if "no recorded run" in msg or "no workspace" in msg:
                return JSONResponse({"error": msg, "code": "not_found"}, status_code=404)
            return JSONResponse({"error": msg, "code": "bad_request"}, status_code=400)
        return JSONResponse(result)

    async def get_run_artifacts(request):
        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"error": "run journal unavailable"}, status_code=404)
        run_id = request.path_params["run_id"]
        manifest = store.read_manifest(run_id)
        if manifest is None:
            return JSONResponse({"error": "run not found"}, status_code=404)
        return JSONResponse({"run_id": run_id, "artifacts": manifest.get("artifacts") or []})

    async def get_run_lineage(request):
        from ..lineage import ancestors, build_lineage, descendants

        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"available": False, "error": "no run journal for this root"})
        run_id = request.path_params["run_id"]
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        graph = build_lineage(manifests)
        graph = dict(graph)
        graph["focus"] = {"run_id": run_id, "ancestors": sorted(ancestors(graph, run_id)), "descendants": sorted(descendants(graph, run_id))}
        graph["available"] = True
        return JSONResponse(graph)

    app.routes.extend(
        [
            Route("/v1/runs", get_runs, methods=["GET"]),
            Route("/v1/runs", post_runs, methods=["POST"]),
            Route("/v1/runs/{run_id}", get_run, methods=["GET"]),
            Route("/v1/runs/{run_id}/resume", post_run_resume, methods=["POST"]),
            Route("/v1/runs/{run_id}/rerun", post_run_rerun, methods=["POST"]),
            Route("/v1/runs/{run_id}/reproduce", post_run_reproduce, methods=["POST"]),
            Route("/v1/runs/{run_id}/artifacts", get_run_artifacts, methods=["GET"]),
            Route("/v1/runs/{run_id}/lineage", get_run_lineage, methods=["GET"]),
        ]
    )
