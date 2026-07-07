from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.routing import Route


def register_plugins(app, daemon) -> None:
    async def get_plugins(request):
        from .. import registry as _registry

        try:
            plugins = _registry.plugin_registry().discover()
            result = []
            for plugin in plugins:
                result.append({
                    "name": getattr(plugin, "name", None),
                    "description": getattr(plugin, "description", None),
                    "version": getattr(plugin, "version", None),
                })
            return JSONResponse({"plugins": result})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"plugins": [], "error": str(exc)})

    app.routes.append(Route("/v1/plugins", get_plugins, methods=["GET"]))
