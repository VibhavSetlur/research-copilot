"""W17 — chmod 600 + tui.secret + doctor world-readable warning.

Covers three paired security guarantees:

1. ``init_config`` writes ``inputs/researcher_config.yaml`` with mode
   ``0o600`` so freshly captured API keys aren't group/world-readable.
2. ``save_profile`` writes ``~/.config/research-os/profile.yaml`` with
   mode ``0o600`` for the same reason.
3. ``check_config_perms`` (the doctor) warns when the file's mode bits
   leak owner-only restriction (``& 0o077 != 0``).
4. ``tui.secret`` exists and behaves like a single-line input wrapper
   around ``getpass`` so wizard Step 6 never echoes pasted API keys.
"""

from __future__ import annotations

import os

import pytest

from research_os import tui
from research_os.cli_doctor import check_config_perms
from research_os.tools.actions.state.config import (
    init_config,
    profile_path,
    save_profile,
)


pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="chmod / mode-bit semantics differ on Windows; W17 wraps "
    "chmod in try/except for compat but the assertion only makes "
    "sense on POSIX.",
)


# ---------------------------------------------------------------------------
# 1 + 2. chmod 600 on writes
# ---------------------------------------------------------------------------


class TestResearcherConfigPerms:
    def test_init_config_sets_owner_only_mode(self, tmp_path):
        init_config(tmp_path)
        cfg = tmp_path / "inputs" / "researcher_config.yaml"
        assert cfg.exists()
        mode = cfg.stat().st_mode & 0o777
        assert mode == 0o600, (
            f"researcher_config.yaml mode is {oct(mode)} — should be 0o600 "
            f"so group/other can't read pasted API keys."
        )

    def test_init_config_perms_survive_overrides_pass(self, tmp_path):
        # First init creates the file with chmod 600. Second init applies
        # overrides via _dump_config_roundtrip — chmod should still hold.
        init_config(tmp_path)
        init_config(tmp_path, overrides={"api_keys": {"openai": "sk-test"}})
        cfg = tmp_path / "inputs" / "researcher_config.yaml"
        mode = cfg.stat().st_mode & 0o777
        assert mode == 0o600


class TestProfilePerms:
    def test_save_profile_sets_owner_only_mode(self, tmp_path, monkeypatch):
        # Redirect ~/.config to tmp_path so we don't clobber the dev's
        # real profile.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        res = save_profile({"researcher": {"name": "Test User"}})
        assert res["status"] == "success"
        p = profile_path()
        assert p.exists()
        mode = p.stat().st_mode & 0o777
        assert mode == 0o600


# ---------------------------------------------------------------------------
# 3. Doctor check_config_perms warns on world-readable file
# ---------------------------------------------------------------------------


class TestCheckConfigPerms:
    def test_passes_when_mode_is_600(self, tmp_path):
        init_config(tmp_path)
        status, msg, _hint = check_config_perms(workspace=tmp_path)
        assert status == "pass", msg

    def test_warns_when_world_readable(self, tmp_path):
        init_config(tmp_path)
        cfg = tmp_path / "inputs" / "researcher_config.yaml"
        # Simulate a researcher who chmod'd it to default-umask perms.
        os.chmod(cfg, 0o640 | 0o004)
        expected_mode = oct(cfg.stat().st_mode & 0o777)[2:]
        status, msg, hint = check_config_perms(workspace=tmp_path)
        assert status == "warn"
        assert expected_mode in msg or "readable" in msg
        assert hint and "chmod 600" in hint

    def test_passes_when_no_workspace(self):
        status, msg, _hint = check_config_perms(workspace=None)
        assert status == "pass"

    def test_passes_when_no_config_file(self, tmp_path):
        # Fresh tmp dir, no init_config call.
        status, msg, _hint = check_config_perms(workspace=tmp_path)
        assert status == "pass"


# ---------------------------------------------------------------------------
# 4. tui.secret — masked input wrapper
# ---------------------------------------------------------------------------


class TestTuiSecret:
    def test_secret_is_exported(self):
        assert hasattr(tui, "secret")
        assert callable(tui.secret)

    def test_fallback_uses_getpass_not_input(self, monkeypatch, capsys):
        # Force fallback path (non-TTY).
        monkeypatch.setattr(tui, "raw_supported", lambda: False)

        captured_prompts: list[str] = []

        def fake_getpass(prompt: str = "") -> str:
            captured_prompts.append(prompt)
            return "sk-secret-123"

        monkeypatch.setattr("getpass.getpass", fake_getpass)
        # If the implementation accidentally called input() instead of
        # getpass, this would echo to stdin and fail the test.
        monkeypatch.setattr("builtins.input", lambda _="": pytest.fail(
            "tui.secret should not call input() — it echoes the secret."))

        val = tui.secret("OpenAI key", allow_empty=True)
        assert val == "sk-secret-123"
        assert captured_prompts, "tui.secret fallback should call getpass.getpass"
        # The captured value MUST NOT appear in stdout (getpass is silent).
        out = capsys.readouterr().out
        assert "sk-secret-123" not in out

    def test_fallback_strips_whitespace(self, monkeypatch):
        monkeypatch.setattr(tui, "raw_supported", lambda: False)
        monkeypatch.setattr("getpass.getpass", lambda prompt="": "  sk-abc  ")
        val = tui.secret("k", allow_empty=True)
        assert val == "sk-abc"

    def test_fallback_allows_empty_when_flag_set(self, monkeypatch):
        monkeypatch.setattr(tui, "raw_supported", lambda: False)
        monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
        # allow_empty=True → returning empty string is fine, no loop.
        val = tui.secret("k", allow_empty=True)
        assert val == ""
