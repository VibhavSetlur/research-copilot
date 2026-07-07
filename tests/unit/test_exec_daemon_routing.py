"""Tests — §12.5 exec-tool daemon routing.

Verifies:
1. No daemon (daemon_base_url → None) → native exec, NO warning (FIX 7).
2. Fake daemon (submit 201 + poll terminal) → stdout/output present, run_id,
   native NOT executed (marker check). (FIX 1)
3. Daemon present but submit 503 (gateway off) → degrade to native + warning.
4. Polling failure (http_get → None,None) → degrade to native + warning.
5. Run stays "running" past timeout → status running + run_id, no hang.
6. tool_task op=run with daemon → fire-and-forget (run_id returned, no poll).
7. Seam: research_exec does NOT import research_os.daemon.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parsed(result):
    """Extract the dict payload from a handler's _text(...) list result."""
    assert isinstance(result, list) and len(result) == 1
    text = result[0].text
    return json.loads(text)


def _make_root(tmp_path: Path) -> Path:
    """Create a minimal project-root skeleton."""
    (tmp_path / "workspace" / "logs").mkdir(parents=True)
    (tmp_path / "inputs").mkdir(parents=True)
    return tmp_path


def _write_py_script(root: Path, name: str = "hello.py", content: str | None = None) -> Path:
    script = root / name
    script.write_text(content or 'print("hello")\n')
    return script


def _write_bash_script(root: Path, name: str = "run.sh", content: str | None = None) -> Path:
    script = root / name
    script.write_text(content or "#!/bin/bash\necho hello\n")
    script.chmod(0o755)
    return script


# Terminal manifest returned by the fake http_get poll.
_TERMINAL_MANIFEST = {
    "status": "succeeded",
    "result": {"returncode": 0},
    "duration_s": 0.5,
    "log": ["hello from daemon"],
}

# A terminal manifest with nonzero exit (failed run).
_FAILED_MANIFEST = {
    "status": "failed",
    "result": {"returncode": 1},
    "duration_s": 0.1,
    "log": ["error: something went wrong"],
}


def _fake_http_get_terminal(base_url, path, timeout=2.0, headers=None):
    """Fake http_get that returns a terminal manifest for any run_id."""
    return 200, dict(_TERMINAL_MANIFEST)


def _fake_http_get_none(base_url, path, timeout=2.0, headers=None):
    """Fake http_get that simulates daemon vanishing (fail-safe)."""
    return None, None


# ---------------------------------------------------------------------------
# Seam guard
# ---------------------------------------------------------------------------

def test_research_exec_does_not_import_daemon_package():
    """SEAM: research_exec must never pull in research_os.daemon."""
    import research_os.server.handlers.research_exec as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    import_patterns = [
        "import research_os.daemon",
        "from research_os.daemon",
        "from research_os import daemon",
        "from ..daemon import",
        "from .daemon import",
        "from ...daemon",
    ]
    for pattern in import_patterns:
        assert pattern not in src, (
            f"research_exec.py has a seam violation — found {pattern!r}"
        )


def test_try_daemon_run_not_in_daemon_package():
    """_try_daemon_run lives in research_exec, not in research_os.daemon."""
    import research_os.server.handlers.research_exec as mod
    assert hasattr(mod, "_try_daemon_run")


def test_await_daemon_run_in_research_exec():
    """_await_daemon_run exists in research_exec (FIX 1)."""
    import research_os.server.handlers.research_exec as mod
    assert hasattr(mod, "_await_daemon_run")


# ---------------------------------------------------------------------------
# _try_daemon_run unit tests
# ---------------------------------------------------------------------------

class TestTryDaemonRun:
    def _fn(self):
        from research_os.server.handlers.research_exec import _try_daemon_run
        return _try_daemon_run

    def test_returns_none_when_no_daemon(self, tmp_path):
        fn = self._fn()
        with patch(
            "research_os.server.daemon_bridge.daemon_base_url", return_value=None
        ):
            assert fn(tmp_path, ["python", "x.py"]) is None

    def test_returns_body_on_201(self, tmp_path):
        fn = self._fn()
        body = {"run_id": "abc123", "status": "submitted"}
        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value="tok"),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(201, body)),
        ):
            result = fn(tmp_path, ["python", "x.py"])
        assert result == body

    def test_returns_none_on_503(self, tmp_path):
        fn = self._fn()
        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(503, {"error": "gateway disabled"})),
        ):
            result = fn(tmp_path, ["python", "x.py"])
        assert result is None

    def test_returns_none_on_transport_failure(self, tmp_path):
        fn = self._fn()
        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(None, None)),
        ):
            result = fn(tmp_path, ["python", "x.py"])
        assert result is None

    def test_returns_none_on_401(self, tmp_path):
        fn = self._fn()
        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(401, {"error": "unauthorized"})),
        ):
            result = fn(tmp_path, ["python", "x.py"])
        assert result is None

    def test_root_none_not_sent_as_string_none(self, tmp_path):
        """FIX 3: root=None must not appear as the literal string 'None'."""
        fn = self._fn()
        captured = {}

        def fake_post(base, path, payload, timeout, headers=None):
            captured["payload"] = payload
            return 201, {"run_id": "r1", "status": "submitted"}

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_post", side_effect=fake_post),
        ):
            fn(None, ["python", "x.py"])

        assert "root" not in captured.get("payload", {}), (
            "root=None should not be included in the payload"
        )


