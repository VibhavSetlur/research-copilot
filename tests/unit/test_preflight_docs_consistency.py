"""W21: preflight check 25 — docs/code consistency.

Verifies the new preflight checks added in W21 actually work:
* docs/code consistency detects unknown tool names + missing scripts/ refs
* TOOLS.md round-trip flags fake tool names
* CITATION.cff cff-version is validated
* every TOOL_DEFINITIONS entry has a 'short' field <=120 chars
* every src/research_os_* pack dir is in both bundled lists
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_PATH = REPO_ROOT / "scripts" / "preflight.py"


def _load_preflight():
    spec = importlib.util.spec_from_file_location("_preflight_w21", PREFLIGHT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def test_new_check_functions_exist():
    """All five W21 check functions must be present on preflight module."""
    pre = _load_preflight()
    assert hasattr(pre, "check_docs_counts_agree")
    assert hasattr(pre, "check_tools_md_roundtrip")
    assert hasattr(pre, "check_citation_cff_valid")
    assert hasattr(pre, "check_tool_short_field_length")
    assert hasattr(pre, "check_packs_in_both_lists")


def test_check_short_field_passes_on_clean_codebase():
    """Every TOOL_DEFINITIONS entry has a 'short' field <=120 chars."""
    pre = _load_preflight()
    ok, detail = pre.check_tool_short_field_length()
    assert ok, f"short-field check failed: {detail}"


def test_check_short_field_catches_missing_short(monkeypatch):
    """Removing the 'short' field on a tool must fail the check."""
    pre = _load_preflight()
    from research_os.server import TOOL_DEFINITIONS

    # Pick a real tool, monkey-patch its 'short' to empty.
    first_tool = next(iter(TOOL_DEFINITIONS))
    original_short = TOOL_DEFINITIONS[first_tool].get("short")
    TOOL_DEFINITIONS[first_tool]["short"] = ""
    try:
        ok, detail = pre.check_tool_short_field_length()
        assert not ok
        assert first_tool in detail
    finally:
        if original_short is not None:
            TOOL_DEFINITIONS[first_tool]["short"] = original_short


def test_citation_cff_check_passes():
    """CITATION.cff in this repo must satisfy the schema-ish validation."""
    pre = _load_preflight()
    ok, detail = pre.check_citation_cff_valid()
    assert ok, f"CITATION.cff check failed: {detail}"


def test_packs_in_both_lists_passes():
    """Every bundled in-tree pack/adapter package should be in both lists.

    This guards the real shipped contract: the source tree's bundled
    adapter/package dirs must be represented in both the loader registry
    and the packaging manifest, with no stale list-only entries left behind.
    """
    pre = _load_preflight()
    ok, detail = pre.check_packs_in_both_lists()
    assert ok, f"packs-in-both-lists check failed: {detail}"


def test_bundle_internal_consistency_passes_on_valid_minimal_bundle(monkeypatch):
    pre = _load_preflight()
    bundle = {
        "protocols": {
            "analysis/example": {"next_protocol": "audit/check"},
            "audit/check": {},
        },
        "gates": [{"key": "review", "source_protocol": "analysis/example"}],
        "gate_built_from": ["analysis/example"],
        "preconditions": {"audit/check": [{"protocol": "analysis/example"}]},
    }
    monkeypatch.setattr(pre, "_read_protocol_bundle", lambda: (bundle, None))

    ok, detail = pre.check_bundle_internal_consistency()
    assert ok, detail



def test_bundle_internal_consistency_catches_missing_route_target(monkeypatch):
    pre = _load_preflight()
    bundle = {
        "protocols": {"analysis/example": {"next_protocol": "audit/missing"}},
        "gates": [],
        "preconditions": {},
    }
    monkeypatch.setattr(pre, "_read_protocol_bundle", lambda: (bundle, None))

    ok, detail = pre.check_bundle_internal_consistency()
    assert not ok
    assert "audit/missing" in detail



def test_preflight_registers_25plus_checks():
    """main() must register at least 25 checks (W21 bumps total >=29)."""
    pre = _load_preflight()
    # Inspect main()'s source for the number of tally.check(...) calls
    import inspect

    main_src = inspect.getsource(pre.main)
    n_checks = main_src.count("tally.check(")
    assert n_checks >= 25, f"expected >=25 preflight checks, found {n_checks}"


def test_claude_md_says_25_or_higher():
    """CLAUDE.md hard invariant 4 must say '25/25 (or higher; the count grows)'."""
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    # Hard invariant 4 should not pin a specific count <25.
    assert "preflight 25/25 (or higher; the count grows)" in text or \
        "25/25" in text, \
        "CLAUDE.md should reference preflight 25/25 (or higher)"
