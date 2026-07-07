from __future__ import annotations

import json

from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route


def _parse_kinds(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    kinds = {k.strip() for k in raw.split(",") if k.strip()}
    return kinds or None


def register_events(app, daemon) -> None:
    async def get_events_recent(request):
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
        return JSONResponse({"events": [e.to_dict() for e in events], "last_seq": daemon.events.last_seq, "stats": daemon.events.stats()})

    async def stream_events(request):
        import anyio

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
            gen = daemon.events.subscribe(kinds=kinds, root=root, backfill=backfill, after_seq=after_seq)
            try:
                for event in gen:
                    anyio.from_thread.run(send_stream.send, event)
            except anyio.BrokenResourceError:
                pass
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

        return StreamingResponse(event_publisher(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    app.routes.extend([Route("/v1/events", stream_events, methods=["GET"]), Route("/v1/events/recent", get_events_recent, methods=["GET"])])