# ---------------------------------------------------------------------------
# _await_daemon_run unit tests (FIX 1 / FIX 2)
# ---------------------------------------------------------------------------

class TestAwaitDaemonRun:
    def _fn(self):
        from research_os.server.handlers.research_exec import _await_daemon_run
        return _await_daemon_run

    def test_returns_stdout_on_terminal_success(self, tmp_path):
        fn = self._fn()
        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value="tok"),
            patch("research_os.server.daemon_bridge.http_get",
                  side_effect=_fake_http_get_terminal),
        ):
            result = fn(tmp_path, "r1", timeout=10)

        assert result is not None
        assert result["status"] == "success"
        assert result["exit_code"] == 0
        assert result["run_id"] == "r1"
        assert result["journaled"] is True
        assert "hello from daemon" in result["stdout"]

    def test_returns_running_when_timeout_expires(self, tmp_path):
        """FIX 2: polling respects the user timeout — does not hang."""
        fn = self._fn()

        # Always return "running" status — simulates a slow job.
        def _always_running(base, path, timeout=2.0, headers=None):
            return 200, {"status": "running", "log": []}

        import time as _time
        start = _time.monotonic()
        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_get",
                  side_effect=_always_running),
        ):
            # Very short timeout so the test doesn't actually wait.
            result = fn(tmp_path, "r-slow", timeout=0.3, poll=0.05)

        elapsed = _time.monotonic() - start
        assert result is not None
        assert result["status"] == "running"
        assert result["run_id"] == "r-slow"
        # Must return within a small multiple of timeout (not hang).
        assert elapsed < 3.0, f"_await_daemon_run hung for {elapsed:.1f}s"

    def test_returns_none_when_daemon_vanishes(self, tmp_path):
        """If http_get returns (None, None), degrade → None."""
        fn = self._fn()
        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_get",
                  side_effect=_fake_http_get_none),
        ):
            result = fn(tmp_path, "r-gone", timeout=5)
        assert result is None

    def test_exit_code_from_failed_run(self, tmp_path):
        fn = self._fn()

        def _failed_manifest(base, path, timeout=2.0, headers=None):
            return 200, dict(_FAILED_MANIFEST)

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_get",
                  side_effect=_failed_manifest),
        ):
            result = fn(tmp_path, "r-fail", timeout=10)

        assert result is not None
        assert result["status"] == "error"
        assert result["exit_code"] == 1


# ---------------------------------------------------------------------------
# tool_python_exec — synchronous contract (FIX 1)
# ---------------------------------------------------------------------------

class TestPythonExecDaemonRouting:
    def _call(self, root, script_path_str, timeout=600):
        from research_os.server.handlers.research_exec import _handle_tool_python_exec
        return _handle_tool_python_exec(
            "tool_python_exec",
            {"script_path": script_path_str, "timeout": timeout},
            root,
        )

    def test_no_daemon_runs_natively_NO_warning(self, tmp_path):
        """FIX 7: no daemon configured → native exec, NO warning."""
        root = _make_root(tmp_path)
        _write_py_script(root, "hello.py")

        with patch("research_os.server.daemon_bridge.daemon_base_url",
                   return_value=None):
            result = self._call(root, "hello.py")

        d = _parsed(result)
        assert d["status"] == "success"
        # FIX 7: no daemon → no spurious warning
        assert "warning" not in d.get("payload", {}), (
            "Warning should NOT appear when no daemon is configured"
        )

    def test_fake_daemon_returns_stdout_not_native(self, tmp_path):
        """FIX 1: daemon path polls to completion and returns stdout."""
        root = _make_root(tmp_path)
        marker = root / "marker_was_created.txt"
        _write_py_script(root, "will_error.py",
                         content=f"open({str(marker)!r}, 'w').close()\n")

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value="tok"),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(201, {"run_id": "abc123", "status": "submitted"})),
            patch("research_os.server.daemon_bridge.http_get",
                  side_effect=_fake_http_get_terminal),
        ):
            result = self._call(root, "will_error.py")

        d = _parsed(result)
        assert d["status"] == "success"
        # run_id is present in the awaited payload.
        assert d["payload"].get("run_id") == "abc123"
        assert d["payload"].get("journaled") is True
        # stdout is present (from the journaled log).
        assert "stdout" in d["payload"]
        assert "hello from daemon" in d["payload"]["stdout"]
        # Native path was NOT executed (marker absent).
        assert not marker.exists(), "Native subprocess ran despite daemon accepting the run"

    def test_503_degrades_to_native_with_warning(self, tmp_path):
        """Daemon present but 503 → native + warning (daemon_configured=True)."""
        root = _make_root(tmp_path)
        _write_py_script(root, "hello.py")

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(503, {"error": "gateway off"})),
        ):
            result = self._call(root, "hello.py")

        d = _parsed(result)
        assert d["status"] == "success"
        # FIX 7: warning IS present because daemon was configured but fell back.
        assert "warning" in d.get("payload", {}), (
            "Warning should appear when daemon is configured but run fell back"
        )
        assert "natively" in d["payload"]["warning"]

    def test_poll_failure_degrades_to_native_with_warning(self, tmp_path):
        """Submit 201, then http_get vanishes → degrade to native + warning."""
        root = _make_root(tmp_path)
        _write_py_script(root, "hello.py")

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value="tok"),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(201, {"run_id": "r-lost", "status": "submitted"})),
            patch("research_os.server.daemon_bridge.http_get",
                  side_effect=_fake_http_get_none),
        ):
            result = self._call(root, "hello.py")

        d = _parsed(result)
        assert d["status"] == "success"
        assert "warning" in d.get("payload", {})


