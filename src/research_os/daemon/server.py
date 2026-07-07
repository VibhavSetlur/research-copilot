"""Daemon HTTP server — the lazy ASGI layer (read-only + authed mutating).

Research-OS calls no LLM and has NO chat gateway. This server exposes the
daemon's own read + mutating endpoints; a client / IDE reasons over the MCP
tools directly. This module is the ONLY place that touches starlette/uvicorn,
and it does so lazily: importing `research_os.daemon.server` must not import
the web stack. The deps live in the optional `[daemon]` extra; if they're
missing we raise a clear, actionable error telling the user to install it.

NOTE: endpoint registration is delegated to `research_os.daemon.routes.*`
modules so `build_app(daemon)` stays a thin compatibility wrapper.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


def build_app(daemon: "Daemon"):
    """Build the Starlette ASGI app bound to a running ``daemon``.

    Imported lazily inside the function so module import stays web-free.
    """
    _require_web_stack()
    from starlette.applications import Starlette

    from .routes import (
        register_capabilities,
        register_consent,
        register_core,
        register_events,
        register_gates,
        register_health,
        register_jobs,
        register_lineage,
        register_memory,
        register_notifications,
        register_plans,
        register_runs,
        register_sandbox,
        register_state,
        register_staleness,
        register_workflows,
    )

    app = Starlette()
    for register in (
        register_health,
        register_state,
        register_core,
        register_workflows,
        register_sandbox,
        register_lineage,
        register_staleness,
        register_jobs,
        register_runs,
        register_plans,
        register_memory,
        register_capabilities,
        register_events,
        register_consent,
        register_gates,
        register_notifications,
    ):
        register(app, daemon)
    return app


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
            original,
            chosen,
        )
        object.__setattr__(cfg, "port", chosen)

    logger.info("Research OS daemon serving on %s", cfg.base_url)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")
