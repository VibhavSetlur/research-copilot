from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from starlette.responses import JSONResponse

from research_os.daemon.routes.workflows import register_workflows


class _App:
    def __init__(self):
        self.routes = []


def _route_map(app):
    return {route.path: route for route in app.routes}


def test_workflow_execute_route_registered():
    app = _App()
    daemon = SimpleNamespace(root="/tmp/project")

    register_workflows(app, daemon)

    assert "/v1/workflows" in _route_map(app)
    assert "/v1/workflows/execute" in _route_map(app)


async def _call_route(route, payload):
    request = MagicMock()
    request.json = AsyncMock(return_value=payload)
    return await route.endpoint(request)


def test_workflow_execute_success(monkeypatch):
    app = _App()
    daemon = SimpleNamespace(root="/tmp/project")
    register_workflows(app, daemon)
    route = _route_map(app)["/v1/workflows/execute"]

    fake_executor = MagicMock()
    fake_executor.compile.return_value = object()
    fake_executor.execute = AsyncMock(return_value={"step_0": {"ok": True}})
    fake_protocol = MagicMock()
    fake_driver = MagicMock()
    fake_driver.load_protocol.return_value = fake_protocol

    monkeypatch.setattr("research_os.daemon.routes.workflows.ProtocolDriver", lambda root: fake_driver)
    monkeypatch.setattr("research_os.daemon.routes.workflows.DAGExecutor", lambda: fake_executor)

    response = asyncio.run(_call_route(route, {"protocol_id": "demo/protocol", "inputs": {"x": 1}}))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200
    fake_driver.load_protocol.assert_called_once_with("demo/protocol")
    fake_executor.compile.assert_called_once_with(fake_protocol)
    fake_executor.execute.assert_awaited_once()


def test_workflow_execute_missing_protocol_id():
    app = _App()
    daemon = SimpleNamespace(root="/tmp/project")
    register_workflows(app, daemon)
    route = _route_map(app)["/v1/workflows/execute"]

    response = asyncio.run(_call_route(route, {"inputs": {}}))

    assert response.status_code == 400
    assert b"protocol_id" in response.body


def test_workflow_execute_invalid_inputs_type():
    app = _App()
    daemon = SimpleNamespace(root="/tmp/project")
    register_workflows(app, daemon)
    route = _route_map(app)["/v1/workflows/execute"]

    response = asyncio.run(_call_route(route, {"protocol_id": "demo/protocol", "inputs": []}))

    assert response.status_code == 400
    assert b"inputs" in response.body
