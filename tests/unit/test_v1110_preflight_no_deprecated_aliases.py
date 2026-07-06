"""Preflight check: ``check_no_deprecated_aliases_in_protocols``.

v1.11.0 adds a 22nd preflight check that scans every shipped protocol
YAML for references to deprecated alias names (the legacy pre-consolidation
tool names declared in ``server._DEPRECATED_ALIASES``). Shipping a
protocol scaffold that still calls ``tool_failure_check`` instead of
``tool_lessons(operation='failure_check')`` would cause the very first
invocation of that protocol to emit deprecation telemetry — bad first
impression and a maintenance trap.

These tests cover both directions:

* the live catalogue passes (no protocol references a deprecated name),
* a planted deprecated reference is caught,
* registry / index files prefixed with ``_`` are intentionally ignored
  (the router index may legitimately mention legacy names for routing
  context).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_PATH = REPO_ROOT / "scripts" / "preflight.py"


def _load_preflight():
    spec = importlib.util.spec_from_file_location("preflight", PREFLIGHT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_function_exists():
    mod = _load_preflight()
    assert hasattr(mod, "check_no_deprecated_aliases_in_protocols")
    assert callable(mod.check_no_deprecated_aliases_in_protocols)


def test_live_catalogue_clean():
    """Every shipped protocol must be free of deprecated alias refs."""
    mod = _load_preflight()
    ok, msg = mod.check_no_deprecated_aliases_in_protocols()
    assert ok, msg


def test_planted_deprecated_ref_is_caught(tmp_path, monkeypatch):
    """A protocol YAML referencing a currently-deprecated alias must fail.

    Note: tool_search_pubmed was hard-removed in phase-14a (v2.0.0), so we
    plant a Phase-9-era alias that is still in _DEPRECATED_ALIASES.
    """
    mod = _load_preflight()
    cat = tmp_path / "literature"
    cat.mkdir()
    (cat / "bad.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "literature/bad",
                "name": "bad",
                "version": "2.0.0",
                "steps": [
                    {
                        "id": "search",
                        "description": "Call tool_web_scrape before retry.",
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(mod, "PROTOCOLS_DIR", tmp_path)
    ok, msg = mod.check_no_deprecated_aliases_in_protocols()
    assert not ok
    assert "tool_web_scrape" in msg
    assert "literature/bad" in msg


def test_underscore_prefixed_files_are_skipped(tmp_path, monkeypatch):
    """Files like ``_router_index.yaml`` are not protocol scaffolds and
    are allowed to mention deprecated names for routing context."""
    mod = _load_preflight()
    (tmp_path / "_router_index.yaml").write_text(
        "# mentions tool_failure_check for trigger context only\n"
        "protocols: {}\n"
    )
    monkeypatch.setattr(mod, "PROTOCOLS_DIR", tmp_path)
    ok, _ = mod.check_no_deprecated_aliases_in_protocols()
    assert ok


def test_check_is_registered_in_main(tmp_path):
    """The new check must be wired into ``main()``'s tally so the count
    moves from 21 → 22. We don't run ``main()`` (it would re-run the full
    suite); instead we read the source and confirm the check name appears
    on a ``tally.check(...)`` line."""
    text = PREFLIGHT_PATH.read_text()
    assert "check_no_deprecated_aliases_in_protocols" in text
    # The new check must appear in main() as a tally.check(...) call,
    # not just as a function definition.
    main_section = text.split("def main()", 1)[1]
    assert "check_no_deprecated_aliases_in_protocols" in main_section


def test_every_deprecated_alias_resolves_to_real_handler():
    """Sanity check on the source-of-truth set: every name we forbid in
    protocols must still resolve to a real tool via the alias table.
    This guards against the deprecation list drifting out of sync with
    the consolidation map."""
    from research_os.server import (
        _ALIASES,
        _DEPRECATED_ALIASES,
        _HANDLERS,
        _resolve_tool_name,
    )

    bad: list[str] = []
    for name in _DEPRECATED_ALIASES:
        canonical = _resolve_tool_name(name)
        if canonical == name:
            bad.append(f"{name}: no alias mapping")
        elif canonical not in _HANDLERS:
            bad.append(f"{name} -> {canonical}: target missing from _HANDLERS")
    assert not bad, bad
    # And every deprecated name must in fact be in the alias map.
    missing = sorted(_DEPRECATED_ALIASES - set(_ALIASES))
    assert not missing, f"deprecated names not in _ALIASES: {missing}"
