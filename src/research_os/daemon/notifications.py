"""Notification spine — the daemon's one channel to reach the researcher.

Daemon intent #4 ("notify the researcher on completion, incl. via Hermes").
Every notification flows through ONE durable, append-only outbox:

    .os_state/notifications/outbox.jsonl

and is optionally pushed through a researcher-configured delivery command
(``DaemonConfig.notify_command``) that reads the notification JSON on
stdin. The outbox is the source of truth (always written); delivery is
best-effort on top, so a missing/failing channel never loses the record
and never breaks the job that triggered it.

stdlib only. See docs/NOTIFICATION_SPINE.md.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUTBOX_SCHEMA = 1
_DELIVERY_TIMEOUT_S = 15.0

_VALID_LEVELS = {"info", "action_required", "warn"}


def _outbox_path(root: str | Path) -> Path:
    return Path(root) / ".os_state" / "notifications" / "outbox.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_line(path: Path, record: dict) -> None:
    """Append one JSON record + newline. O_APPEND keeps small writes atomic.

    Each record is independent, so even a torn final line never corrupts
    prior records (the reader skips unparseable lines).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _deliver(record: dict, notify_command: str) -> dict:
    """Best-effort push of one notification via the configured command.

    The command receives the notification JSON on stdin. Returns a
    ``delivery`` dict ({attempted, ok, detail}). NEVER raises — a missing
    or failing command is recorded, not propagated.
    """
    if not notify_command:
        return {"attempted": False, "ok": None, "detail": "no notify_command configured"}
    try:
        proc = subprocess.run(
            notify_command,
            shell=True,
            input=json.dumps(record, default=str),
            capture_output=True,
            text=True,
            timeout=_DELIVERY_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"attempted": True, "ok": False,
                "detail": f"delivery timed out after {_DELIVERY_TIMEOUT_S}s"}
    except Exception as exc:  # noqa: BLE001 - delivery must never break emit
        return {"attempted": True, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
    if proc.returncode == 0:
        return {"attempted": True, "ok": True, "detail": (proc.stdout or "").strip()[:200]}
    return {"attempted": True, "ok": False,
            "detail": (proc.stderr or proc.stdout or "non-zero exit").strip()[:200]}


def emit(
    root: str | Path,
    *,
    kind: str,
    title: str,
    body: str = "",
    level: str = "info",
    context: dict[str, Any] | None = None,
    notify_command: str = "",
) -> dict:
    """Write one notification to the outbox and attempt delivery.

    Returns the persisted record (including its ``delivery`` outcome). The
    outbox write is the durable part; delivery is best-effort and recorded.
    Failures in delivery are captured in the record, never raised — a
    notification must never break the job or gate that triggered it.
    """
    if level not in _VALID_LEVELS:
        level = "info"
    record = {
        "schema": OUTBOX_SCHEMA,
        "id": "ntfy_" + secrets.token_hex(4),
        "ts": _now_iso(),
        "kind": str(kind),
        "level": level,
        "title": str(title),
        "body": str(body),
        "context": context or {},
    }
    delivery = _deliver(record, notify_command)
    record["delivered"] = bool(delivery.get("ok"))
    record["delivery"] = delivery
    try:
        _append_line(_outbox_path(root), record)
    except OSError:
        # Even the durable write failed (read-only fs etc.) — return the
        # record so the caller at least has it in memory; do not raise.
        pass
    return record


def read_outbox(
    root: str | Path,
    *,
    undelivered_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    """Read recent outbox records (newest last). Skips unparseable lines.

    Fail-safe: a missing/unreadable outbox yields []. ``undelivered_only``
    filters to records whose delivery did not succeed (so a client can
    surface what the researcher actually missed).
    """
    path = _outbox_path(root)
    out: list[dict] = []
    try:
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if undelivered_only and rec.get("delivered") is True:
                    continue
                out.append(rec)
    except OSError:
        return []
    if limit and len(out) > limit:
        out = out[-limit:]
    return out


def emit_job_terminal(
    root: str | Path,
    job: dict,
    *,
    notify_command: str = "",
) -> dict | None:
    """Emit a notification for a terminal job (succeeded/failed/cancelled).

    Distils a job dict (from JobQueue.to_dict) into a researcher-facing
    notification. Returns None for non-terminal / unknown status so callers
    can wire this unconditionally on every job event.
    """
    status = str(job.get("status") or "")
    if status not in {"succeeded", "failed", "cancelled"}:
        return None
    name = job.get("name") or job.get("id") or "job"
    started = job.get("started_at")
    finished = job.get("finished_at")
    dur = ""
    if isinstance(started, (int, float)) and isinstance(finished, (int, float)):
        secs = max(0, int(finished - started))
        dur = f" in {secs // 60}m{secs % 60:02d}s" if secs >= 60 else f" in {secs}s"
    if status == "succeeded":
        level, body = "info", f"{name} finished{dur}."
    elif status == "failed":
        level = "action_required"
        body = f"{name} FAILED{dur}: {job.get('error') or 'unknown error'}"
    else:
        level, body = "warn", f"{name} was cancelled{dur}."
    return emit(
        root,
        kind=f"job.{status}",
        title=f"Job '{name}' {status}",
        body=body,
        level=level,
        context={"job_id": job.get("id"), "status": status},
        notify_command=notify_command,
    )


def emit_runs_interrupted(
    root: str | Path,
    run_ids: list[str],
    *,
    notify_command: str = "",
) -> dict | None:
    """Emit ONE notification when the daemon rehydrates interrupted runs.

    Called on daemon startup after orphaned (non-terminal) runs from a prior
    crash/reboot are marked INTERRUPTED. This is the "you walked away and the
    box rebooted mid-run" case — the researcher should learn their work didn't
    finish the moment they (or their notify channel) reconnect, not silently
    discover a phantom-dead run later. Returns None when there's nothing to
    report so the caller can wire it unconditionally.
    """
    if not run_ids:
        return None
    n = len(run_ids)
    plural = "run" if n == 1 else "runs"
    return emit(
        root,
        kind="runs.interrupted",
        title=f"{n} {plural} interrupted",
        body=(
            f"{n} {plural} were in flight when the daemon last stopped "
            "(crash or reboot) and did not complete. Re-run the affected "
            "step(s) so the work finishes; partial output may be present. "
            "See: research-os runs (status=interrupted)."
        ),
        level="action_required",
        context={"run_ids": list(run_ids)[:50], "count": n},
        notify_command=notify_command,
    )
