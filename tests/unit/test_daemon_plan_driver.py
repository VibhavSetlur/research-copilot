"""Tests for daemon/protocol_driver.py — §13.3 ProtocolDriver.

Style mirrors tests/unit/test_daemon_workflows.py:
- tmp_path, direct calls, dict assertions, json.dumps serializability.

Real protocol used: guidance/project_startup (9 steps, confirmed to load).
"""
from __future__ import annotations

import json

import pytest

from research_os.daemon.protocol_driver import ProtocolDriver, plans_dir

# The canonical protocol used for all happy-path tests.  Confirmed loadable:
#   ProtocolRegistry.get_protocol("guidance/project_startup") → 9 steps.
PROTOCOL = "guidance/project_startup"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_driver(root):
    return ProtocolDriver(root)


def _step_count(tmp_path):
    """How many steps does the test protocol have?"""
    from research_os.tools.actions.protocol import ProtocolRegistry
    return len(ProtocolRegistry.get_protocol(PROTOCOL).steps)


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------

def test_start_creates_plan_file(tmp_path):
    """start() writes a .os_state/plans/<id>.json with status=active, step_index=0."""
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)

    plan_file = plans_dir(tmp_path) / f"{plan_id}.json"
    assert plan_file.exists(), "plan file not created"

    data = json.loads(plan_file.read_text())
    assert data["id"] == plan_id
    assert data["protocol"] == PROTOCOL
    assert data["step_index"] == 0
    assert data["status"] == "active"
    assert "results" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_start_unknown_protocol_raises(tmp_path):
    """start() with an unknown protocol name raises a clear error (RoError)."""
    driver = _make_driver(tmp_path)
    with pytest.raises(Exception) as exc_info:
        driver.start("guidance/this_does_not_exist_at_all_xyz")
    # RoError or any descriptive exception — the important thing is it raises,
    # not returns silently.
    assert exc_info.value is not None


def test_start_returns_hex_id(tmp_path):
    """plan_id is a non-empty hex string (uuid4().hex)."""
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)
    assert isinstance(plan_id, str) and len(plan_id) == 32
    int(plan_id, 16)  # must be valid hex


def test_persisted_plan_is_json_serialisable(tmp_path):
    """The plan JSON must not contain any Protocol object — only the name."""
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)
    plan_file = plans_dir(tmp_path) / f"{plan_id}.json"
    raw = plan_file.read_text()
    data = json.loads(raw)
    # The "protocol" field must be a plain string (the name), not an object.
    assert isinstance(data["protocol"], str)
    assert data["protocol"] == PROTOCOL
    # No key like "steps", "trigger", etc. that would indicate the full
    # Protocol object was serialised.
    assert "steps" not in data
    assert "trigger" not in data
    # And the whole dict is round-trippable.
    assert json.dumps(data)  # must not raise


# ---------------------------------------------------------------------------
# step()
# ---------------------------------------------------------------------------

def test_step_returns_current_step_dict(tmp_path):
    """step() returns a dict with id, name, description, index, total_steps."""
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)
    result = driver.step(plan_id)

    assert isinstance(result, dict)
    assert result["index"] == 0
    assert "name" in result
    assert "description" in result
    assert "total_steps" in result
    assert result["total_steps"] == _step_count(tmp_path)


def test_step_missing_plan_returns_not_found(tmp_path):
    """step() on a non-existent plan_id returns a terminal-marker dict (no crash)."""
    driver = _make_driver(tmp_path)
    result = driver.step("deadbeef" * 4)
    assert isinstance(result, dict)
    assert result.get("status") == "not_found"


def test_step_completed_plan_returns_terminal(tmp_path):
    """step() on a completed plan returns a completed-status dict."""
    total = _step_count(tmp_path)
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)

    for i in range(total):
        driver.complete_step(plan_id, f"result-{i}")

    result = driver.step(plan_id)
    assert result.get("status") == "completed"


# ---------------------------------------------------------------------------
# complete_step()
# ---------------------------------------------------------------------------

def test_complete_step_advances_index(tmp_path):
    """complete_step() records the result and increments step_index."""
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)

    summary = driver.complete_step(plan_id, {"output": "first result"})
    assert summary["step_index"] == 1
    assert summary["status"] == "active"

    # Confirm on-disk too.
    plan_file = plans_dir(tmp_path) / f"{plan_id}.json"
    data = json.loads(plan_file.read_text())
    assert data["step_index"] == 1
    assert len(data["results"]) == 1


def test_complete_step_records_result_by_step_id(tmp_path):
    """complete_step() keys results by the step's id (or index)."""
    from research_os.tools.actions.protocol import ProtocolRegistry

    protocol = ProtocolRegistry.get_protocol(PROTOCOL)
    step0_key = protocol.steps[0].id or "0"

    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)
    driver.complete_step(plan_id, "my-result")

    plan_file = plans_dir(tmp_path) / f"{plan_id}.json"
    data = json.loads(plan_file.read_text())
    assert step0_key in data["results"]
    assert data["results"][step0_key] == "my-result"