# ---------------------------------------------------------------------------
# tool_bash_exec (via _handle_tool_script_exec) — synchronous contract
# ---------------------------------------------------------------------------

class TestBashExecDaemonRouting:
    def _call(self, root, script_path_str, timeout=600):
        from research_os.server.handlers.research_exec import _handle_tool_bash_exec
        return _handle_tool_bash_exec(
            "tool_bash_exec",
            {"script_path": script_path_str, "timeout": timeout},
            root,
        )

    def test_no_daemon_runs_natively_NO_warning(self, tmp_path):
        """FIX 7: no daemon → native, NO warning."""
        root = _make_root(tmp_path)
        _write_bash_script(root, "run.sh")

        with patch("research_os.server.daemon_bridge.daemon_base_url",
                   return_value=None):
            result = self._call(root, "run.sh")

        d = _parsed(result)
        assert d["status"] == "success"
        assert "warning" not in d.get("payload", {})

    def test_fake_daemon_returns_stdout_not_native(self, tmp_path):
        """FIX 1: daemon polls to completion, returns stdout, no native exec."""
        root = _make_root(tmp_path)
        marker = root / "bash_marker.txt"
        _write_bash_script(root, "mark.sh",
                           content=f"#!/bin/bash\ntouch {marker}\n")

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value="tok"),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(201, {"run_id": "bash-run-1", "status": "submitted"})),
            patch("research_os.server.daemon_bridge.http_get",
                  side_effect=_fake_http_get_terminal),
        ):
            result = self._call(root, "mark.sh")

        d = _parsed(result)
        assert d["status"] == "success"
        assert d["payload"].get("run_id") == "bash-run-1"
        assert d["payload"].get("journaled") is True
        assert "stdout" in d["payload"]
        assert not marker.exists(), "Native bash ran despite daemon accepting run"

    def test_503_degrades_to_native_with_warning(self, tmp_path):
        """Daemon present but 503 → native + warning."""
        root = _make_root(tmp_path)
        _write_bash_script(root, "run.sh")

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(503, {})),
        ):
            result = self._call(root, "run.sh")

        d = _parsed(result)
        assert d["status"] == "success"
        assert "warning" in d.get("payload", {})


# ---------------------------------------------------------------------------
# tool_task (op=run) — fire-and-forget, no poll (FIX 1 KEEP AS-IS)
# ---------------------------------------------------------------------------

