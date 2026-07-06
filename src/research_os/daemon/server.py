"""Daemon HTTP server — the lazy ASGI layer (read-only + gateway).

This module is the ONLY place that touches starlette/uvicorn, and it does
so lazily: importing `research_os.daemon.server` must not import the web
stack. The deps live in the optional `[daemon]` extra; if they're missing
we raise a clear, actionable error telling the user to install it.

Read-only endpoints (no auth beyond the 127.0.0.1 bind):
  GET  /healthz            liveness + version
  GET  /v1/state           multi-root state snapshot (all registered roots)
  GET  /v1/supervision     PI roll-up: health across ALL registered projects
                           (counts + worst findings + needs_attention list)
  GET  /v1/domain          detected research field + field-aware defaults
  GET  /v1/capabilities    agent front door: identity + field + tool/protocol
                           inventory + work-state freshness + gateway readiness
                           (?tools=full embeds OpenAI tool schemas)
  GET  /v1/orient          "standup": narrative of where the project is +
                           ONE recommended next action (field + run journal
                           + staleness synthesis; ?root=, ?limit=)
  GET  /v1/workflows       detect Snakemake/Nextflow pipelines + preview
                           the planned DAG via a read-only dry-run when the
                           engine is installed (?root=, ?introspect=false)
  GET  /v1/sandbox         report the strongest execution-isolation tier
                           this host supports (container/namespace/resource)
                           so a caller knows the bounding before submitting
                           untrusted work (?refresh=true re-probes)
  GET  /v1/lineage         content-addressed run dependency graph (?run_id=)
  GET  /v1/lineage.mermaid  the run-lineage DAG as a mermaid provenance diagram
  GET  /v1/staleness       freshness verdict over the lineage DAG
  GET  /v1/rebuild/plan    what a rebuild WOULD re-run, in order (dry-run)
  GET  /v1/jobs            background task queue snapshot
  GET  /v1/jobs/{job_id}   one job
  GET  /v1/runs            durable run journal (the permanent archive)
  GET  /v1/runs/{run_id}   one run manifest (?log=1&tail=N for output)
  GET  /v1/stream          SSE stream of the 7 core event kinds (run.started/
                           completed/failed, protocol.step_started, gate.pending/
                           resolved, memory.stored); ?since=<iso> resumes by time
  GET  /v1/events          SSE stream of daemon events
  GET  /v1/events/recent   poll-friendly recent-events snapshot
  GET  /v1/consent/pending pending consent requests awaiting a human verdict
  GET  /v1/consent/grants  minted consent grants (?include_spent=true)
  GET  /v1/gates/pending   pending HITL gates awaiting a human decision
  GET  /v1/notifications   the notification outbox — what the daemon told the
                           researcher + delivery outcome (?undelivered=true)

Mutating endpoints (require enable_gateway + a per-session bearer token,
the consent/staleness authority surface; off by default):
  POST /v1/jobs            submit a journaled background run (agent-initiated
                           execution → one journal/provenance/lineage path) (auth)
  POST /v1/runs            submit a journaled run (canonical exec-tool path) (auth)
  POST /v1/runs/{run_id}/resume  resume an interrupted/paused run from its
                           recorded spec (checkpoint-aware) (auth)
  GET  /v1/continuation     current autonomous goal-loop state (goal/hops/active)
  POST /v1/continuation/start  begin an autonomous goal loop toward a goal (auth)
  POST /v1/continuation/stop   end the active autonomous goal loop (auth)
  POST /v1/consent/request the agent asks for consent (open; cannot grant)
  POST /v1/consent/approve mints a one-shot, TTL'd, arg-bound token (auth)
  POST /v1/consent/deny    rejects a pending request (auth)
  POST /v1/consent/consume burns a token (auth)
  POST /v1/gates/respond   resolve a pending HITL gate {gate_id, decision} (auth)
  POST /v1/staleness/verdict  assess freshness + persist the verdict sidecar
                              the floor gate reads (auth)

NOTE: this list is drift-guarded — scripts/preflight.py (check_daemon_
endpoints_documented) fails the build if a registered Route is missing
from this docstring or vice versa. Keep them in sync.

Gateway endpoint (Phase 2 — MUTATING, requires a per-session bearer token
and an explicit enable_gateway flag; off by default):
  POST /v1/chat/completions  OpenAI-compatible chat completions. Routes the
                             prompt through the protocol router, injects
                             domain + freshness + protocol context, forwards
                             to the configured upstream LLM, and executes
                             any Research-OS tool calls through the dispatch
                             seam, looping until the model answers. Supports
                             stream:true (Server-Sent Events of
                             chat.completion.chunk frames).

The transport sits behind this thin module by design (docs/ROADMAP.md
§6) so a judge phase can swap starlette for something else without
touching the Daemon or the registry/queue.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime web import
    from .core import Daemon

logger = logging.getLogger("research-os.daemon.server")

_INSTALL_HINT = (
    "The Research OS daemon HTTP server needs the optional web stack. "
    "Install it with:  pip install 'research-os[daemon]'"
)


def _require_web_stack():
    """Import starlette/uvicorn lazily; raise a clear error if absent."""
    try:
        import starlette  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised via missing dep
        raise RuntimeError(_INSTALL_HINT) from exc


def _bearer_token(authorization: str) -> str:
    """Extract the token from an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        return ""
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def _make_upstream_forwarder(cfg):
    """Build the network forwarder the gateway calls to reach the LLM.

    Uses stdlib ``urllib`` (no httpx dependency) to POST the OpenAI-shaped
    body to the configured upstream. Returns a ``forward_fn(body, headers)``
    closure so the gateway core stays network-agnostic and testable.
    """
    import urllib.error
    import urllib.request

    base = (getattr(cfg, "gateway_upstream_base_url", "") or "").rstrip("/")
    url = f"{base}/chat/completions"
    api_key = os.environ.get(getattr(cfg, "gateway_api_key_env", ""), "")
    upstream_model = getattr(cfg, "gateway_upstream_model", "") or ""
    timeout = float(getattr(cfg, "gateway_timeout", 120) or 120)

    def forward(body: dict, headers: dict) -> dict:
        payload = dict(body)
        # Force the configured upstream model (the client's model name is a
        # routing hint to us, not necessarily a valid upstream model id).
        if upstream_model:
            payload["model"] = upstream_model
        data = json.dumps(payload).encode("utf-8")
        req_headers = {"Content-Type": "application/json", **(headers or {})}
        if api_key:
            req_headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"upstream {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"cannot reach upstream {url}: {exc.reason}") from exc

    return forward


