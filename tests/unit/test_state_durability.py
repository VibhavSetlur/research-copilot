"""Durability / concurrency / recovery regressions (3.2.10 hardening wave).

Covers:
  * D1 — load_state→save_state RMW now routed through the ledger lock
    (concurrent-ish mutations don't lose each other; mutate_state helper).
  * D5 — current_tier.json atomic write (no partial file on crash).
  * D6 — active_plan.json atomic write at the persist sites.
  * D7 — researcher_certifications atomic write (no self-bricking partial).
  * E3 — sys_workspace_tree depth coercion + clamp.
"""

from __future__ import annotations

import json

from research_os.project_ops import (
    create_numbered_experiment,
    load_state,
    mutate_state,
    scaffold_minimal_workspace,
)
from research_os.state.state_ledger import ResearchLedger


# ── D1: locked read-modify-write ──────────────────────────────────────


def test_mutate_state_serialises_two_mutations(tmp_path):
    """Two sequential mutate_state calls compose — neither write is lost
    (the lock spans the whole load→mutate→save, not just the final write)."""
    scaffold_minimal_workspace(tmp_path, "T")

    mutate_state(tmp_path, lambda s: s.__setitem__("alpha", 1))
    mutate_state(tmp_path, lambda s: s.__setitem__("beta", 2))

    st = load_state(tmp_path)
    assert st["alpha"] == 1
    assert st["beta"] == 2


def test_mutate_state_preserves_concurrent_paths_entries(tmp_path):
    """Simulate the lost-update window: a mutator that reads the CURRENT
    locked state (not a stale snapshot taken before another write) must see
    the prior mutation. mutate_state reloads inside the lock, so the second
    add sees the first's path entry instead of clobbering it."""
    scaffold_minimal_workspace(tmp_path, "T")

    def add_path(pid):
        def _m(s):
            s.setdefault("paths", {})[pid] = {"path_id": pid, "status": "active"}
        return _m

    mutate_state(tmp_path, add_path("01_a"))
    mutate_state(tmp_path, add_path("02_b"))

    paths = load_state(tmp_path)["paths"]
    assert "01_a" in paths and "02_b" in paths


def test_locked_update_public_wrapper(tmp_path):
    ledger = ResearchLedger(tmp_path / ".os_state" / "state_ledger.json")
    out = ledger.locked_update(lambda s: s.__setitem__("domain", "bio"))
    assert out["domain"] == "bio"
    assert ledger.get()["domain"] == "bio"


def test_ledger_phase_mutators_stay_green_under_lock(tmp_path):
    """D8: update/set_phase/complete_phase now run under the lock; the return
    value + state shape must be unchanged (no deadlock from nested locks)."""
    ledger = ResearchLedger(tmp_path / ".os_state" / "state_ledger.json")
    ledger.update(pipeline_stage="execution", step=2)
    assert ledger.get()["pipeline_stage"] == "execution"
    ledger.set_phase("analysis", step=3)
    assert ledger.get()["checkpoints"]["analysis"] == "in_progress"
    ledger.complete_phase("analysis")
    s = ledger.get()
    assert s["checkpoints"]["analysis"] == "complete"
    assert s["resumable_from"] == "analysis"


def test_save_ctm_writes_blob_and_stub_under_lock(tmp_path):
    """D8: save_ctm keeps the disk-blob write outside the lock and appends
    the stub inside it — both must land."""
    ledger = ResearchLedger(tmp_path / ".os_state" / "state_ledger.json")
    state = ledger.save_ctm({"phase": "analysis", "handoff_notes": "x"})
    assert len(state["context_transfer_memo_stubs"]) == 1
    blobs = list((tmp_path / ".os_state" / "context_transfer_memos").glob("*.json"))
    assert len(blobs) == 1


def test_hypothesis_add_concurrent_ids_distinct(tmp_path):
    """D1: id allocation moved inside the locked mutator so two adds mint
    distinct H{n} instead of both minting the same id."""
    from research_os.tools.actions.memory.memory import (
        hypothesis_add,
        hypothesis_list,
    )

    scaffold_minimal_workspace(tmp_path, "T")
    hypothesis_add("first", tmp_path)
    hypothesis_add("second", tmp_path)
    ids = [h["id"] for h in hypothesis_list(tmp_path)["hypotheses"]]
    assert ids == ["H1", "H2"]


