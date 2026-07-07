"""Phase 7 §13.5 endpoint tests — the full v2 daemon surface.

Tests for every new endpoint added in §13.5:
  GET  /v1/healthz
  GET  /v1/runs/{id}/artifacts
  GET  /v1/runs/{id}/lineage
  GET  /v1/plans
  GET  /v1/plans/{id}
  GET  /v1/memory/search
  GET  /v1/plugins
  GET  /v1/metrics
  POST /v1/runs/{id}/rerun
  POST /v1/runs/{id}/reproduce
  POST /v1/plans
  POST /v1/plans/{id}/step
  POST /v1/memory/record
  DoD guard: no /v1/messages route; no new /v1/chat/* beyond the dead completions one.

Auth pattern: _consent_auth_error helper (enable_gateway=True + bearer matching
RESEARCH_OS_GATEWAY_TOKEN env var).  Each mutating test sets the env var via
monkeypatch and passes headers={"Authorization": "Bearer secret-123"}.

All tests are skipped automatically when the optional [daemon] web stack is
absent so the suite still passes on a core-only install.
"""
from __future__ import annotations

import time

import pytest

starlette = pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from research_os.daemon import Daemon  # noqa: E402
from research_os.daemon.server import build_app  # noqa: E402


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path):
    """Basic daemon client (no gateway, no pre-seeded runs)."""
    (tmp_path / ".os_state").mkdir()
    daemon = Daemon.for_root(tmp_path)
    return TestClient(build_app(daemon)), daemon, tmp_path


def _gw_daemon(tmp_path, **over):
    (tmp_path / ".os_state").mkdir(exist_ok=True)
    return Daemon.for_root(tmp_path, **over)


@pytest.fixture
def gw_client(tmp_path, monkeypatch):
    """Gateway-enabled daemon + matching env token."""
    monkeypatch.setenv("RESEARCH_OS_GATEWAY_TOKEN", "secret-123")
    daemon = _gw_daemon(tmp_path, enable_gateway=True)
    return TestClient(build_app(daemon)), daemon, tmp_path


_AUTH = {"Authorization": "Bearer secret-123"}


@pytest.fixture
def chain_client(tmp_path):
    """Daemon with a 2-run chain A → B pre-seeded in the journal."""
    from research_os.daemon.runstore import build_manifest

    (tmp_path / ".os_state").mkdir()
    daemon = Daemon.for_root(tmp_path)
    store = daemon.runstore
    assert store is not None

    h1 = "sha256:" + "a" * 64
    a = build_manifest(
        run_id="aaaa1111", name="buildA", kind="subprocess",
        status="succeeded", root=str(tmp_path),
        provenance={"inputs": {"data.csv": "sha256:" + "d" * 64}},
        artifacts=[{"path": "model.txt", "sha256": h1, "change": "created"}],
        submitted_at=100.0,
    )
    b = build_manifest(
        run_id="bbbb2222", name="buildB", kind="subprocess",
        status="succeeded", root=str(tmp_path),
        provenance={"inputs": {"model.txt": h1}},
        artifacts=[{"path": "result.txt",
                    "sha256": "sha256:" + "c" * 64, "change": "created"}],
        submitted_at=200.0,
    )
    store.write_manifest("aaaa1111", a)
    store.write_manifest("bbbb2222", b)
    return TestClient(build_app(daemon)), daemon, tmp_path


# ── GET /v1/healthz ───────────────────────────────────────────────────────────

