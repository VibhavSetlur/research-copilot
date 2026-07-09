"""Endpoint tests for the daemon HTTP server (Phase 1, read-only API).

Skipped automatically when the optional [daemon] web stack isn't installed,
so the suite still passes on a core-only install.
"""
from __future__ import annotations

import pytest

starlette = pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from research_os.daemon import Daemon  # noqa: E402
from research_os.daemon.server import build_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    (tmp_path / ".os_state").mkdir()
    daemon = Daemon.for_root(tmp_path)
    return TestClient(build_app(daemon)), daemon


def test_healthz(client):
    c, _ = client
    r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "research-os-daemon"
    assert "version" in body
    assert body["serving"] is False  # TestClient doesn't flip serving


def test_state_multi_root(client, tmp_path):
    c, _ = client
    r = c.get("/v1/state")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["roots"][0]["initialized"] is True


def test_state_single_root_filter(client, tmp_path):
    c, _ = client
    r = c.get("/v1/state", params={"root": str(tmp_path)})
    assert r.status_code == 200
    assert r.json()["root"]["initialized"] is True


def test_state_unknown_root_registers_and_returns(client, tmp_path):
    c, _ = client
    other = tmp_path.parent / "not_a_project_xyz"
    r = c.get("/v1/state", params={"root": str(other)})
    assert r.status_code == 200
    assert r.json()["root"]["initialized"] is False


def test_jobs_empty(client):
    c, _ = client
    r = c.get("/v1/jobs")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_orient_endpoint(client):
    c, _ = client
    r = c.get("/v1/orient")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "research-os"
    assert "narrative" in body and body["narrative"]
    assert body["recommended_next_action"]["action"]


def test_workflows_endpoint(client):
    c, _ = client
    r = c.get("/v1/workflows")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "research-os"
    assert "detected" in body
    assert isinstance(body["workflows"], list)


def test_sandbox_endpoint(client):
    c, _ = client
    r = c.get("/v1/sandbox")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "research-os"
    assert body["best_tier"] in ("container", "namespace", "resource", "none")
    assert "tiers_available" in body
    assert "default_limits" in body
    # On any POSIX CI/dev host the resource floor must be present.
    assert "resource" in body["tiers_available"]


def test_capabilities_endpoint(client):
    c, _ = client
    r = c.get("/v1/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "research-os"
    assert body["available"] is True
    assert body["tools"]["total"] > 0
    assert body["protocols"]["total"] > 0
    assert body["field"]["id"]
    # Lean by default: no full schemas unless asked.
    assert "schemas" not in body["tools"]


def test_capabilities_tools_full(client):
    c, _ = client
    r = c.get("/v1/capabilities", params={"tools": "full"})
    assert r.status_code == 200
    schemas = r.json()["tools"]["schemas"]
    assert isinstance(schemas, list) and schemas
    assert schemas[0]["type"] == "function"


def test_jobs_reflects_submitted_job(client):
    c, daemon = client
    daemon.tasks.start()
    try:
        daemon.tasks.submit(lambda: 1, name="probe")
        r = c.get("/v1/jobs")
        assert r.status_code == 200
        assert r.json()["total"] == 1
    finally:
        daemon.tasks.shutdown()


def test_job_not_found(client):
    c, _ = client
    r = c.get("/v1/jobs/nope")
    assert r.status_code == 404


def test_jobs_bad_limit(client):
    c, _ = client
    r = c.get("/v1/jobs", params={"limit": "abc"})
    assert r.status_code == 400


def test_require_web_stack_message():
    # The install hint must name the [daemon] extra.
    from research_os.daemon.server import _INSTALL_HINT

    assert "research-os[daemon]" in _INSTALL_HINT


# ── lineage / staleness / rebuild-plan endpoints (Phase 1.17) ─────────
@pytest.fixture
def chain_client(tmp_path):
    """A daemon whose journal holds a real 2-run chain A -> B.

    A produces model.txt (hash H1); B records model.txt (H1) as an input
    and produces result.txt. The content-addressed link falls out of the
    matching hash, exactly as in production.
    """
    from research_os.daemon.runstore import build_manifest

    (tmp_path / ".os_state").mkdir()
    daemon = Daemon.for_root(tmp_path)
    store = daemon.runstore
    assert store is not None

    h1 = "sha256:" + "a" * 64  # A's output == B's input
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


def test_lineage_endpoint_builds_graph(chain_client):
    c, _, _ = chain_client
    r = c.get("/v1/lineage")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["counts"]["runs"] == 2
    assert body["counts"]["edges"] == 1
    assert body["counts"]["linked"] == 2


def test_lineage_focus_returns_ancestors(chain_client):
    c, _, _ = chain_client
    r = c.get("/v1/lineage", params={"run_id": "bbbb2222"})
    assert r.status_code == 200
    focus = r.json()["focus"]
    assert focus["run_id"] == "bbbb2222"
    assert "aaaa1111" in focus["ancestors"]


def test_staleness_endpoint_flags_changed_input(chain_client):
    c, _, tmp_path = chain_client
    # data.csv doesn't exist on disk -> A is input-stale (recorded hash,
    # missing file) -> B is transitive-stale.
    r = c.get("/v1/staleness")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["counts"]["total"] == 2
    assert set(body["stale"]) == {"aaaa1111", "bbbb2222"}


def test_rebuild_plan_orders_producers_first(chain_client):
    c, _, _ = chain_client
    r = c.get("/v1/rebuild/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    # producer (A) must precede consumer (B).
    assert body["plan"] == ["aaaa1111", "bbbb2222"]
    assert body["counts"]["planned"] == 2
    assert "dry-run" in body["note"]


def test_lineage_bad_limit_is_400(chain_client):
    c, _, _ = chain_client
    r = c.get("/v1/lineage", params={"limit": "xyz"})
    assert r.status_code == 400


def test_endpoints_unavailable_without_runstore(tmp_path):
    # A daemon with no resolved root has no runstore -> graceful "available: False".
    daemon = Daemon.for_root(None)
    if daemon.runstore is not None:
        pytest.skip("daemon resolved a runstore; not the no-root case")
    c = TestClient(build_app(daemon))
    for path in ("/v1/lineage", "/v1/staleness", "/v1/rebuild/plan"):
        body = c.get(path).json()
        assert body["available"] is False


# ── POST /v1/jobs — agent-initiated journaled run (one execution path) ──────


def _gw_daemon(tmp_path):
    (tmp_path / ".os_state").mkdir(exist_ok=True)
    return Daemon.for_root(tmp_path)


def test_post_jobs_no_token_open(tmp_path, monkeypatch):
    """No token configured → endpoint is open (no auth required behind localhost)."""
    monkeypatch.delenv("RESEARCH_OS_DAEMON_TOKEN", raising=False)
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))
    r = c.post("/v1/jobs", json={"cmd": "echo hi"})
    # No token → open; should not get 401/503 for auth reasons (may 400 for bad body)
    assert r.status_code != 401
    assert r.status_code != 503


