"""Daemon configuration — bind address, port, runtime knobs.

Kept stdlib-only and dependency-free so it imports cheaply. Values
resolve in this order (later wins):

1. Built-in defaults (localhost-only, conservative).
2. ``inputs/researcher_config.yaml`` -> ``daemon:`` block, when a
   project root is provided.
3. Environment variables (``RESEARCH_OS_DAEMON_*``).
4. Explicit overrides passed to :meth:`DaemonConfig.resolve`.

SECURITY DEFAULT: the daemon binds to ``127.0.0.1`` only. It is a local
research assistant, not a network service. Phases that add mutating
endpoints MUST add a per-session token on top of this (see ROADMAP §6).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


# Localhost only, by design. See module docstring.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


@dataclass(frozen=True)
class DaemonConfig:
    """Immutable daemon runtime configuration.

    Frozen so a running daemon can hold a stable snapshot; use
    :meth:`with_overrides` to derive a modified copy.
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    # Per-session bearer token clients must present to call the *mutating*
    # endpoints (/v1/runs, /v1/gates/respond, /v1/consent/*, …). Read from
    # this env var; when unset those endpoints refuse the write (mutating
    # surface MUST be authenticated — ROADMAP §6). Read surfaces stay open
    # behind the 127.0.0.1 bind. RO calls no LLM and has no gateway; this is
    # purely local write-authorization for the daemon's own endpoints.
    auth_token_env: str = "RESEARCH_OS_DAEMON_TOKEN"
    # Enable the read-only web dashboard (Phase 5). Off until built.
    enable_dashboard: bool = False
    # Sandbox execution mode (Phase 4): "auto" detects a container
    # runtime and falls back to native; "native" forces host execution;
    # "off" disables agent code execution entirely.
    sandbox_mode: str = "auto"
    # Background task queue worker count (Phase 1). The "master loop owns
    # execution" primitive runs jobs off the request thread on this pool.
    task_workers: int = 2
    # TTL (seconds) for the registry's per-root state cache. Avoids
    # hammering the filesystem under rapid polling (e.g. a dashboard).
    state_cache_ttl: float = 1.0
    # How often (seconds) the daemon re-runs its self-check (health_notes) so
    # the AI-facing daemon_notes stay fresh DURING a long session instead of
    # only at startup. 0 disables the periodic tick (startup-only). Default 5m.
    self_check_interval: float = 300.0
    # Researcher-notification delivery command (notification spine, intent
    # #4). A shell command the daemon runs once per notification, with the
    # notification JSON on stdin. Empty → persist-only (outbox still
    # written; nothing pushed). The researcher wires this to their own
    # channel (Hermes→Slack, mailx, a webhook…). Read from project config /
    # env — never from an agent-writable surface at request time.
    notify_command: str = ""
    # Autonomous-continuation hook (Phase 4, OPT-IN). A shell command the
    # daemon runs when a long job reaches a terminal state, with a JSON
    # continuation payload on stdin (the finished run + the project goal). The
    # researcher wires this to their agent (Hermes / CC / any) so that after a
    # multi-hour result lands, the AI is automatically re-prompted to CONTINUE
    # the work toward the goal — unattended, while they're away. Empty (the
    # default) → the daemon never auto-continues; nothing runs without the
    # researcher explicitly opting in. Read from project config / env only,
    # never from an agent-writable surface at request time.
    continue_command: str = ""
    # Max autonomous continuation hops for ONE goal before the daemon stops
    # and waits for a human — a hard ceiling so a goal-loop can't run forever.
    continue_max_hops: int = 25
    # Seconds to wait for the continue_command (the researcher's agent) per hop.
    # A real continuing agent needs longer than the old hardcoded 30s; the hop
    # is fire-and-forget past this (the agent keeps running detached).
    continue_timeout: float = 900.0

    _VALID_SANDBOX_MODES = ("auto", "native", "off")

    def __post_init__(self) -> None:
        if self.sandbox_mode not in self._VALID_SANDBOX_MODES:
            raise ValueError(
                f"sandbox_mode must be one of {self._VALID_SANDBOX_MODES}, "
                f"got {self.sandbox_mode!r}"
            )
        if not (0 < self.port < 65536):
            raise ValueError(f"port must be in 1..65535, got {self.port}")
        if self.task_workers < 1:
            raise ValueError(f"task_workers must be >= 1, got {self.task_workers}")
        if self.state_cache_ttl < 0:
            raise ValueError(
                f"state_cache_ttl must be >= 0, got {self.state_cache_ttl}"
            )

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def with_overrides(self, **kwargs: object) -> "DaemonConfig":
        """Return a copy with the given fields replaced (ignores ``None``)."""
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean) if clean else self

    # ── resolution ────────────────────────────────────────────────────
    @classmethod
    def resolve(
        cls,
        root: Path | None = None,
        **overrides: object,
    ) -> "DaemonConfig":
        """Build a config from defaults -> project file -> env -> overrides."""
        cfg = cls()
        if root is not None:
            cfg = cfg.with_overrides(**_from_project_file(Path(root)))
        cfg = cfg.with_overrides(**_from_env())
        cfg = cfg.with_overrides(**overrides)
        return cfg