class TestTaskRunDaemonRouting:
    def _call(self, root, command):
        from research_os.server.handlers.research_exec import _handle_tool_task_run
        return _handle_tool_task_run(
            "tool_task",
            {"command": command, "description": "test"},
            root,
        )

    def test_no_daemon_runs_natively_NO_warning(self, tmp_path):
        """FIX 7: no daemon → native, NO warning."""
        root = _make_root(tmp_path)

        with patch("research_os.server.daemon_bridge.daemon_base_url",
                   return_value=None):
            result = self._call(root, ["sleep", "0"])

        d = _parsed(result)
        assert d["status"] == "success"
        assert "warning" not in d.get("payload", {})

    def test_fake_daemon_returns_run_id_fire_and_forget(self, tmp_path):
        """tool_task op=run stays fire-and-forget — returns run_id, no poll."""
        root = _make_root(tmp_path)
        marker = root / "task_marker.txt"

        http_get_called = []

        def _recording_http_get(base, path, timeout=2.0, headers=None):
            http_get_called.append(path)
            return 200, _TERMINAL_MANIFEST

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value="tok"),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(201, {"run_id": "task-run-1", "status": "submitted"})),
            patch("research_os.server.daemon_bridge.http_get",
                  side_effect=_recording_http_get),
        ):
            result = self._call(root, f"touch {marker}")

        d = _parsed(result)
        assert d["status"] == "success"
        assert d["payload"].get("run_id") == "task-run-1"
        assert d["payload"].get("journaled") is True
        # Native task_run was NOT called (marker absent).
        assert not marker.exists(), "Native task_run ran despite daemon accepting run"
        # http_get was NOT called — fire-and-forget, no polling.
        assert len(http_get_called) == 0, (
            f"tool_task op=run should NOT poll (http_get was called: {http_get_called})"
        )

    def test_503_degrades_to_native_with_warning(self, tmp_path):
        """Daemon present but 503 → native + warning."""
        root = _make_root(tmp_path)

        with (
            patch("research_os.server.daemon_bridge.daemon_base_url",
                  return_value="http://127.0.0.1:9999"),
            patch("research_os.server.daemon_bridge.daemon_bearer",
                  return_value=None),
            patch("research_os.server.daemon_bridge.http_post",
                  return_value=(503, {})),
        ):
            result = self._call(root, ["sleep", "0"])

        d = _parsed(result)
        assert d["status"] == "success"
        assert "warning" in d.get("payload", {})


# ---------------------------------------------------------------------------
# daemon_bridge additions: http_post headers + daemon_bearer + http_get sig
# ---------------------------------------------------------------------------

class TestDaemonBridgeExtensions:
    def test_daemon_bearer_returns_none_when_no_descriptor(self, tmp_path):
        from research_os.server import daemon_bridge as db
        assert db.daemon_bearer(tmp_path) is None

    def test_daemon_bearer_returns_none_when_env_not_set(self, tmp_path, monkeypatch):
        from research_os.server import daemon_bridge as db
        monkeypatch.delenv("RESEARCH_OS_DAEMON_TOKEN", raising=False)
        monkeypatch.delenv("RESEARCH_OS_GATEWAY_TOKEN", raising=False)
        assert db.daemon_bearer(tmp_path) is None

    def test_daemon_bearer_returns_token_from_default_env(self, tmp_path, monkeypatch):
        from research_os.server import daemon_bridge as db
        monkeypatch.setenv("RESEARCH_OS_DAEMON_TOKEN", "my-secret-token")
        token = db.daemon_bearer(tmp_path)
        assert token == "my-secret-token"

    def test_daemon_bearer_uses_descriptor_env_name(self, tmp_path, monkeypatch):
        from research_os.server import daemon_bridge as db
        p = tmp_path / ".os_state" / "daemon.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"pid": 1, "auth_token_env": "MY_CUSTOM_TOKEN"}),
            encoding="utf-8",
        )
        monkeypatch.setenv("MY_CUSTOM_TOKEN", "custom-tok")
        monkeypatch.delenv("RESEARCH_OS_DAEMON_TOKEN", raising=False)
        monkeypatch.delenv("RESEARCH_OS_GATEWAY_TOKEN", raising=False)
        assert db.daemon_bearer(tmp_path) == "custom-tok"

    def test_http_post_with_no_headers(self):
        """http_post with headers=None must accept None without raising."""
        from research_os.server import daemon_bridge as db
        status, body = db.http_post(
            "http://127.0.0.1:1", "/v1/runs", {}, timeout=0.1, headers=None
        )
        assert status is None
        assert body is None

    def test_http_post_with_auth_header(self):
        """headers dict is accepted; transport failure still → (None, None)."""
        from research_os.server import daemon_bridge as db
        status, body = db.http_post(
            "http://127.0.0.1:1", "/v1/runs", {}, timeout=0.1,
            headers={"Authorization": "Bearer xyz"},
        )
        assert status is None
        assert body is None

    def test_http_get_returns_tuple_on_unreachable(self):
        """FIX: http_get returns (None, None) on unreachable, not just None."""
        from research_os.server import daemon_bridge as db
        status, body = db.http_get("http://127.0.0.1:1", "/v1/orient", timeout=0.2)
        assert status is None
        assert body is None

    def test_http_get_accepts_headers_kwarg(self):
        """http_get must accept an optional headers kwarg without raising."""
        from research_os.server import daemon_bridge as db
        # No server listening → (None, None); just confirm signature.
        status, body = db.http_get(
            "http://127.0.0.1:1", "/v1/runs/r1?log=1",
            timeout=0.1,
            headers={"Authorization": "Bearer tok"},
        )
        assert status is None
        assert body is None
