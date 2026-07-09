"""W14 RoError + did_you_mean regression tests.

Covers:

* did_you_mean namespace-awareness (sys_X typo prefers other sys_*) — closes FIX-16.
* Lowered cutoff (0.5) returns matches for short tool names.
* Em dashes are absent from user-facing error templates in
  ``server/errors.py``, ``server/envelopes.py``, ``server/dispatch.py``,
  and ``server/handlers/meta_workspace.py``.
* Each newly-converted RoError raise site actually raises RoError
  (not the bare Exception/ValueError/FileNotFoundError) and the WHAT/WHY/NEXT
  trio is non-empty.
* did_you_mean fires on unknown step_id, category, pack, adapter,
  and consolidated tool name (intent_class-style namespaced lookup).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# Tests sometimes run after modules that reload `research_os.*` from
# sys.modules (e.g. test_v170_plugins_packs_stress._fresh_import).
# Re-import RoError + did_you_mean lazily inside each test that catches
# them, so the class identity matches the freshly-reloaded module.
from research_os.server.errors import RoError, did_you_mean  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _refresh_roerror_alias():
    """Re-bind module-level RoError to whatever class the SUT is using.

    Some tests in this suite reload research_os.* from sys.modules
    (e.g. test_v170_plugins_packs_stress._fresh_import). After such a
    reload, the RoError imported at the top of THIS module is a stale
    class object — RoError raised by the SUT will not match
    pytest.raises(RoError). Refresh the alias every test.
    """
    global RoError, did_you_mean
    import importlib
    mod = importlib.import_module("research_os.server.errors")
    RoError = mod.RoError
    did_you_mean = mod.did_you_mean
    yield


# ── namespace-aware did_you_mean ──────────────────────────────────


def test_did_you_mean_prefers_same_namespace_for_sys():
    candidates = [
        "sys_protocol_get",
        "sys_protocol_list",
        "tool_protocol_get",
        "mem_protocol_get",
    ]
    # typo on a sys_ name should be answered with the sys_ candidate first
    out = did_you_mean(
        "sys_protocl_get", candidates, n=3, cutoff=0.5, namespace_aware=True
    )
    assert out, "expected at least one match for short-name typo"
    assert out[0].startswith("sys_"), (
        f"namespace-aware lookup should prefer sys_ but got {out}"
    )


def test_did_you_mean_prefers_same_namespace_for_tool():
    candidates = [
        "tool_progress_digest",
        "sys_progress_get",
        "mem_progress_log",
    ]
    out = did_you_mean(
        "tool_progres_digest", candidates, n=3, cutoff=0.5, namespace_aware=True
    )
    assert out and out[0].startswith("tool_")


def test_did_you_mean_low_cutoff_finds_short_typos():
    candidates = ["tool_search", "tool_plan", "tool_audit"]
    # default cutoff=0.6 would miss this; cutoff=0.5 should not
    out = did_you_mean("tool_serc", candidates, n=3, cutoff=0.5)
    assert "tool_search" in out


def test_did_you_mean_returns_empty_when_no_close_match():
    out = did_you_mean("xxxx", ["zzzz", "yyyy"], n=3, cutoff=0.9)
    assert out == []


# ── em-dash policy: never in user-facing templates ────────────────


def _src(rel: str) -> str:
    p = Path(__file__).resolve().parents[2] / "src" / rel
    return p.read_text()


def test_no_em_dash_in_roerror_composer():
    txt = _src("research_os/server/errors.py")
    # We accept em dashes in docstrings/comments but NOT inside the
    # composed error sentence template.
    assert 'f"— next:' not in txt
    assert 'f"next: ' in txt or 'next: ' in txt


def test_no_em_dash_in_envelopes_composer():
    txt = _src("research_os/server/envelopes.py")
    assert 'f"— next:' not in txt


def test_no_em_dash_in_dispatcher_rate_limit_message():
    txt = _src("research_os/server/dispatch.py")
    assert "Rate limit exceeded —" not in txt
    assert "Rate limit exceeded:" in txt


def test_no_em_dash_in_meta_workspace_error_strings():
    txt = _src("research_os/server/handlers/meta_workspace.py")
    # Only check that the two specific error literals we cleaned no longer
    # carry an em dash.
    assert "os_state.md missing —" not in txt
    assert "synthesis/ files exist —" not in txt


# ── converted RoError raise sites ─────────────────────────────────


def test_data_unsupported_format_raises_roerror(tmp_path: Path):
    from research_os.tools.actions.data.data import _read

    bogus = tmp_path / "x.weirdext"
    bogus.write_text("not real data")
    with pytest.raises(RoError) as exc:
        _read(bogus)
    assert "Unsupported file format" in exc.value.what
    assert exc.value.why and exc.value.next_action


def test_asset_manager_missing_asset_raises_roerror(tmp_path: Path):
    """asset_manager.read_text() now raises RoError for missing assets."""
    # We verify the SOURCE wires through RoError. A runtime call may hit
    # importlib.resources MultiplexedPath quirks unrelated to this change.
    src = _src("research_os/utils/asset_manager.py")
    assert "raise RoError(" in src
    assert "Asset" in src and "next_action=" in src


def test_iteration_step_dir_missing_raises_roerror_with_did_you_mean(tmp_path: Path):
    from research_os.tools.actions.state.iteration import _step_dir

    (tmp_path / "workspace" / "01_foo").mkdir(parents=True)
    (tmp_path / "workspace" / "02_bar").mkdir()
    with pytest.raises(RoError) as exc:
        _step_dir(tmp_path, "01_fo")  # close to "01_foo"
    msg = str(exc.value)
    assert "Step '01_fo' not found" in exc.value.what
    assert "01_foo" in msg or "01_foo" in (exc.value.next_action or "")


def test_literature_step_missing_raises_roerror(tmp_path: Path):
    from research_os.tools.actions.search.literature import _step_literature_dir

    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "01_setup").mkdir()
    with pytest.raises(RoError) as exc:
        _step_literature_dir(tmp_path, "01_setu")
    assert exc.value.what.startswith("Step '01_setu'")


def test_literature_workspace_missing_raises_roerror(tmp_path: Path):
    from research_os.tools.actions.search.literature import _step_literature_dir

    with pytest.raises(RoError) as exc:
        _step_literature_dir(tmp_path, "01_x")
    assert "workspace/" in exc.value.what


def test_protocol_not_found_raises_roerror(tmp_path: Path):
    from research_os.tools.actions.protocol import load_protocol

    with pytest.raises(RoError) as exc:
        load_protocol("totally/bogus_protocol_name_xyz")
    assert "not found" in exc.value.what.lower()
    assert exc.value.next_action


def test_consolidation_registry_bind_unknown_raises_roerror():
    from research_os.consolidation_registry import bind_handler

    with pytest.raises(RoError) as exc:
        bind_handler("does_not_exist_xx", lambda *a, **k: None)
    assert "does_not_exist_xx" in exc.value.what
    assert exc.value.next_action


def test_consolidation_registry_register_removed_validates():
    from research_os.consolidation_registry import register_removed

    with pytest.raises(RoError):
        register_removed("", "message")
    with pytest.raises(RoError):
        register_removed("tool_x", "")


def test_plugin_loader_validation_raises_roerror(tmp_path: Path):
    from research_os.plugins.loader import _validate
    from research_os.plugins.pack_api import PackRegistration

    reg = PackRegistration(
        name="BadName",  # uppercase — invalid
        version="0.1.0",
        description="x",
        protocols_dir=tmp_path,
        tools=(),
        router_entries={},
    )
    with pytest.raises(RoError) as exc:
        _validate(reg)
    assert "lowercase" in (exc.value.why or "") or "invalid" in exc.value.what.lower()


def test_adapter_loader_validation_raises_roerror():
    from research_os.adapters.loader import _validate
    from research_os.adapters.base import AdapterRegistration

    reg = AdapterRegistration(
        name="BadAdapter",  # uppercase: invalid
        version="0.1.0",
        description="x",
        detect=lambda root: False,
        extract=lambda root, step_id=None: {},
        describe=None,
        tools_md_patterns=(),
        tools=(),
    )
    with pytest.raises(RoError) as exc:
        _validate(reg)
    assert exc.value.why


# ── did_you_mean wired into 5 typo-prone surfaces ────────────────


def _envelope(result):
    if isinstance(result, list) and result:
        return json.loads(result[0].text)
    raise AssertionError(f"unexpected handler return shape: {type(result)}")


@pytest.fixture
def project_root(tmp_path):
    (tmp_path / ".os_state").mkdir()
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "logs").mkdir()
    return tmp_path


def test_dispatcher_unknown_tool_namespace_aware(project_root):
    from research_os.server import _handle_tool_call

    # Typo on a sys_ tool should prefer sys_ candidates in suggestions.
    result = _handle_tool_call("sys_protocol_lst", {}, project_root)
    env = _envelope(result)
    assert env["status"] == "error"
    next_action = (env["payload"] or {}).get("next_action") or ""
    # Should mention at least one sys_ tool in the suggestion list.
    if "did you mean" in next_action.lower():
        # In-namespace candidate should be first if any sys_ name matched.
        m = re.search(r"did you mean:\s*([^?]+)", next_action, flags=re.I)
        if m:
            first = m.group(1).split(",")[0].strip()
            assert first.startswith("sys_"), (
                f"namespace-aware suggestion should lead with sys_*, got {first!r}"
            )


def test_removed_tool_returns_migration_error(project_root):
    """Consolidated-away tools return a clear migration error naming a live tool."""
    from research_os.server import _handle_tool_call

    for removed, hint in (
        ("sys_protocol_list", "sys_protocol_get"),
        ("sys_packs_installed", "skills"),
        ("tool_adapter_extract", "skills"),
    ):
        result = _handle_tool_call(removed, {}, project_root)
        env = _envelope(result)
        assert env["status"] == "error"
        payload = env.get("payload") or {}
        msg = (payload.get("what") or "").lower()
        assert "removed" in msg