def _from_project_file(root: Path) -> dict:
    """Read a ``daemon:`` block from ``inputs/researcher_config.yaml``.

    Best-effort: any read/parse error yields an empty override set so the
    daemon still starts on defaults.
    """
    try:
        import yaml  # lazy: yaml is a core dep but keep this import local
    except Exception:
        return {}
    for rel in ("inputs/researcher_config.yaml", "researcher_config.yaml"):
        path = root / rel
        if path.exists():
            try:
                cfg = yaml.safe_load(path.read_text()) or {}
            except Exception:
                return {}
            block = cfg.get("daemon") or {}
            return _coerce(block)
    return {}


def _from_env() -> dict:
    """Pull ``RESEARCH_OS_DAEMON_*`` env vars into an override dict."""
    env = {
        "host": os.environ.get("RESEARCH_OS_DAEMON_HOST"),
        "port": os.environ.get("RESEARCH_OS_DAEMON_PORT"),
        "auth_token_env": os.environ.get("RESEARCH_OS_DAEMON_AUTH_TOKEN_ENV"),
        "enable_dashboard": os.environ.get("RESEARCH_OS_DAEMON_DASHBOARD"),
        "sandbox_mode": os.environ.get("RESEARCH_OS_DAEMON_SANDBOX"),
        "task_workers": os.environ.get("RESEARCH_OS_DAEMON_WORKERS"),
        "state_cache_ttl": os.environ.get("RESEARCH_OS_DAEMON_CACHE_TTL"),
        "notify_command": os.environ.get("RESEARCH_OS_DAEMON_NOTIFY_COMMAND"),
        "continue_command": os.environ.get("RESEARCH_OS_DAEMON_CONTINUE_COMMAND"),
        "continue_max_hops": os.environ.get("RESEARCH_OS_DAEMON_CONTINUE_MAX_HOPS"),
        "continue_timeout": os.environ.get("RESEARCH_OS_DAEMON_CONTINUE_TIMEOUT"),
    }
    return _coerce({k: v for k, v in env.items() if v is not None})


def _coerce(block: dict) -> dict:
    """Coerce a raw config dict to the typed fields DaemonConfig accepts."""
    out: dict = {}
    if "host" in block and block["host"] is not None:
        out["host"] = str(block["host"])
    if "port" in block and block["port"] is not None:
        try:
            out["port"] = int(block["port"])
        except (TypeError, ValueError):
            pass
    for flag in ("enable_dashboard",):
        if flag in block and block[flag] is not None:
            out[flag] = _as_bool(block[flag])
    for skey in (
        "auth_token_env",
        "notify_command",
        "continue_command",
    ):
        if skey in block and block[skey] is not None:
            out[skey] = str(block[skey])
    if "sandbox_mode" in block and block["sandbox_mode"] is not None:
        out["sandbox_mode"] = str(block["sandbox_mode"]).strip().lower()
    if "task_workers" in block and block["task_workers"] is not None:
        try:
            out["task_workers"] = int(block["task_workers"])
        except (TypeError, ValueError):
            pass
    if "state_cache_ttl" in block and block["state_cache_ttl"] is not None:
        try:
            out["state_cache_ttl"] = float(block["state_cache_ttl"])
        except (TypeError, ValueError):
            pass
    if "continue_max_hops" in block and block["continue_max_hops"] is not None:
        try:
            out["continue_max_hops"] = int(block["continue_max_hops"])
        except (TypeError, ValueError):
            pass
    if "continue_timeout" in block and block["continue_timeout"] is not None:
        try:
            out["continue_timeout"] = float(block["continue_timeout"])
        except (TypeError, ValueError):
            pass
    return out


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")
