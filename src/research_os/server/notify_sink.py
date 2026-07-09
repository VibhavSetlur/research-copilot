"""Notification-outbox sink for sys_notify (reasoning side).

When a daemon is running, ``sys_notify`` should reach the researcher
through the daemon's notification spine (which knows the configured
delivery channel) instead of only appending to a log file nobody tails.
The reasoning layer MUST NOT import ``research_os.daemon`` (the
preflight-enforced seam), so this writes the SAME outbox file by SHAPE —
exactly like ``server/consent.py`` writes/reads the consent ledger.

The daemon owns delivery: it watches the outbox (or the live emit path
does delivery directly). This sink's job is only to durably record the
notification where the daemon's spine can see it. With no daemon present,
the caller keeps its existing log-file behaviour and this sink is a no-op.

stdlib only; fail-safe (any error → silently skip the outbox write, the
log-file path in interaction.notify_researcher still runs).
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

_OUTBOX_SCHEMA = 1


def _outbox_path(root: Path) -> Path:
    from . import daemon_bridge as _bridge

    return _bridge.state_path(root, _bridge.NOTIFICATIONS_OUTBOX)


def _daemon_present(root: Path) -> bool:
    """True iff a daemon is running for this project (descriptor + live PID).

    Delegates to the canonical daemon_bridge.daemon_present — no daemon
    import. Any error → False (degrade: the log-file path still runs).
    """
    from . import daemon_bridge as _bridge

    return _bridge.daemon_present(root)


def sink_notification(
    root: Path,
    message: str,
    level: str,
    *,
    kind: str = "sys_notify",
    context: dict | None = None,
) -> bool:
    """Append a sys_notify message to the daemon outbox, IF a daemon is up.

    Returns True if the record was written (daemon present + write ok),
    False otherwise (no daemon, or any error). Never raises — the caller's
    log-file notification is the durable fallback.

    ``context`` is an optional structured payload merged into the record's
    ``context`` block (e.g. the gate_key + fingerprint of a blocked floor
    gate) so a client/daemon can route or de-duplicate on it.

    The record is marked ``delivered=False`` / delivery not attempted: the
    daemon's spine is responsible for pushing it through the configured
    channel. The reasoning side cannot run the delivery command (it doesn't
    know the daemon config and must not shell out on the agent's behalf).
    """
    try:
        if not _daemon_present(Path(root)):
            return False
        ctx = {"source": kind}
        if isinstance(context, dict):
            ctx.update(context)
        rec = {
            "schema": _OUTBOX_SCHEMA,
            "id": "ntfy_" + secrets.token_hex(4),
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "kind": kind,
            "level": level if level in {"info", "action_required", "warn"} else "info",
            "title": message[:120],
            "body": message,
            "context": ctx,
            "delivered": False,
            "delivery": {"attempted": False, "ok": None,
                         "detail": f"queued by {kind}; daemon delivers"},
        }
        path = _outbox_path(Path(root))
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, separators=(",", ":")) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except (OSError, ValueError):
        return False


# A gate-block page for the SAME (gate_key, fingerprint) is emitted at most
# once per this window — a hands-off agent that retries a blocked floor gate
# in a tight loop must not flood the away researcher's channel. The window is
# generous (longer than the consent token TTL) so one approval cycle yields
# exactly one page.
_GATE_BLOCK_DEDUP_SECONDS = 600


def _recent_gate_block_pages(root: Path) -> dict[str, float]:
    """Map ``gate_dedup_key -> latest_ts_epoch`` from the existing outbox.

    Reads the outbox by shape (best-effort). Used to de-duplicate repeated
    gate-block pages for the same blocked action. Any read error → empty map
    (fail toward notifying, never toward silence — a missed page is worse
    than a duplicate one when the user is away).
    """
    path = _outbox_path(Path(root))
    out: dict[str, float] = {}
    try:
        if not path.exists():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or rec.get("kind") != "gate_block":
                continue
            dk = (rec.get("context") or {}).get("dedup_key")
            if not isinstance(dk, str):
                continue
            ts = _parse_epoch(rec.get("ts"))
            if ts is not None and ts > out.get(dk, 0.0):
                out[dk] = ts
    except OSError:
        return {}
    return out


def _parse_epoch(ts) -> float | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def notify_gate_blocked(
    root: Path,
    *,
    tool: str,
    gate_key: str,
    arg_fingerprint: str,
    reason: str = "",
) -> bool:
    """Page the away researcher that an unattended floor gate is BLOCKED.

    Called by the gate ONLY on the daemon-enforced ``consent_required`` path
    (the truly unattended case: a daemon is the authority and the human is
    away). Emits an ``action_required`` record onto the daemon outbox so the
    researcher's configured channel surfaces that the autopilot agent is
    stuck awaiting approval — otherwise a wedged/looping/crashed agent leaves
    the human with no signal that action is needed.

    De-duplicated on (gate_key, arg_fingerprint): the same blocked action
    pages at most once per :data:`_GATE_BLOCK_DEDUP_SECONDS`, so an agent
    retrying in a loop does not flood the channel. Never raises; returns True
    iff a page was written (daemon present, not a recent duplicate, write ok).
    """
    try:
        root = Path(root)
        if not _daemon_present(root):
            return False
        dedup_key = f"{gate_key}|{arg_fingerprint}"
        recent = _recent_gate_block_pages(root)
        last = recent.get(dedup_key)
        if last is not None:
            now = datetime.now(timezone.utc).timestamp()
            if now - last < _GATE_BLOCK_DEDUP_SECONDS:
                return False  # already paged for this exact blocked action
        because = f" — {reason}" if reason else ""
        message = (
            f"Autopilot is BLOCKED: '{tool}' hit floor gate '{gate_key}' and "
            f"needs your approval before it can proceed{because}. Review the "
            "pending consent request and approve or deny it (CLI: research-os "
            "daemon consent approve)."
        )
        return sink_notification(
            root,
            message,
            "action_required",
            kind="gate_block",
            context={
                "gate_key": gate_key,
                "tool": tool,
                "arg_fingerprint": arg_fingerprint,
                "dedup_key": dedup_key,
            },
        )
    except Exception:  # noqa: BLE001 - paging is best-effort; never break the gate
        return False
