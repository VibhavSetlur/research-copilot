"""Daemon bridge — the reasoning side's single, canonical view of the daemon.

docs/DAEMON_BRIDGE.md. The MCP / reasoning layer (``server/``,
``tools/``) talks to the daemon ONLY through on-disk contracts read by
shape — the preflight-enforced seam (ARCHITECTURE #1): this module, like every
reasoning-side reader, MUST NOT import ``research_os.daemon``. The daemon
is an opaque local service that self-advertises a descriptor and writes
sidecar files; this module is the ONE place that knows where those files
live and how to tell whether the daemon is alive.

Before this module, the descriptor-read + PID-liveness check and the
``.os_state/`` contract paths were duplicated across consent.py,
notify_sink.py, staleness_state.py, and meta_workspace.py — four copies
that could drift. This is their single source of truth; those modules now
delegate here. No behaviour change: this is the superset of the careful
versions of each.

stdlib only; every function fails SAFE (errors → "no daemon" / None), so
the degrade-to-stdio path is never broken by a bad descriptor.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ── the .os_state/ contract paths (relative to a project root) ────────────
STATE_DIR = ".os_state"
DAEMON_DESCRIPTOR = "daemon.json"
CONSENT_DIR = "consent"
CONSENT_GRANTED = "consent/granted.json"
CONSENT_SPENT = "consent/spent.json"
NOTIFICATIONS_OUTBOX = "notifications/outbox.jsonl"
STALENESS_VERDICT = "staleness/verdict.json"
DAEMON_NOTES = "daemon_notes.json"
RUNS_DIR = "runs"
GATES_DIR = "gates"  # HITL gate queue (§12.4)
PLANS_DIR = "plans"  # protocol-driver plan store (§13.3)


def state_path(root: str | Path, *parts: str) -> Path:
    """Join a path under ``<root>/.os_state/`` from contract-relative parts.

    e.g. ``state_path(root, CONSENT_GRANTED)`` →
    ``<root>/.os_state/consent/granted.json``.
    """
    return Path(root).joinpath(STATE_DIR, *parts)


def descriptor_path(root: str | Path) -> Path:
    """Path to the daemon's self-advertised discovery descriptor."""
    return state_path(root, DAEMON_DESCRIPTOR)


def read_descriptor(root: str | Path) -> dict[str, Any] | None:
    """Read + parse the daemon descriptor, or None on any failure.

    Does NOT check PID liveness — use :func:`daemon_present` for that. A
    well-formed descriptor dict is returned even if the process is dead, so
    callers that want the advertised metadata (version, base_url) can read
    it; liveness is a separate question.
    """
    path = descriptor_path(root)
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _pid_alive(pid: Any) -> bool:
    """POSIX liveness check via ``os.kill(pid, 0)``. Fail-safe to False.

    PermissionError = the PID exists but is owned by another user → it IS a
    live process (the daemon is running), so True.
    """
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def daemon_present(root: str | Path) -> bool:
    """True iff a daemon is running for this project (descriptor + live PID).

    The single canonical check: read ``.os_state/daemon.json``, confirm the
    advertised PID is alive. No daemon import. Any error → False (degrade to
    in-process behaviour, never block stdio-only users). A descriptor whose
    PID is dead or uncheckable is treated as "not running" (a crashed daemon
    left a stale file).
    """
    desc = read_descriptor(root)
    if desc is None:
        return False
    return _pid_alive(desc.get("pid"))


def daemon_base_url(root: str | Path) -> str | None:
    """Base URL of a LIVE daemon for this root, or None.

    Returns None when no descriptor, a dead PID, or no resolvable address —
    so a caller can ``if (url := daemon_base_url(root)):`` and know the HTTP
    surface is worth probing.
    """
    desc = read_descriptor(root)
    if desc is None or not _pid_alive(desc.get("pid")):
        return None
    base = desc.get("base_url")
    if isinstance(base, str) and base:
        return base
    host, port = desc.get("host"), desc.get("port")
    if host and port:
        return f"http://{host}:{port}"
    return None