def build_app(daemon: "Daemon"):
    """Build the Starlette ASGI app bound to a running ``daemon``.

    Imported lazily inside the function so module import stays web-free.
    """
    _require_web_stack()
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
    from starlette.routing import Route

    from research_os import __version__

    async def healthz(request):
        return JSONResponse(
            {
                "status": "ok",
                "service": "research-os-daemon",
                "version": __version__,
                "serving": daemon.serving,
                "roots": daemon.registry.roots(),
            }
        )

    async def get_state(request):
        # Multi-root snapshot. A ?root= filter returns just that workspace.
        root = request.query_params.get("root")
        if root:
            ws = daemon.registry.get(root) or daemon.registry.register(root)
            return JSONResponse({"root": ws.state()})
        return JSONResponse(daemon.registry.snapshot())

    async def get_supervision(request):
        # Supervisor (PI) roll-up: health across ALL registered projects in one
        # call — "are all my students' projects healthy / on-protocol / not
        # stuck?" Read-only.
        from . import health_notes as _h
        roots = list(daemon.registry.roots())
        if daemon.root is not None and str(daemon.root) not in roots:
            roots.append(str(daemon.root))
        return JSONResponse(_h.run_self_check_all(roots))

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
        # MUTATING: submit a command as a journaled background run. This is
        # the agent-initiated execution path — it closes ARCHITECTURE §6.2
        # ("one execution path"): a run submitted here goes through the same
        # core.run_command lifecycle the CLI uses, so it gets the full
        # journal + provenance + lineage + reproduce treatment instead of
        # escaping into an untracked inline subprocess. Auth-gated like every
        # mutating endpoint (executes code on the host).
        denied = _consent_auth_error(request)
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
                {"error": "body must include 'cmd' (a string or argv list)",
                 "code": "bad_request"},
                status_code=400,
            )
        env = body.get("env")
        if env is not None and not isinstance(env, dict):
            return JSONResponse(
                {"error": "'env' must be an object of string overrides",
                 "code": "bad_request"},
                status_code=400,
            )
        inputs = body.get("inputs")
        if inputs is not None and not (
            isinstance(inputs, list) and all(isinstance(x, str) for x in inputs)
        ):
            return JSONResponse(
                {"error": "'inputs' must be a list of path strings",
                 "code": "bad_request"},
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
        except Exception as exc:  # noqa: BLE001 - surface submit failure as 500
            return JSONResponse(
                {"error": f"failed to submit run: {exc}", "code": "submit_failed"},
                status_code=500,
            )
        return JSONResponse({"job_id": job_id, "status": "submitted"}, status_code=201)

    async def post_run_resume(request):
        # MUTATING: resume an interrupted/paused/failed run by re-launching its
        # recorded spec as a fresh journaled run. The recovery lever orient's
        # resume_interrupted recommendation points at. Auth-gated (executes
        # code on the host).
        denied = _consent_auth_error(request)
        if denied is not None:
            return denied
        run_id = request.path_params["run_id"]
        try:
            result = daemon.resume_run(run_id)
        except ValueError as exc:
            return JSONResponse(
                {"error": str(exc), "code": "not_resumable"}, status_code=400
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": f"failed to resume run: {exc}", "code": "resume_failed"},
                status_code=500,
            )
        return JSONResponse(result, status_code=201)

    async def post_continuation_start(request):
        # MUTATING: begin an autonomous goal loop. After this, when a long run
        # reaches terminal AND daemon.continue_command is set, the daemon
        # re-prompts the researcher's agent toward this goal (hop-limited).
        # Auth-gated. No-op-safe: opt-in still requires continue_command.
        denied = _consent_auth_error(request)
        if denied is not None:
            return denied
        if daemon.root is None:
            return JSONResponse(
                {"error": "no project root", "code": "no_root"}, status_code=400
            )
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        goal = str((body or {}).get("goal", "")).strip()
        if not goal:
            return JSONResponse(
                {"error": "goal is required", "code": "no_goal"}, status_code=400
            )
        try:
            from . import continuation as _cont

            state = _cont.start_goal_loop(daemon.root, goal)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": f"failed to start loop: {exc}", "code": "start_failed"},
                status_code=500,
            )
        opted_in = bool((getattr(daemon.config, "continue_command", "") or "").strip())
        return JSONResponse(
            {"status": "started", "goal": goal, "opted_in": opted_in, "state": state},
            status_code=201,
        )

    async def post_continuation_stop(request):
        # MUTATING: end the active autonomous goal loop (goal met / researcher
        # stopped it). Auth-gated. Idempotent.
        denied = _consent_auth_error(request)
        if denied is not None:
            return denied
        if daemon.root is None:
            return JSONResponse(
                {"error": "no project root", "code": "no_root"}, status_code=400
            )
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        reason = str((body or {}).get("reason", "goal_met")).strip() or "goal_met"
        try:
            from . import continuation as _cont

            state = _cont.stop_goal_loop(daemon.root, reason=reason)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {"error": f"failed to stop loop: {exc}", "code": "stop_failed"},
                status_code=500,
            )
        return JSONResponse({"status": "stopped", "reason": reason, "state": state})

    async def get_continuation(request):
        # READ-ONLY: the current goal-loop state (goal, hops, active).
        if daemon.root is None:
            return JSONResponse({"active": False, "available": False})
        try:
            from . import continuation as _cont

            state = _cont._read_loop_state(daemon.root)
            opted_in = bool((getattr(daemon.config, "continue_command", "") or "").strip())
            return JSONResponse({"available": True, "opted_in": opted_in, **state})
        except Exception:  # noqa: BLE001
            return JSONResponse({"active": False, "available": False})

    async def get_runs(request):
        # Durable run journal — the permanent record (survives restarts).
        # /v1/jobs is the live in-memory view; /v1/runs is the archive.
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
        # Optional full log via ?log=1 (&tail=N for the last N lines).
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

    async def get_events_recent(request):
        # JSON snapshot of recent events (poll-friendly fallback for clients
        # that can't hold an SSE stream open).
        kinds = _parse_kinds(request.query_params.get("kinds"))
        root = request.query_params.get("root")
        after_raw = request.query_params.get("after")
        limit_raw = request.query_params.get("limit")
        try:
            after = int(after_raw) if after_raw else 0
            limit = max(1, int(limit_raw)) if limit_raw else 100
        except ValueError:
            return JSONResponse({"error": "after/limit must be integers"}, status_code=400)
        events = daemon.events.recent(limit=limit, kinds=kinds, root=root, after_seq=after)
        return JSONResponse(
            {
                "events": [e.to_dict() for e in events],
                "last_seq": daemon.events.last_seq,
                "stats": daemon.events.stats(),
            }
        )

    async def stream_events(request):
        # Server-Sent Events stream. Reconnecting clients pass Last-Event-ID
        # (or ?after=N) to resume without gaps. The bus generator blocks, so
        # we pump it from a worker thread via anyio and yield into the ASGI
        # event loop.
        import anyio
        from starlette.responses import StreamingResponse

        kinds = _parse_kinds(request.query_params.get("kinds"))
        root = request.query_params.get("root")
        last_event_id = request.headers.get("last-event-id")
        after_q = request.query_params.get("after")
        after_seq = 0
        for candidate in (last_event_id, after_q):
            if candidate:
                try:
                    after_seq = int(candidate)
                    break
                except ValueError:
                    pass
        backfill = 0 if after_seq else 20

        send_stream, receive_stream = anyio.create_memory_object_stream(64)

        def _pump():
            gen = daemon.events.subscribe(
                kinds=kinds, root=root, backfill=backfill, after_seq=after_seq
            )
            try:
                for event in gen:
                    anyio.from_thread.run(send_stream.send, event)
            except anyio.BrokenResourceError:
                pass  # client disconnected
            finally:
                gen.close()
                anyio.from_thread.run_sync(send_stream.close)

        async def event_publisher():
            async with anyio.create_task_group() as tg:
                tg.start_soon(anyio.to_thread.run_sync, _pump)
                async with receive_stream:
                    async for event in receive_stream:
                        if event.kind == "heartbeat":
                            yield ": keepalive\n\n"
                            continue
                        payload = json.dumps(event.to_dict())
                        yield f"id: {event.seq}\nevent: {event.kind}\ndata: {payload}\n\n"

        return StreamingResponse(
            event_publisher(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def get_domain(request):
        # Field-awareness: detect (or read) the project's research domain
        # and return its profile + sensible defaults. Read-only; safe to
        # poll. ?root= overrides the daemon's resolved root.
        from pathlib import Path as _Path

        from .domains import detect

        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        if root is None:
            return JSONResponse({"available": False,
                                 "error": "no project root resolved"})
        result = detect(root)
        out = result.as_dict()
        out["root"] = str(root)
        out["available"] = True
        return JSONResponse(out)

    async def get_capabilities(request):
        # The agent front door: one read-only call that fully describes
        # Research-OS to any AI agent — identity, detected field, tool +
        # protocol inventory, work-state freshness, gateway readiness.
        # ?root= overrides; ?tools=full embeds the OpenAI tool schemas.
        from . import gateway as _gw

        want_schemas = request.query_params.get("tools") == "full"
        root_q = request.query_params.get("root")
        target = daemon
        if root_q:
            target = daemon.registry.get(root_q) or daemon.registry.register(root_q)
        try:
            payload = _gw.build_capabilities(target, include_tool_schemas=want_schemas)
        except Exception as exc:  # noqa: BLE001 - orientation must never 500
            return JSONResponse(
                {"service": "research-os", "available": False, "error": str(exc)}
            )
        return JSONResponse(payload)

    async def get_orient(request):
        # The "standup" endpoint: where are we + what should I do next.
        # A read-only synthesis over field + run journal + staleness, with
        # ONE recommended next action. ?root= overrides; ?limit= caps the
        # run scan. Best-effort: never 500.
        from . import orient as _orient

        root_q = request.query_params.get("root")
        limit, err = _limit_param(request, default=50)
        if err is not None:
            return err
        try:
            payload = _orient.build_orientation(daemon, root=root_q, limit=limit or 50)
        except Exception as exc:  # noqa: BLE001 - orientation must never 500
            return JSONResponse(
                {"service": "research-os", "available": False, "error": str(exc)}
            )
        return JSONResponse(payload)

    async def get_workflows(request):
        # Pipeline DAG awareness (JUDGE-7): detect Snakemake/Nextflow
        # definitions under the root and, when the engine is installed,
        # preview the planned steps via a read-only dry-run. ?root=
        # overrides; ?introspect=false skips the dry-run (detection only).
        from . import workflows as _wf

        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        introspect = request.query_params.get("introspect", "true") != "false"
        try:
            payload = _wf.survey_workflows(root, introspect=introspect)
        except Exception as exc:  # noqa: BLE001 - introspection must never 500
            return JSONResponse(
                {"service": "research-os", "available": False, "error": str(exc)}
            )
        return JSONResponse(payload)

    async def get_sandbox(request):
        # Execution sandbox capabilities (Phase 4): report the strongest
        # isolation tier this host can provide (container → namespace →
        # resource) so an agent knows what bounding it gets BEFORE submitting
        # untrusted work. Read-only; never 500s. ?refresh=true re-probes.
        from . import sandbox as _sb

        refresh = request.query_params.get("refresh", "false") == "true"
        try:
            caps = _sb.detect_sandbox(refresh=refresh)
            payload = caps.to_dict()
            payload["service"] = "research-os"
            payload["default_limits"] = _sb.ResourceLimits().to_dict()
            # Surface the project's declared resource budget (if any) + the
            # effective limits a run would actually get, so an agent can see
            # the bound BEFORE submitting and cite it when paging.
            from . import resource_budget as _budget

            root_q = request.query_params.get("root")
            root = root_q or getattr(daemon, "root", None)
            if root:
                payload["resource_budget"] = _budget.budget_summary(root)
                payload["effective_limits"] = _budget.resolve_run_limits(
                    root, base=_sb.ResourceLimits()
                ).to_dict()
        except Exception as exc:  # noqa: BLE001 - detection must never 500
            return JSONResponse(
                {"service": "research-os", "available": False, "error": str(exc)}
            )
        return JSONResponse(payload)

    def _runstore_or_none(request):
        # Resolve the runstore for an optional ?root= override, else the
        # daemon's own runstore. Returns (runstore, error_response|None).
        root_q = request.query_params.get("root")
        if root_q:
            # A registry workspace carries no runstore — construct one directly
            # for the override root so ?root= lineage/staleness/rebuild actually
            # read that project's journal (F-7) instead of always degrading to
            # available:false.
            from .runstore import RunStore
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
            return None, JSONResponse(
                {"error": "limit must be an integer"}, status_code=400
            )

    async def get_lineage(request):
        # The content-addressed run dependency graph (who fed whom).
        from .lineage import ancestors, build_lineage, descendants

        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"available": False,
                                 "error": "no run journal for this root"})
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        graph = build_lineage(manifests)
        # Optional focus on one run's up/downstream cone.
        rid = request.query_params.get("run_id")
        if rid:
            graph = dict(graph)
            graph["focus"] = {
                "run_id": rid,
                "ancestors": sorted(ancestors(graph, rid)),
                "descendants": sorted(descendants(graph, rid)),
            }
        graph["available"] = True
        return JSONResponse(graph)

    async def get_lineage_mermaid(request):
        # The run-lineage DAG rendered as a mermaid flowchart string — a
        # provenance diagram a README/conclusions/audit can embed.
        from .lineage import build_lineage, lineage_to_mermaid

        store = _runstore_or_none(request)
        if store is None:
            return PlainTextResponse("flowchart LR\n  empty[\"(no run journal)\"]")
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        return PlainTextResponse(lineage_to_mermaid(build_lineage(manifests)))

    async def get_staleness(request):
        # Freshness verdict over the lineage DAG — which results were built
        # from inputs that have since changed on disk.
        from . import provenance as _prov
        from . import staleness as _stale

        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"available": False,
                                 "error": "no run journal for this root"})
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        # Resolve hashes against the right root (override or daemon root).
        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        hash_file = _prov.hash_fn_for_root(root)
        report = _stale.assess(manifests, hash_file)
        report["available"] = True
        return JSONResponse(report)

    async def get_rebuild_plan(request):
        # The plan only — what WOULD be rebuilt, in dependency order.
        # Read-only by design: actual rebuild is a mutation and stays on
        # the CLI / a future authenticated POST.
        if daemon.runstore is None and not request.query_params.get("root"):
            return JSONResponse({"available": False,
                                 "error": "no run journal resolved"})
        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse({"available": False,
                                 "error": "no run journal for this root"})
        limit, err = _limit_param(request)
        if err is not None:
            return err
        from . import provenance as _prov
        from . import staleness as _stale
        from .lineage import build_lineage, topo_order

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
        return JSONResponse({
            "available": True,
            "plan": plan,
            "counts": {"stale": len(stale_ids), "planned": len(plan)},
            "note": "dry-run only; POST rebuild requires auth (not yet enabled)",
        })

    async def post_staleness_verdict(request):
        # MUTATING: assess freshness over the lineage DAG and PERSIST the
        # verdict sidecar (.os_state/staleness/verdict.json) that the
        # reasoning-side staleness gate reads by shape. Gateway-gated like
        # the other mutating endpoints — writing the verdict is an authority
        # action (it can block the final-deliverable compile).
        denied = _consent_auth_error(request)
        if denied is not None:
            return denied
        from . import provenance as _prov
        from . import staleness as _stale

        store = _runstore_or_none(request)
        if store is None:
            return JSONResponse(
                {"error": "no run journal for this root", "code": "not_found"},
                status_code=404,
            )
        limit, err = _limit_param(request)
        if err is not None:
            return err
        manifests = store.recent_manifests(limit=limit or 200)
        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        if not root:
            return JSONResponse(
                {"error": "no project root resolved", "code": "bad_request"},
                status_code=400,
            )
        hash_file = _prov.hash_fn_for_root(root)
        report = _stale.assess(manifests, hash_file)
        path = _stale.write_verdict(root, report)
        verdict = _stale.verdict_from_report(report)
        return JSONResponse(
            {"verdict": verdict, "path": str(path)}, status_code=201
        )

    async def chat_completions(request):
        # OpenAI-compatible gateway (Phase 2). Mutating surface -> requires
        # a per-session bearer token. Off unless config.enable_gateway.
        from . import gateway as _gw

        cfg = daemon.config
        if not getattr(cfg, "enable_gateway", False):
            return JSONResponse(
                _gw.error_response(
                    "gateway disabled; set daemon.enable_gateway=true to use it",
                    code="gateway_disabled",
                ),
                status_code=503,
            )

        # Auth: a token MUST be configured, and the client MUST present it.
        expected = os.environ.get(getattr(cfg, "gateway_token_env", ""), "")
        if not expected:
            return JSONResponse(
                _gw.error_response(
                    "gateway token not configured; set "
                    f"${cfg.gateway_token_env} on the daemon",
                    code="gateway_unconfigured",
                ),
                status_code=503,
            )
        presented = _bearer_token(request.headers.get("authorization", ""))
        if presented != expected:
            return JSONResponse(
                _gw.error_response("invalid or missing bearer token",
                                   code="unauthorized"),
                status_code=401,
            )

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                _gw.error_response("request body must be valid JSON",
                                   code="bad_request"),
                status_code=400,
            )
        if not isinstance(body, dict) or not body.get("messages"):
            return JSONResponse(
                _gw.error_response("body must include a 'messages' array",
                                   code="bad_request"),
                status_code=400,
            )

        forward = _make_upstream_forwarder(cfg)
        try:
            result = _gw.run_completion(
                body, daemon, forward,
                max_tool_rounds=getattr(cfg, "gateway_max_tool_rounds", 6),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("gateway completion failed")
            return JSONResponse(
                _gw.error_response(f"upstream completion failed: {exc}",
                                   code="upstream_error"),
                status_code=502,
            )
        # Streaming: re-emit the resolved completion as OpenAI-compatible
        # SSE chunks. The tool-call loop runs to completion first (we can't
        # honestly stream tokens mid-loop), then the answer streams as
        # chat.completion.chunk frames every streaming client understands.
        if body.get("stream"):
            return StreamingResponse(
                _gw.to_stream_chunks(result),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return JSONResponse(result)

    # ── consent authority (un-skippable gates) ──────────────────────────
    # The daemon is the consent AUTHORITY for floor gates. The reasoning
    # layer reads the granted ledger by shape (server/consent.py) and
    # refuses a gate unless a daemon-minted token is present. Here the
    # daemon mints/approves/denies/consumes those tokens. Read surfaces
    # (pending, grants) are ungated telemetry so a client can show them;
    # mutating surfaces require the same enable_gateway + bearer auth as
    # the chat gateway, because they decide whether dangerous actions may
    # proceed.
    def _consent_store(request):
        from pathlib import Path as _Path

        from .consent import ConsentStore

        root_q = request.query_params.get("root")
        root = _Path(root_q) if root_q else daemon.root
        return ConsentStore(root)

    def _consent_auth_error(request):
        """Return a JSONResponse if the mutating consent surface is blocked.

        Mirrors chat_completions: enable_gateway must be on and a bearer
        token matching $gateway_token_env must be presented. Returns None
        when authorized.
        """
        cfg = daemon.config
        if not getattr(cfg, "enable_gateway", False):
            return JSONResponse(
                {"error": "consent mutation disabled; set "
                          "daemon.enable_gateway=true to use it",
                 "code": "gateway_disabled"},
                status_code=503,
            )
        expected = os.environ.get(getattr(cfg, "gateway_token_env", ""), "")
        if not expected:
            return JSONResponse(
                {"error": "gateway token not configured", "code":
                 "gateway_unconfigured"},
                status_code=503,
            )
        presented = _bearer_token(request.headers.get("authorization", ""))
        if presented != expected:
            return JSONResponse(
                {"error": "invalid or missing bearer token",
                 "code": "unauthorized"},
                status_code=401,
            )
        return None

    async def get_consent_pending(request):
        store = _consent_store(request)
        return JSONResponse({"pending": store.list_pending()})

    async def get_consent_grants(request):
        store = _consent_store(request)
        include = request.query_params.get("include_spent") == "true"
        return JSONResponse(
            {"grants": store.list_grants(include_spent=include)}
        )

    async def get_notifications(request):
        # Read-only view of the notification outbox (the spine, intent #4):
        # what the daemon told the researcher, and whether delivery
        # succeeded. ?undelivered=true filters to records that did not reach
        # the configured channel, so a client/AI can surface what was missed.
        from . import notifications as _ntfy

        root_q = request.query_params.get("root")
        root = root_q or getattr(daemon, "root", None)
        if not root:
            return JSONResponse({"available": False,
                                 "error": "no project root resolved"})
        undelivered = request.query_params.get("undelivered") == "true"
        limit, err = _limit_param(request)
        if err is not None:
            return err
        records = _ntfy.read_outbox(
            root, undelivered_only=undelivered, limit=limit or 100
        )
        return JSONResponse({"available": True, "notifications": records,
                             "count": len(records)})

    async def post_consent_request(request):
        # The agent REQUESTS consent (it cannot self-grant). Open without
        # bearer auth: requesting is harmless (it only queues), and the
        # agent must be able to ask. Approval is what requires authority.
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "body must be valid JSON", "code": "bad_request"},
                status_code=400,
            )
        if not isinstance(body, dict):
            return JSONResponse(
                {"error": "body must be a JSON object", "code": "bad_request"},
                status_code=400,
            )
        gate_key = body.get("gate_key")
        fingerprint = body.get("arg_fingerprint")
        if not gate_key or not fingerprint:
            return JSONResponse(
                {"error": "gate_key and arg_fingerprint are required",
                 "code": "bad_request"},
                status_code=400,
            )
        store = _consent_store(request)
        req = store.request(
            gate_key=str(gate_key),
            tool=str(body.get("tool", "")),
            arg_fingerprint=str(fingerprint),
            reason=str(body.get("reason", "")),
        )
        return JSONResponse({"request": req}, status_code=201)

    async def post_consent_approve(request):
        # MUTATING + authority-bearing: mints a token. Requires auth.
        denied = _consent_auth_error(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "body must be valid JSON", "code": "bad_request"},
                status_code=400,
            )
        request_id = (body or {}).get("request_id")
        if not request_id:
            return JSONResponse(
                {"error": "request_id is required", "code": "bad_request"},
                status_code=400,
            )
        store = _consent_store(request)
        ttl = (body or {}).get("ttl_seconds")
        kwargs = {}
        if isinstance(ttl, int) and ttl > 0:
            kwargs["ttl_seconds"] = ttl
        grant = store.approve(str(request_id), **kwargs)
        if grant is None:
            return JSONResponse(
                {"error": "unknown or already-resolved request_id",
                 "code": "not_found"},
                status_code=404,
            )
        return JSONResponse({"grant": grant}, status_code=201)

    async def post_consent_deny(request):
        denied = _consent_auth_error(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        request_id = (body or {}).get("request_id")
        if not request_id:
            return JSONResponse(
                {"error": "request_id is required", "code": "bad_request"},
                status_code=400,
            )
        store = _consent_store(request)
        ok = store.deny(str(request_id))
        return JSONResponse({"denied": ok})

    async def post_consent_consume(request):
        denied = _consent_auth_error(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = (body or {}).get("token")
        if not token:
            return JSONResponse(
                {"error": "token is required", "code": "bad_request"},
                status_code=400,
            )
        store = _consent_store(request)
        ok = store.consume(str(token))
        return JSONResponse({"consumed": ok})

    async def stream_v1(request):
        # SSE stream with optional ?since=<iso> backfill by wall-clock time.
        # Mirrors stream_events exactly, adding time-based resume on top of the
        # existing sequence-number resume so reconnecting clients can catch up
        # using a stored ISO timestamp instead of an opaque seq number.
        import anyio
        from datetime import datetime, timezone

        kinds = _parse_kinds(request.query_params.get("kinds"))
        root = request.query_params.get("root")

        # Sequence-based resume (parity with stream_events).
        last_event_id = request.headers.get("last-event-id")
        after_q = request.query_params.get("after")
        after_seq = 0
        for candidate in (last_event_id, after_q):
            if candidate:
                try:
                    after_seq = int(candidate)
                    break
                except ValueError:
                    pass

        # Time-based resume via ?since=<iso>.
        since_epoch: float | None = None
        since_raw = request.query_params.get("since")
        if since_raw:
            try:
                dt = datetime.fromisoformat(since_raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                since_epoch = dt.timestamp()
            except (ValueError, TypeError):
                pass

        # When using time-based backfill, pull recent events and drop those
        # at or before the since timestamp, yielding remaining first.
        backfill = 0 if after_seq else 20

        send_stream, receive_stream = anyio.create_memory_object_stream(64)

        def _pump():
            # Time-based backfill: fetch up to 200 recent events, filter by ts.
            backfill_events = []
            if since_epoch is not None:
                try:
                    candidates = daemon.events.recent(limit=200, kinds=kinds, root=root)
                    backfill_events = [e for e in candidates if e.ts > since_epoch]
                except Exception:  # noqa: BLE001
                    pass

            gen = daemon.events.subscribe(
                kinds=kinds, root=root, backfill=backfill, after_seq=after_seq
            )
            try:
                for ev in backfill_events:
                    anyio.from_thread.run(send_stream.send, ev)
                for event in gen:
                    anyio.from_thread.run(send_stream.send, event)
            except anyio.BrokenResourceError:
                pass  # client disconnected
            finally:
                gen.close()
                anyio.from_thread.run_sync(send_stream.close)

        async def event_publisher():
            async with anyio.create_task_group() as tg:
                tg.start_soon(anyio.to_thread.run_sync, _pump)
                async with receive_stream:
                    async for event in receive_stream:
                        if event.kind == "heartbeat":
                            yield ": keepalive\n\n"
                            continue
                        payload = json.dumps(event.to_dict())
                        yield f"event: {event.kind}\ndata: {payload}\n\n"

        return StreamingResponse(
            event_publisher(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def get_gates_pending(request):
        # READ-ONLY: list all gates currently awaiting a human decision.
        if daemon.gates is None:
            return JSONResponse({"gates": [], "available": False})
        return JSONResponse({"gates": [g.to_dict() for g in daemon.gates.pending()], "available": True})

    async def post_gates_respond(request):
        # MUTATING: resolve a pending HITL gate. Auth-gated like post_jobs.
        denied = _consent_auth_error(request)
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
        gate_id = body.get("gate_id")
        decision = body.get("decision")
        if not gate_id or not isinstance(gate_id, str):
            return JSONResponse(
                {"error": "body must include 'gate_id' (a string)", "code": "bad_request"},
                status_code=400,
            )
        if not decision or not isinstance(decision, str):
            return JSONResponse(
                {"error": "body must include 'decision' (a string)", "code": "bad_request"},
                status_code=400,
            )
        # FIX 5: validate the decision value — only "approve" or "reject" are
        # accepted. Anything else would silently map to rejected (resolve()
        # maps != "approve" → rejected), turning a typo into a silent denial.
        decision_normalized = decision.strip().lower()
        if decision_normalized not in {"approve", "reject"}:
            return JSONResponse(
                {
                    "error": "decision must be 'approve' or 'reject'",
                    "code": "bad_request",
                },
                status_code=400,
            )
        if daemon.gates is None:
            return JSONResponse(
                {"error": "gate queue unavailable", "code": "unavailable"},
                status_code=503,
            )
        if daemon.gates.get(gate_id) is None:
            return JSONResponse(
                {"error": "gate not found", "code": "not_found"},
                status_code=404,
            )
        approved = daemon.gates.resolve(gate_id, decision_normalized)
        return JSONResponse({"gate_id": gate_id, "decision": decision_normalized, "approved": approved, "status": "resolved"})

    async def post_runs(request):
        # MUTATING: submit a journaled run — the canonical exec-tool path.
        # Mirrors post_jobs body validation + run_command call, but returns
        # run_id (not job_id) at 201. Auth-gated like post_jobs.
        denied = _consent_auth_error(request)
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
                {"error": "body must include 'cmd' (a string or argv list)",
                 "code": "bad_request"},
                status_code=400,
            )
        env = body.get("env")
        if env is not None and not isinstance(env, dict):
            return JSONResponse(
                {"error": "'env' must be an object of string overrides",
                 "code": "bad_request"},
                status_code=400,
            )
        inputs = body.get("inputs")
        if inputs is not None and not (
            isinstance(inputs, list) and all(isinstance(x, str) for x in inputs)
        ):
            return JSONResponse(
                {"error": "'inputs' must be a list of path strings",
                 "code": "bad_request"},
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
        except Exception as exc:  # noqa: BLE001 - surface submit failure as 500
            return JSONResponse(
                {"error": f"failed to submit run: {exc}", "code": "submit_failed"},
                status_code=500,
            )
        return JSONResponse({"run_id": job_id, "status": "submitted"}, status_code=201)

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/v1/state", get_state, methods=["GET"]),
        Route("/v1/supervision", get_supervision, methods=["GET"]),
        Route("/v1/domain", get_domain, methods=["GET"]),
        Route("/v1/capabilities", get_capabilities, methods=["GET"]),
        Route("/v1/orient", get_orient, methods=["GET"]),
        Route("/v1/workflows", get_workflows, methods=["GET"]),
        Route("/v1/sandbox", get_sandbox, methods=["GET"]),
        Route("/v1/lineage", get_lineage, methods=["GET"]),
        Route("/v1/lineage.mermaid", get_lineage_mermaid, methods=["GET"]),
        Route("/v1/staleness", get_staleness, methods=["GET"]),
        Route("/v1/staleness/verdict", post_staleness_verdict, methods=["POST"]),
        Route("/v1/rebuild/plan", get_rebuild_plan, methods=["GET"]),
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/v1/jobs", get_jobs, methods=["GET"]),
        Route("/v1/jobs", post_jobs, methods=["POST"]),
        Route("/v1/jobs/{job_id}", get_job, methods=["GET"]),
        Route("/v1/runs", get_runs, methods=["GET"]),
        Route("/v1/runs/{run_id}", get_run, methods=["GET"]),
        Route("/v1/runs/{run_id}/resume", post_run_resume, methods=["POST"]),
        Route("/v1/continuation", get_continuation, methods=["GET"]),
        Route("/v1/continuation/start", post_continuation_start, methods=["POST"]),
        Route("/v1/continuation/stop", post_continuation_stop, methods=["POST"]),
        Route("/v1/stream", stream_v1, methods=["GET"]),
        Route("/v1/gates/pending", get_gates_pending, methods=["GET"]),
        Route("/v1/gates/respond", post_gates_respond, methods=["POST"]),
        Route("/v1/runs", post_runs, methods=["POST"]),
        Route("/v1/events", stream_events, methods=["GET"]),
        Route("/v1/events/recent", get_events_recent, methods=["GET"]),
        Route("/v1/consent/pending", get_consent_pending, methods=["GET"]),
        Route("/v1/consent/grants", get_consent_grants, methods=["GET"]),
        Route("/v1/notifications", get_notifications, methods=["GET"]),
        Route("/v1/consent/request", post_consent_request, methods=["POST"]),
        Route("/v1/consent/approve", post_consent_approve, methods=["POST"]),
        Route("/v1/consent/deny", post_consent_deny, methods=["POST"]),
        Route("/v1/consent/consume", post_consent_consume, methods=["POST"]),
    ]
    return Starlette(routes=routes)


def _parse_kinds(raw: str | None) -> set[str] | None:
    """Parse a comma-separated ?kinds= filter into a set, or None for all."""
    if not raw:
        return None
    kinds = {k.strip() for k in raw.split(",") if k.strip()}
    return kinds or None


def serve(daemon: "Daemon") -> None:
    """Run the daemon's HTTP server in the foreground (blocking).

    Binds to the configured host/port (localhost by default). Blocks until
    interrupted. Used by `research-os daemon start`.
    """
    _require_web_stack()
    import socket as _socket

    import uvicorn

    app = build_app(daemon)
    cfg = daemon.config

    # Per-project on a shared node: the default port (8787) is frequently held
    # by ANOTHER project's daemon. Rather than fail the bind (and previously
    # exit 0 as if it had started), probe the configured port and fall forward
    # to the next free one so each project's daemon actually comes up. The real
    # bound port is written into the discovery descriptor by the caller, so
    # `daemon status` / `daemon stop` find it.
    def _port_free(host: str, port: int) -> bool:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return True
            except OSError:
                return False

    if not _port_free(cfg.host, cfg.port):
        original = cfg.port
        chosen = None
        for candidate in range(cfg.port + 1, cfg.port + 50):
            if _port_free(cfg.host, candidate):
                chosen = candidate
                break
        if chosen is None:
            raise RuntimeError(
                f"daemon port {original} is in use and no free port was found in "
                f"{original + 1}..{original + 49}. Free one or pass --port."
            )
        logger.warning(
            "daemon port %s busy (another project's daemon?) — using %s instead",
            original, chosen,
        )
        # cfg is a frozen dataclass; update in place so the discovery descriptor
        # (written from daemon.config.port) records the REAL bound port.
        object.__setattr__(cfg, "port", chosen)

    logger.info("Research OS daemon serving on %s", cfg.base_url)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")
