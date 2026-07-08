"""Tests for `research-os route` — terminal-facing protocol router preview.

Exercises the CLI wrapper around ``route_request``: human-readable output,
``--json`` mode, the empty-prompt guard, and that it never persists an
active plan (read-only preview).
"""
from __future__ import annotations

import json

from research_os import cli
from research_os.tools.actions.router import route_request


def test_route_request_engine_returns_decision(tmp_path):
    """The underlying engine resolves a clear prompt to a protocol."""
    res = route_request("draft the methods section", tmp_path, persist_plan=False)
    assert res["status"] == "success"
    assert res.get("primary_protocol")
    assert res.get("resolved_level") in (0, 2, 3)


def test_route_cli_human_output(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = _run_route("fit a mixed effects model to my data", no_color=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Route for:" in out
    assert "intent" in out
    # A protocol or shortcut line should appear.
    assert ("protocol" in out) or ("shortcut" in out)


def test_route_cli_json_output(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = _run_route("draft the methods section", json_out=True, no_color=True)
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["status"] == "success"
    assert "primary_protocol" in payload
    assert "decomposition" in payload


def test_route_cli_empty_prompt_guard(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = _run_route("   ", no_color=True)
    assert rc == 2


def test_route_cli_is_read_only(capsys, tmp_path, monkeypatch):
    """Preview must not write an active plan, even for a complex prompt."""
    monkeypatch.chdir(tmp_path)
    _run_route(
        "design and run a full multi-factor experiment with analysis and writeup",
        no_color=True,
    )
    # No active plan persisted anywhere under the cwd.
    assert not list(tmp_path.rglob("active_plan.json"))


def test_route_in_subcommands_for_completion():
    assert "route" in cli.SUBCOMMANDS_FOR_COMPLETION
    assert "hermes" in cli.SUBCOMMANDS_FOR_COMPLETION


def _run_route(prompt: str, *, json_out: bool = False, no_color: bool = False) -> int:
    """Invoke cmd_route with a hand-built args namespace."""
    import argparse

    args = argparse.Namespace(
        command="route",
        prompt=prompt,
        json=json_out,
        no_color=no_color,
    )
    return cli.cmd_route(args)