def http_get(
    base_url: str,
    path: str,
    timeout: float = 2.0,
    headers: "dict[str, str] | None" = None,
) -> "tuple[int | None, dict[str, Any] | None]":
    """GET base_url+path and return (status_code, parsed_json_or_None).

    Pure stdlib (urllib). Probes a running daemon's read-only HTTP surface
    WITHOUT importing the daemon package — the daemon is treated as an
    opaque local service, exactly as an external client would. Localhost
    only by design (the daemon binds 127.0.0.1).

    Returns ``(None, None)`` on any transport failure (fail-safe, never raises).
    ``headers`` merges extra HTTP headers (e.g. ``Authorization: Bearer …``).
    """
    import urllib.request

    url = base_url.rstrip("/") + path
    try:
        req = urllib.request.Request(url, method="GET")  # noqa: S310 - localhost only
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except Exception:  # noqa: BLE001 - any probe failure → (None, None) (fail-safe)
        return None, None


def http_post(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    timeout: float = 2.0,
    headers: dict[str, str] | None = None,
) -> tuple[int | None, dict[str, Any] | None]:
    """POST JSON to base_url+path. Returns (status_code, parsed_json_or_None).

    Stdlib only; localhost only. Unlike http_get this surfaces the status
    code so a caller can distinguish 201 (created) from 4xx (bad request) —
    the consent-request flow needs that. On a transport failure returns
    (None, None) — fail-safe, never raises.

    ``headers`` (optional) merges extra HTTP headers into the request;
    ``Content-Type: application/json`` is always set and cannot be overridden.
    Intended for adding an ``Authorization: Bearer <token>`` header when
    calling auth-gated daemon endpoints (e.g. ``POST /v1/runs``).
    """
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8")
    merged_headers: dict[str, str] = {}
    if headers:
        merged_headers.update(headers)
    merged_headers["Content-Type"] = "application/json"  # always last → wins
    req = urllib.request.Request(  # noqa: S310 - localhost only
        url, data=data, headers=merged_headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - localhost only
            body = resp.read().decode("utf-8")
            parsed = json.loads(body) if body else None
            return resp.status, (parsed if isinstance(parsed, dict) else None)
    except urllib.error.HTTPError as exc:  # structured error body, keep the code
        try:
            parsed = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            parsed = None
        return exc.code, (parsed if isinstance(parsed, dict) else None)
    except Exception:  # noqa: BLE001 - transport failure → (None, None)
        return None, None


def daemon_bearer(root: str | Path) -> str | None:
    """Return the daemon's bearer token if the operator exported it.

    RO calls no LLM and has no gateway; this token only authorizes the
    daemon's own mutating endpoints (/v1/runs, /v1/gates/respond, …). Reads
    the descriptor's advertised ``auth_token_env`` field (falling back to the
    documented default ``RESEARCH_OS_DAEMON_TOKEN``, then to the pre-5.0
    ``RESEARCH_OS_GATEWAY_TOKEN`` for one release) and returns the value of
    that env-var, or ``None`` when no token is set.

    Call-site convention: if the return is ``None`` the caller sends no
    Authorization header. When the daemon has no token configured, mutating
    endpoints are open on localhost; when it does, an unauthenticated POST
    gets 401 → degrade-open to native execution.
    No daemon import — reads only the on-disk descriptor by shape.
    """
    desc = read_descriptor(root)
    env_name = (desc or {}).get("auth_token_env") or "RESEARCH_OS_DAEMON_TOKEN"
    token = os.environ.get(env_name)
    if not token:
        # Back-compat: honor the pre-5.0 env name for one release.
        token = os.environ.get("RESEARCH_OS_GATEWAY_TOKEN")
    return token or None


def read_daemon_notes(root: str | Path) -> dict[str, Any] | None:
    """Read the daemon's startup self-check notes (.os_state/daemon_notes.json).

    The daemon writes this on startup (health_notes.write_notes) with any
    structural problems / interrupted runs / unframed intake it noticed. Read
    by-shape (no daemon import) so sys_boot/sys_daemon can surface the daemon's
    findings to the agent. Returns None when absent/unreadable (fail-safe).
    """
    try:
        path = state_path(root, DAEMON_NOTES)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None