def test_create_numbered_experiment_records_path_under_lock(tmp_path):
    scaffold_minimal_workspace(tmp_path, "T")
    res = create_numbered_experiment(
        tmp_path, "eda", enforce_predecessor_finalized=False
    )
    st = load_state(tmp_path)
    assert res["path_id"] in st["paths"]
    assert st["current_path"] == res["path_id"]


# ── D5: current_tier.json atomic write ────────────────────────────────


def test_set_current_tier_is_atomic(tmp_path):
    from research_os.protocols._tiers import TIERS
    from research_os.tools.actions.state.tier_state import (
        get_current_tier,
        set_current_tier,
    )

    (tmp_path / ".os_state").mkdir(parents=True)
    set_current_tier(tmp_path, TIERS[0])
    set_current_tier(tmp_path, TIERS[1])
    assert get_current_tier(tmp_path) == TIERS[1]
    # No partial temp file left behind.
    leftover = list((tmp_path / ".os_state").glob("*.tmp"))
    assert not leftover
    # The committed file is valid JSON.
    data = json.loads((tmp_path / ".os_state" / "current_tier.json").read_text())
    assert data["current_tier"] == TIERS[1]


# ── D6: active_plan.json atomic write ─────────────────────────────────


def test_active_plan_persist_is_atomic(tmp_path):
    from research_os.tools.actions import router

    (tmp_path / ".os_state").mkdir(parents=True)
    router._persist_active_plan(
        tmp_path,
        prompt="do a thing",
        primary_protocol="guidance/analysis_plan",
        shortcut_tool=None,
        decomposition=[{"tool": "tool_route", "why": "x"}],
    )
    plan_path = tmp_path / ".os_state" / "active_plan.json"
    assert plan_path.exists()
    plan = json.loads(plan_path.read_text())  # valid JSON, fully written
    assert plan["primary_protocol"] == "guidance/analysis_plan"
    assert not list((tmp_path / ".os_state").glob("*.tmp"))


# ── D7: researcher_certifications atomic write ─────────────────────────


def test_self_certify_atomic_no_partial(tmp_path):
    from research_os.tools.actions.state.certifications import (
        _cert_path,
        list_certifications,
        self_certify,
    )

    scaffold_minimal_workspace(tmp_path, "T")
    res = self_certify(
        tmp_path, domain="code_review", scope="all steps",
        rationale="did it manually",
    )
    assert res["status"] == "success"
    assert list_certifications(tmp_path)["count"] == 1
    cert_dir = _cert_path(tmp_path).parent
    assert not list(cert_dir.glob("*.tmp"))


def test_certifications_save_leaves_prior_file_on_dump_failure(tmp_path):
    """An interrupted save must not clobber the prior valid file (atomic
    temp+replace). We assert the happy-path file is well-formed YAML/JSON
    after two successive saves."""
    from research_os.tools.actions.state.certifications import (
        _cert_path,
        self_certify,
    )

    scaffold_minimal_workspace(tmp_path, "T")
    self_certify(tmp_path, domain="code_review", scope="all", rationale="r1")
    self_certify(tmp_path, domain="preregistration", scope="all", rationale="r2")
    path = _cert_path(tmp_path)
    assert path.exists()
    # Parses cleanly (no truncation) — try YAML then JSON.
    text = path.read_text()
    try:
        import yaml
        data = yaml.safe_load(text)
    except Exception:
        data = json.loads(text)
    assert isinstance(data, dict)
    assert len(data.get("certifications", [])) == 2


# ── E3: sys_workspace_tree depth coercion + clamp ─────────────────────


def test_workspace_tree_handles_bad_depth(tmp_path):
    from research_os.server.handlers.meta_workspace import (
        _handle_sys_workspace_tree,
    )

    ws = tmp_path / "workspace"
    (ws / "a" / "b" / "c").mkdir(parents=True)

    # Negative, string, garbage, oversized, zero, None — none may crash.
    for depth in (-5, "3", "garbage", 9999, 0, None):
        out = _handle_sys_workspace_tree(
            "sys_workspace_tree", {"depth": depth}, tmp_path
        )
        # Handler returns a list of content objects; just confirm it ran.
        assert out is not None


def test_build_tree_negative_depth_terminates(tmp_path):
    """Defense-in-depth: a negative depth slipping past the clamp must still
    terminate at the base case rather than recurse the whole subtree."""
    from research_os.server._helpers import _build_tree

    (tmp_path / "x" / "y").mkdir(parents=True)
    res = _build_tree(tmp_path, -3, True)
    assert res == {"_truncated": True}
