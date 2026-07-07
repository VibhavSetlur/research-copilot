"""4.0.2: dispatch-boundary robustness — str root coercion + typed input errors."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from research_os.project_ops import scaffold_minimal_workspace
from research_os.server.dispatch import _handle_tool_call


def _proj() -> Path:
    root = Path(tempfile.mkdtemp()) / "p"
    scaffold_minimal_workspace(root, "T", mode="analysis")
    return root


def test_str_root_does_not_crash_action_functions():
    """The daemon can pass a str root; dispatch must coerce it to Path
    so the ~45 functions doing `root / '...'` don't crash."""
    root = _proj()
    r = _handle_tool_call("tool_audit", {"scope": "project", "dimension": "coherence"}, str(root))
    d = json.loads(r[0].text)
    assert "status" in d  # no unhandled TypeError, real envelope returned


def test_tool_route_non_string_prompt_clean_error():
    root = _proj()
    r = _handle_tool_call("tool_route", {"prompt": 123}, root)
    assert "must be a string" in r[0].text


def test_tool_audit_non_string_scope_clean_error():
    root = _proj()
    r = _handle_tool_call("tool_audit", {"scope": ["step"], "dimension": "x"}, root)
    assert "must be strings" in r[0].text