def test_complete_last_step_sets_completed(tmp_path):
    """Completing the final step sets status='completed'."""
    total = _step_count(tmp_path)
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)

    for i in range(total - 1):
        driver.complete_step(plan_id, f"r{i}")

    summary = driver.complete_step(plan_id, "final")
    assert summary["status"] == "completed"
    assert summary["step_index"] == total

    # Verify on disk.
    data = json.loads((plans_dir(tmp_path) / f"{plan_id}.json").read_text())
    assert data["status"] == "completed"


def test_complete_step_missing_plan_raises(tmp_path):
    """complete_step() on a non-existent plan_id raises KeyError."""
    driver = _make_driver(tmp_path)
    with pytest.raises(KeyError):
        driver.complete_step("cafebabe" * 4, "some-result")


# ---------------------------------------------------------------------------
# Resumability (the key DoD requirement)
# ---------------------------------------------------------------------------

def test_resumability_new_driver_continues_existing_plan(tmp_path):
    """A brand-new ProtocolDriver instance on the same root can continue a plan.

    Proves that state is purely on disk: driver A starts + advances the plan,
    then is discarded.  Driver B (fresh instance) loads the same plan_id from
    disk and continues from where A left off.
    """
    # Driver A: start + complete step 0.
    driver_a = _make_driver(tmp_path)
    plan_id = driver_a.start(PROTOCOL)
    driver_a.complete_step(plan_id, "result-from-driver-a")

    # Driver A goes away — throw it away.
    del driver_a

    # Driver B: fresh instance, same root.
    driver_b = _make_driver(tmp_path)
    current = driver_b.step(plan_id)

    # Should now be on step 1 (driver A completed step 0).
    assert current["index"] == 1, (
        f"Expected index=1 after driver A completed step 0, got {current}"
    )

    # Driver B can complete the rest.
    total = _step_count(tmp_path)
    for i in range(1, total):
        driver_b.complete_step(plan_id, f"result-b-{i}")

    final = driver_b.step(plan_id)
    assert final.get("status") == "completed"


# ---------------------------------------------------------------------------
# get_plan() / list_plans()
# ---------------------------------------------------------------------------

def test_get_plan_returns_persisted_dict(tmp_path):
    """get_plan() returns the full persisted plan dict."""
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)
    plan = driver.get_plan(plan_id)

    assert plan is not None
    assert plan["id"] == plan_id
    assert plan["protocol"] == PROTOCOL
    assert plan["status"] == "active"


def test_get_plan_missing_returns_none(tmp_path):
    """get_plan() returns None for an unknown plan_id."""
    driver = _make_driver(tmp_path)
    assert driver.get_plan("does-not-exist") is None


def test_list_plans_returns_summaries(tmp_path):
    """list_plans() returns one summary per started plan."""
    driver = _make_driver(tmp_path)
    id1 = driver.start(PROTOCOL)
    id2 = driver.start(PROTOCOL)

    plans = driver.list_plans()
    ids = {p["id"] for p in plans}
    assert id1 in ids and id2 in ids
    # Each summary has the expected keys.
    for p in plans:
        assert "id" in p
        assert "protocol" in p
        assert "step_index" in p
        assert "status" in p
        assert "created_at" in p


def test_list_plans_skips_corrupt_files(tmp_path):
    """list_plans() silently skips corrupt JSON files."""
    driver = _make_driver(tmp_path)
    good_id = driver.start(PROTOCOL)

    # Write a corrupt file.
    bad_file = plans_dir(tmp_path) / "corrupt-plan.json"
    bad_file.write_text("not-json{{{{", encoding="utf-8")

    plans = driver.list_plans()
    ids = {p["id"] for p in plans}
    assert good_id in ids
    # No crash, the corrupt file was skipped.


def test_list_plans_empty_when_no_plans(tmp_path):
    """list_plans() returns [] when no plans have been started."""
    driver = _make_driver(tmp_path)
    assert driver.list_plans() == []


# ---------------------------------------------------------------------------
# Serialisation guard: plan JSON is small and name-based, no Protocol object
# ---------------------------------------------------------------------------

def test_plan_json_contains_only_protocol_name_not_object(tmp_path):
    """The persisted plan must store only the protocol NAME, not a Protocol object.

    This is the critical invariant that makes plans survive daemon restarts and
    bundle rebuilds: the Protocol is always rehydrated from the registry, never
    stored.
    """
    driver = _make_driver(tmp_path)
    plan_id = driver.start(PROTOCOL)
    driver.complete_step(plan_id, {"some": "result"})

    plan_file = plans_dir(tmp_path) / f"{plan_id}.json"
    raw = plan_file.read_text()
    data = json.loads(raw)

    # The protocol field is a string (the name), not an embedded object.
    assert isinstance(data["protocol"], str)

    # The file must not contain the full protocol body (steps key at top level
    # would indicate the Protocol object was inlined).
    assert "steps" not in data
    assert "trigger" not in data
    assert "expected_outputs" not in data

    # The file should be small: id + protocol + step_index + status + results
    # + timestamps = well under 2 KB for any reasonable result.
    assert len(raw) < 4096, f"Plan JSON unexpectedly large ({len(raw)} bytes)"
