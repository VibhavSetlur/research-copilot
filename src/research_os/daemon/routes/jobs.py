from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_jobs(app, daemon) -> None:
    async def get_jobs(request):
        root = request.query_params.get("root")
        limit_raw = request.query_params.get("limit")
        limit = None
        if limit_raw is not None:
            try:
                limit = max(0, int(limit_raw))
            except ValueError:
                return JSONResponse({"error": "limit must be an integer"}, status_code=400)
        return JSONResponse(daemon.tasks.snapshot(root=root, limit=limit))

    async def get_job(request):
        job = daemon.tasks.get(request.path_params["job_id"])
        if job is None:
            return JSONResponse({"error": "job not found"}, status_code=404)
        return JSONResponse(job.to_dict())

    async def post_jobs(request):
        from .shared import mutating_auth_error

        denied = mutating_auth_error(request, daemon)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "request body must be valid JSON", "code": "bad_request"},
                status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "body must be a JSON object", "code": "bad_request"},
                status_code=400,
            )
        cmd = body.get("cmd")
        if not cmd or not isinstance(cmd, (str, list)):
            return JSONResponse(
                {"error": "body must include 'cmd' (a string or argv list)", "code": "bad_request"},
                status_code=400,
            )
        env = body.get("env")
        if env is not None and not isinstance(env, dict):
            return JSONResponse(
                {"error": "'env' must be an object of string overrides", "code": "bad_request"},
                status_code=400,
            )
        inputs = body.get("inputs")
        if inputs is not None and not (isinstance(inputs, list) and all(isinstance(x, str) for x in inputs)):
            return JSONResponse(
                {"error": "'inputs' must be a list of path strings", "code": "bad_request"},
                status_code=400,
            )
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
        return JSONResponse({"job_id": job_id, "status": "submitted"}, status_code=201)

    app.routes.extend(
        [
            Route("/v1/jobs", get_jobs, methods=["GET"]),
            Route("/v1/jobs", post_jobs, methods=["POST"]),
            Route("/v1/jobs/{job_id}", get_job, methods=["GET"]),
        ]
    )
