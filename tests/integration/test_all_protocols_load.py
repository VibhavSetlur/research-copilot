"""Smoke test: every protocol on disk loads cleanly via the loader."""

from pathlib import Path

import pytest

from research_os.tools.actions.protocol import load_protocol


PROTOCOLS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "src" / "research_os" / "protocols"
)


def _all_protocol_paths():
    for p in sorted(PROTOCOLS_DIR.rglob("*.yaml")):
        if "light" in p.parts:
            continue
        # Skip underscore-prefixed special files (router index, etc.)
        if p.name.startswith("_"):
            continue
        yield p


@pytest.mark.parametrize("protocol_path", list(_all_protocol_paths()))
def test_protocol_loads_and_has_required_fields(protocol_path):
    name = protocol_path.relative_to(PROTOCOLS_DIR).with_suffix("").as_posix()
    loaded = load_protocol(name)
    assert loaded is not None
    assert "id" in loaded
    assert "steps" in loaded and isinstance(loaded["steps"], list)
    assert len(loaded["steps"]) >= 1
    # The loader injects protocol_completion automatically.
    assert any(s.get("id") == "protocol_completion" for s in loaded["steps"])


def test_no_light_folder():
    light = PROTOCOLS_DIR / "light"
    assert not light.exists(), "light/ folder must not exist (merged into single source)"


def test_all_protocols_have_no_dot_tool_calls():
    """Protocols should use underscore tool names. Dot notation works via the
    dispatcher alias, but new protocols should not introduce more."""
    broken_patterns = [
        "sys_state.get", "sys_file.read", "sys_file.write", "sys_path.create",
        "sys_path.abandon", "sys_checkpoint.create",
        "mem_analysis.log", "mem_methods.append", "mem_decision.log",
        "tool_search.web", "tool_search.semantic_scholar",
        "tool_audit.synthesis", "tool_python.exec",
    ]
    for p in _all_protocol_paths():
        text = p.read_text()
        for pat in broken_patterns:
            assert pat not in text, f"{p.name} uses legacy dot-notation `{pat}`"
