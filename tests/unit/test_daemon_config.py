"""Unit tests for the v4 daemon config layer (research_os.daemon.config).

Covers default values, the localhost-only security default, validation,
and the resolution precedence: defaults -> project file -> env ->
explicit overrides.
"""
from __future__ import annotations

import pytest

from research_os.daemon.config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DaemonConfig,
    _as_bool,
)


def test_defaults_are_localhost_only():
    cfg = DaemonConfig()
    assert cfg.host == DEFAULT_HOST == "127.0.0.1"
    assert cfg.port == DEFAULT_PORT
    assert cfg.auth_token_env == "RESEARCH_OS_DAEMON_TOKEN"
    assert cfg.enable_dashboard is False
    assert cfg.sandbox_mode == "auto"
    assert cfg.base_url == f"http://127.0.0.1:{DEFAULT_PORT}"


def test_invalid_sandbox_mode_rejected():
    with pytest.raises(ValueError):
        DaemonConfig(sandbox_mode="rocket")


@pytest.mark.parametrize("port", [0, -1, 65536, 99999])
def test_invalid_port_rejected(port):
    with pytest.raises(ValueError):
        DaemonConfig(port=port)


def test_with_overrides_ignores_none():
    cfg = DaemonConfig()
    same = cfg.with_overrides(host=None, port=None)
    assert same.host == cfg.host and same.port == cfg.port
    changed = cfg.with_overrides(port=9001)
    assert changed.port == 9001
    # original untouched (frozen / copy semantics)
    assert cfg.port == DEFAULT_PORT


def test_resolve_no_root_uses_defaults_then_overrides():
    cfg = DaemonConfig.resolve(root=None, port=1234)
    assert cfg.port == 1234
    assert cfg.auth_token_env == "RESEARCH_OS_DAEMON_TOKEN"


def test_env_resolution(monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_DAEMON_PORT", "5555")
    monkeypatch.setenv("RESEARCH_OS_DAEMON_SANDBOX", "native")
    cfg = DaemonConfig.resolve(root=None)
    assert cfg.port == 5555
    assert cfg.sandbox_mode == "native"


def test_explicit_override_beats_env(monkeypatch):
    monkeypatch.setenv("RESEARCH_OS_DAEMON_PORT", "5555")
    cfg = DaemonConfig.resolve(root=None, port=7777)
    assert cfg.port == 7777


def test_project_file_resolution(tmp_path):
    import yaml

    inp = tmp_path / "inputs"
    inp.mkdir()
    (inp / "researcher_config.yaml").write_text(
        yaml.safe_dump({"daemon": {"port": 8181, "sandbox_mode": "off"}})
    )
    cfg = DaemonConfig.resolve(root=tmp_path)
    assert cfg.port == 8181
    assert cfg.sandbox_mode == "off"


def test_env_beats_project_file(tmp_path, monkeypatch):
    import yaml

    inp = tmp_path / "inputs"
    inp.mkdir()
    (inp / "researcher_config.yaml").write_text(
        yaml.safe_dump({"daemon": {"port": 8181}})
    )
    monkeypatch.setenv("RESEARCH_OS_DAEMON_PORT", "9090")
    cfg = DaemonConfig.resolve(root=tmp_path)
    assert cfg.port == 9090


def test_malformed_project_file_falls_back_to_defaults(tmp_path):
    (tmp_path / "researcher_config.yaml").write_text("{not: valid: yaml: [")
    cfg = DaemonConfig.resolve(root=tmp_path)
    assert cfg.port == DEFAULT_PORT  # did not crash


@pytest.mark.parametrize(
    "raw,expected",
    [
        (True, True), (False, False),
        ("1", True), ("true", True), ("YES", True), ("on", True),
        ("0", False), ("false", False), ("no", False), ("", False),
    ],
)
def test_as_bool(raw, expected):
    assert _as_bool(raw) is expected