def test_post_jobs_rejects_bad_token(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))
    r = c.post("/v1/jobs", headers={"Authorization": "Bearer wrong"},
               json={"cmd": "echo hi"})
    assert r.status_code == 401


def test_post_jobs_requires_cmd(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))
    r = c.post("/v1/jobs", headers={"Authorization": "Bearer secret-123"},
               json={"name": "no command"})
    assert r.status_code == 400
    assert r.json()["code"] == "bad_request"


def test_post_jobs_submits_and_journals(tmp_path, monkeypatch):
    # The keystone: a run submitted by an agent through HTTP goes through the
    # same core.run_command lifecycle the CLI uses, so it lands in the live
    # job queue (and, on completion, the durable journal) — not an untracked
    # inline subprocess.
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))
    r = c.post(
        "/v1/jobs",
        headers={"Authorization": "Bearer secret-123"},
        json={"cmd": "echo hello-from-agent", "name": "agent-run", "shell": True},
    )
    assert r.status_code == 201
    body = r.json()
    job_id = body["job_id"]
    assert body["status"] == "submitted"
    # The job is now tracked in the queue under the same id; poll until it
    # reaches a terminal state (it ran through the journaled lifecycle).
    import time
    deadline = time.time() + 10
    job = daemon.tasks.get(job_id)
    while job is not None and not job.status.terminal and time.time() < deadline:
        time.sleep(0.05)
        job = daemon.tasks.get(job_id)
    assert job is not None
    snap = c.get("/v1/jobs").json()
    ids = {j["id"] for j in snap.get("jobs", [])}
    assert job_id in ids


# ── chat route is gone (v5.0.0 removed the LLM gateway) ──────────────────────

def test_no_chat_completions_route(tmp_path):
    """v5.0.0: POST /v1/chat/completions was removed; the route must not exist."""
    (tmp_path / ".os_state").mkdir(exist_ok=True)
    daemon = Daemon.for_root(tmp_path)
    app = build_app(daemon)
    paths = [str(getattr(r, "path", "")) for r in app.routes]
    chat_routes = [p for p in paths if "/v1/chat" in p]
    assert chat_routes == [], f"Expected no /v1/chat/* routes, got: {chat_routes}"


# ── autonomous continuation endpoints ─────────────────────────────────


def test_continuation_get_open_default_inactive(tmp_path):
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))
    r = c.get("/v1/continuation")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body.get("active") in (False, None)


def test_continuation_start_requires_auth(tmp_path, monkeypatch):
    """Token set but not presented → 401."""
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))
    r = c.post("/v1/continuation/start", json={"goal": "build the model"})
    assert r.status_code == 401


def test_continuation_start_stop_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))
    hdr = {"Authorization": "Bearer secret-123"}

    # start a loop
    r = c.post("/v1/continuation/start", json={"goal": "reach the goal"}, headers=hdr)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "started"
    assert body["goal"] == "reach the goal"
    # not opted in (no continue_command) — reported so the AI knows
    assert body["opted_in"] is False

    # the loop is now visible as active
    state = c.get("/v1/continuation").json()
    assert state["active"] is True
    assert state["goal"] == "reach the goal"

    # stop it
    r2 = c.post("/v1/continuation/stop", json={"reason": "goal_met"}, headers=hdr)
    assert r2.status_code == 200
    assert r2.json()["status"] == "stopped"
    assert c.get("/v1/continuation").json()["active"] is False


def test_continuation_start_rejects_empty_goal(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "secret-123")
    daemon = _gw_daemon(tmp_path)
    c = TestClient(build_app(daemon))
    r = c.post(
        "/v1/continuation/start", json={"goal": "  "},
        headers={"Authorization": "Bearer secret-123"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "no_goal"



