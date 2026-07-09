"""Autonomous continuation (opt-in goal loop) + audit-judge scoring.

continuation: opt-in only, hop-limited, fail-open. judge: validates the
scorecard shape (a score without a reason is rejected).
"""
from __future__ import annotations


from research_os.daemon import continuation
from research_os.daemon.config import DaemonConfig
from research_os.tools.actions.audit import judge


# --- continuation: opt-in + hop ceiling ------------------------------------

def test_continuation_noop_when_not_opted_in(tmp_path):
    cfg = DaemonConfig()  # continue_command == "" (default)
    continuation.start_goal_loop(tmp_path, "reach the goal")
    res = continuation.maybe_continue(tmp_path, config=cfg, finished_run={"id": "r1"})
    assert res["ran"] is False
    assert res["reason"] == "not_opted_in"


def test_continuation_noop_without_active_goal(tmp_path):
    cfg = DaemonConfig(continue_command="true")  # opted in
    # no goal loop started
    res = continuation.maybe_continue(tmp_path, config=cfg, finished_run={"id": "r1"})
    assert res["ran"] is False
    assert res["reason"] == "no_active_goal"


def test_continuation_runs_a_hop_when_opted_in(tmp_path):
    cfg = DaemonConfig(continue_command="true")  # harmless command
    continuation.start_goal_loop(tmp_path, "build the model")
    res = continuation.maybe_continue(tmp_path, config=cfg, finished_run={"id": "r1"})
    assert res["ran"] is True
    assert res["hop"] == 1
    # a hop payload was persisted
    assert (tmp_path / ".os_state" / "continuation" / "hop_0001.json").exists()


def test_continuation_respects_hop_ceiling(tmp_path):
    cfg = DaemonConfig(continue_command="true", continue_max_hops=2)
    continuation.start_goal_loop(tmp_path, "loop goal")
    r1 = continuation.maybe_continue(tmp_path, config=cfg, finished_run={"id": "a"})
    r2 = continuation.maybe_continue(tmp_path, config=cfg, finished_run={"id": "b"})
    r3 = continuation.maybe_continue(tmp_path, config=cfg, finished_run={"id": "c"})
    assert r1["ran"] and r2["ran"]
    assert r3["ran"] is False
    assert r3["reason"] == "max_hops_reached"


def test_stop_goal_loop_halts_continuation(tmp_path):
    cfg = DaemonConfig(continue_command="true")
    continuation.start_goal_loop(tmp_path, "g")
    continuation.stop_goal_loop(tmp_path, reason="goal_met")
    res = continuation.maybe_continue(tmp_path, config=cfg, finished_run={"id": "x"})
    assert res["ran"] is False
    assert res["reason"] == "no_active_goal"


def test_build_payload_is_self_contained(tmp_path):
    p = continuation.build_continuation_payload(
        tmp_path, finished_run={"id": "r9", "status": "succeeded"},
        goal="the goal", hops=3,
    )
    assert p["kind"] == "autonomous_continuation"
    assert p["goal"] == "the goal"
    assert p["hop"] == 3
    assert p["finished_run"]["id"] == "r9"
    assert "instruction" in p


# --- judge: scorecard validation -------------------------------------------

def _good_dims():
    return [
        {"name": "rigor", "score": 4, "justification": "pre-registered, CI reported"},
        {"name": "clarity", "score": 5, "justification": "figures + plain conclusions"},
    ]


def test_judge_records_valid_scorecard(tmp_path):
    res = judge.score_work(
        tmp_path, subject="step 03 analysis", dimensions=_good_dims(),
        limitations=["small n"], improvements=[], verdict="ship",
    )
    assert res["status"] == "success"
    assert res["mean_score"] == 4.5
    assert res["verdict"] == "ship"
    assert (tmp_path / ".os_state" / "judge" / "latest.json").exists()


def test_judge_rejects_score_without_justification(tmp_path):
    bad = [{"name": "rigor", "score": 3, "justification": "ok"}]  # too short
    res = judge.score_work(
        tmp_path, subject="x", dimensions=bad, limitations=[], improvements=[],
        verdict="ship",
    )
    assert res["status"] == "error"
    assert "justification" in res["message"]


def test_judge_rejects_out_of_range_score(tmp_path):
    bad = [{"name": "rigor", "score": 9, "justification": "way too high a number"}]
    res = judge.score_work(
        tmp_path, subject="x", dimensions=bad, limitations=[], improvements=[],
        verdict="ship",
    )
    assert res["status"] == "error"
    assert "0..5" in res["message"]


def test_judge_iterate_requires_improvements(tmp_path):
    res = judge.score_work(
        tmp_path, subject="x", dimensions=_good_dims(), limitations=[],
        improvements=[], verdict="iterate",  # no improvements -> reject
    )
    assert res["status"] == "error"
    assert "improvement" in res["message"]


def test_judge_invalid_verdict_rejected(tmp_path):
    res = judge.score_work(
        tmp_path, subject="x", dimensions=_good_dims(), limitations=[],
        improvements=["do better"], verdict="maybe",
    )
    assert res["status"] == "error"


def test_judge_latest_scorecard_roundtrips(tmp_path):
    judge.score_work(
        tmp_path, subject="s", dimensions=_good_dims(), limitations=[],
        improvements=["x"], verdict="iterate",
    )
    latest = judge.latest_scorecard(tmp_path)
    assert latest is not None and latest["verdict"] == "iterate"


def test_judge_loop_signal_ship_vs_iterate(tmp_path):
    ship = judge.score_work(
        tmp_path, subject="a", dimensions=_good_dims(), limitations=[],
        improvements=[], verdict="ship",
    )
    assert "stop the loop" in ship["loop_signal"]
    it = judge.score_work(
        tmp_path, subject="b", dimensions=_good_dims(), limitations=[],
        improvements=["fix it"], verdict="iterate",
    )
    assert "keep iterating" in it["loop_signal"]


def test_continuation_max_hops_zero_disables(tmp_path):
    """F3: continue_max_hops=0 must DISABLE the loop, not fall back to 25."""
    cfg = DaemonConfig(continue_command="true", continue_max_hops=0)
    continuation.start_goal_loop(tmp_path, "g")
    res = continuation.maybe_continue(tmp_path, config=cfg, finished_run={"id": "x"})
    assert res["ran"] is False
    assert res["reason"] == "autonomy_disabled"
