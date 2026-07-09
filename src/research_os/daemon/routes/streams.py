from __future__ import annotations

import json
from datetime import datetime, timezone

from starlette.responses import StreamingResponse
from starlette.routing import Route

from .events import _parse_kinds


def register_streams(app, daemon) -> None:
    async def stream_v1(request):
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
        since_epoch = None
        since_raw = request.query_params.get("since")
        if since_raw:
            try:
                dt = datetime.fromisoformat(since_raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                since_epoch = dt.timestamp()
            except (ValueError, TypeError):
                pass
        backfill = 0 if after_seq else 20
        send_stream, receive_stream = anyio.create_memory_object_stream(64)

        def _pump():
            backfill_events = []
            if since_epoch is not None:
                try:
                    candidates = daemon.events.recent(limit=200, kinds=kinds, root=root)
                    backfill_events = [e for e in candidates if e.ts > since_epoch]
                except Exception:
                    pass
            gen = daemon.events.subscribe(kinds=kinds, root=root, backfill=backfill, after_seq=after_seq)
            try:
                for ev in backfill_events:
                    anyio.from_thread.run(send_stream.send, ev)
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
                        yield f"event: {event.kind}\ndata: {payload}\n\n"

        return StreamingResponse(event_publisher(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    app.routes.append(Route("/v1/stream", stream_v1, methods=["GET"]))