def test_v1_healthz_alias(client):
    c, _, _ = client
    r = c.get("/v1/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "research-os-daemon"
    assert "version" in body


# ── GET /v1/runs/{id}/artifacts ───────────────────────────────────────────────

def test_run_artifacts_returns_list(chain_client):
    c, _, _ = chain_client
    r = c.get("/v1/runs/aaaa1111/artifacts")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "aaaa1111"
    artifacts = body["artifacts"]
    assert isinstance(artifacts, list) and len(artifacts) == 1
    assert artifacts[0]["path"] == "model.txt"


def test_run_artifacts_unknown_id_returns_404(client):
    c, _, _ = client
    r = c.get("/v1/runs/does-not-exist/artifacts")
    assert r.status_code == 404


# ── GET /v1/runs/{id}/lineage ─────────────────────────────────────────────────

def test_run_lineage_returns_focus(chain_client):
    c, _, _ = chain_client
    r = c.get("/v1/runs/bbbb2222/lineage")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    focus = body["focus"]
    assert focus["run_id"] == "bbbb2222"
    assert "aaaa1111" in focus["ancestors"]
    assert focus["descendants"] == []


def test_run_lineage_source_has_descendants(chain_client):
    c, _, _ = chain_client
    r = c.get("/v1/runs/aaaa1111/lineage")
    assert r.status_code == 200
    focus = r.json()["focus"]
    assert focus["ancestors"] == []
    assert "bbbb2222" in focus["descendants"]


# ── GET /v1/plans + POST /v1/plans + GET /v1/plans/{id} + POST step ──────────

def _real_protocol_name():
    """Return a valid protocol name from the loaded registry."""
    from research_os.tools.actions.protocol import ProtocolRegistry
    names = ProtocolRegistry.list_protocols()
    assert names, "no protocols loaded"
    return names[0]


def test_get_plans_empty(client):
    c, _, _ = client
    r = c.get("/v1/plans")
    assert r.status_code == 200
    assert r.json()["plans"] == []


def test_post_plans_requires_auth(client):
    c, _, _ = client
    proto = _real_protocol_name()
    r = c.post("/v1/plans", json={"protocol": proto})
    # No auth => 503 (gateway disabled)
    assert r.status_code in (401, 503)


def test_post_plans_creates_plan(gw_client):
    c, _, _ = gw_client
    proto = _real_protocol_name()
    r = c.post("/v1/plans", json={"protocol": proto}, headers=_AUTH)
    assert r.status_code == 201, r.text
    body = r.json()
    assert "plan_id" in body


def test_get_plan_detail(gw_client):
    c, _, _ = gw_client
    proto = _real_protocol_name()
    r = c.post("/v1/plans", json={"protocol": proto}, headers=_AUTH)
    assert r.status_code == 201
    plan_id = r.json()["plan_id"]

    r2 = c.get(f"/v1/plans/{plan_id}")
    assert r2.status_code == 200
    detail = r2.json()
    assert detail["id"] == plan_id
    assert detail["protocol"] == proto
    assert detail["status"] == "active"


def test_get_plan_unknown_returns_404(client):
    c, _, _ = client
    r = c.get("/v1/plans/does-not-exist")
    assert r.status_code == 404


def test_post_plan_step_advances(gw_client):
    c, _, _ = gw_client
    proto = _real_protocol_name()
    plan_id = c.post("/v1/plans", json={"protocol": proto}, headers=_AUTH).json()["plan_id"]

    r = c.post(f"/v1/plans/{plan_id}/step", json={"result": {"done": True}}, headers=_AUTH)
    assert r.status_code == 200
    summary = r.json()
    assert summary["id"] == plan_id
    assert summary["step_index"] == 1


def test_post_plan_step_unknown_plan_returns_404(gw_client):
    c, _, _ = gw_client
    r = c.post("/v1/plans/no-such-plan/step", json={"result": {}}, headers=_AUTH)
    assert r.status_code == 404


def test_post_plans_unknown_protocol_returns_400_or_404(gw_client):
    c, _, _ = gw_client
    r = c.post("/v1/plans", json={"protocol": "zzz/not_real"}, headers=_AUTH)
    assert r.status_code in (400, 404)
    body = r.json()
    assert "error" in body
    # Must NOT be a 500 — the spec says "do NOT let it 500".
    assert r.status_code != 500


# ── GET /v1/memory/search ─────────────────────────────────────────────────────

def test_memory_search_missing_q_returns_400(client):
    c, _, _ = client
    r = c.get("/v1/memory/search")
    assert r.status_code == 400


def test_memory_search_empty_q_returns_400(client):
    c, _, _ = client
    r = c.get("/v1/memory/search", params={"q": ""})
    assert r.status_code == 400


def test_memory_search_returns_hits(client):
    c, _, _ = client
    r = c.get("/v1/memory/search", params={"q": "test query"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "test query"
    assert isinstance(body["hits"], list)
    # Empty workspace → hits may be [] but response must be valid.


# ── POST /v1/memory/record ────────────────────────────────────────────────────

def test_post_memory_record_requires_auth(client):
    c, _, _ = client
    r = c.post("/v1/memory/record",
               json={"kind": "analysis", "content": "test", "summary": "s"})
    assert r.status_code in (401, 503)


def test_post_memory_record_stores(gw_client):
    c, _, _ = gw_client
    r = c.post(
        "/v1/memory/record",
        json={"kind": "analysis", "content": "Result: p<0.05", "summary": "sig result"},
        headers=_AUTH,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["stored"] is True
    assert "id" in body
    assert body["kind"] == "analysis"


def test_post_memory_record_missing_kind_returns_400(gw_client):
    c, _, _ = gw_client
    r = c.post("/v1/memory/record",
               json={"content": "no kind field"},
               headers=_AUTH)
    assert r.status_code == 400


def test_post_memory_record_missing_content_returns_400(gw_client):
    c, _, _ = gw_client
    r = c.post("/v1/memory/record",
               json={"kind": "analysis"},
               headers=_AUTH)
    assert r.status_code == 400


def test_memory_search_finds_stored_record(gw_client):
    c, _, _ = gw_client
    # Store something distinctive.
    c.post(
        "/v1/memory/record",
        json={"kind": "lesson", "content": "always wash your hands before PCR", "summary": "PCR lesson"},
        headers=_AUTH,
    )
    r = c.get("/v1/memory/search", params={"q": "PCR"})
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert isinstance(hits, list)
    # Keyword search should find it (may not be first; just verify it's present).
    found = any("PCR" in h.get("content", "") or "PCR" in h.get("summary", "")
                for h in hits)
    assert found, f"stored record not found in search results: {hits}"


# ── GET /v1/plugins ───────────────────────────────────────────────────────────

def test_plugins_returns_empty_list(client):
    c, _, _ = client
    r = c.get("/v1/plugins")
    assert r.status_code == 200
    assert r.json()["plugins"] == []


# ── GET /v1/metrics ───────────────────────────────────────────────────────────

def test_metrics_returns_200_text_plain(client):
    c, _, _ = client
    r = c.get("/v1/metrics")
    assert r.status_code == 200
    ct = r.headers.get("content-type", "")
    assert "text/plain" in ct


def test_metrics_contains_up_metric(client):
    c, _, _ = client
    text = c.get("/v1/metrics").text
    assert "research_os_up 1" in text


def test_metrics_contains_runs_and_events(client):
    c, _, _ = client
    text = c.get("/v1/metrics").text
    assert "research_os_runs_total" in text
    assert "research_os_events_total" in text


# ── POST /v1/runs/{id}/rerun ─────────────────────────────────────────────────

def test_post_rerun_unknown_run_returns_404(gw_client):
    c, _, _ = gw_client
    r = c.post("/v1/runs/no-such-run/rerun", json={"overrides": {}}, headers=_AUTH)
    assert r.status_code == 404


def test_post_rerun_requires_auth(client):
    c, _, _ = client
    r = c.post("/v1/runs/aaaa1111/rerun", json={"overrides": {}})
    assert r.status_code in (401, 503)


def test_post_rerun_journaled_run(tmp_path, monkeypatch):
    """A journaled subprocess run can be rerrun; new_run_id + parent_id returned."""
    from research_os.daemon.runstore import build_manifest

    monkeypatch.setenv("RESEARCH_OS_GATEWAY_TOKEN", "secret-123")
    (tmp_path / ".os_state").mkdir()
    daemon = _gw_daemon(tmp_path, enable_gateway=True)
    store = daemon.runstore
    assert store is not None

    manifest = build_manifest(
        run_id="rr001", name="fast-run", kind="subprocess",
        status="succeeded", root=str(tmp_path),
        spec={"cmd": "echo rerun-test", "shell": True},
        submitted_at=10.0,
    )
    store.write_manifest("rr001", manifest)

    c = TestClient(build_app(daemon))
    r = c.post("/v1/runs/rr001/rerun", json={"overrides": {}}, headers=_AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parent_id"] == "rr001"
    assert "new_run_id" in body


# ── POST /v1/runs/{id}/reproduce ─────────────────────────────────────────────

def test_post_reproduce_unknown_run_returns_404(gw_client):
    c, _, _ = gw_client
    r = c.post("/v1/runs/no-such-run/reproduce", json={}, headers=_AUTH)
    assert r.status_code == 404


def test_post_reproduce_requires_auth(client):
    c, _, _ = client
    r = c.post("/v1/runs/aaaa1111/reproduce", json={})
    assert r.status_code in (401, 503)


def test_post_reproduce_journaled_run(tmp_path, monkeypatch):
    """A journaled subprocess run produces a verdict."""
    from research_os.daemon.runstore import build_manifest

    monkeypatch.setenv("RESEARCH_OS_GATEWAY_TOKEN", "secret-123")
    (tmp_path / ".os_state").mkdir()
    daemon = _gw_daemon(tmp_path, enable_gateway=True)
    store = daemon.runstore
    assert store is not None

    manifest = build_manifest(
        run_id="rep001", name="repro-run", kind="subprocess",
        status="succeeded", root=str(tmp_path),
        spec={"cmd": "echo reproduce-test", "shell": True},
        submitted_at=10.0,
    )
    store.write_manifest("rep001", manifest)

    c = TestClient(build_app(daemon))
    # timeout=5 so the test doesn't hang waiting for reproduce to finish.
    r = c.post("/v1/runs/rep001/reproduce", json={"timeout": 5}, headers=_AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "verdict" in body
    assert body["original_id"] == "rep001"


# ── AUTH: mutating endpoint without token returns 401 / 503 ──────────────────

def test_mutating_without_token_denied():
    """A mutating endpoint with no token or wrong token must be refused."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        (Path(tmp) / ".os_state").mkdir()
        daemon = Daemon.for_root(Path(tmp), enable_gateway=False)
        c = TestClient(build_app(daemon))
        for method, path in [
            ("POST", "/v1/plans"),
            ("POST", "/v1/memory/record"),
            ("POST", "/v1/runs/x/rerun"),
            ("POST", "/v1/runs/x/reproduce"),
        ]:
            r = getattr(c, method.lower())(path, json={})
            assert r.status_code in (401, 503), (
                f"{method} {path} should be denied but got {r.status_code}"
            )


# ── DoD guard: no /v1/messages or new /v1/chat/* routes ─────────────────────

def test_no_chat_messages_routes():
    """The spec forbids /v1/messages and any new /v1/chat/* beyond the dead
    gateway's /v1/chat/completions. Assert neither appears in the routes."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".os_state").mkdir()
        daemon = Daemon.for_root(Path(tmp))
        app = build_app(daemon)
        paths = [str(getattr(r, "path", "")) for r in app.routes]
        # /v1/messages must not exist at all.
        assert not any("/v1/messages" in p for p in paths), (
            f"Found /v1/messages route(s): {[p for p in paths if '/v1/messages' in p]}"
        )
        # /v1/chat/* must be limited to the single pre-existing dead gateway route.
        chat_routes = [p for p in paths if "/v1/chat" in p]
        assert chat_routes == ["/v1/chat/completions"], (
            f"Unexpected /v1/chat routes: {chat_routes}"
        )
