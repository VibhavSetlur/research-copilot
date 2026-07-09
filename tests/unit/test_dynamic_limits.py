"""Dynamic resource limits — scale a run's ceiling to live host capacity.

Verifies the min(declared, requested, headroom) policy + fail-open behaviour.
Capacity is injected so the tests are deterministic (no real /proc dependence).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from research_os.daemon import dynamic_limits as dl


def _write_cfg(root: Path, runtime: dict) -> None:
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "inputs" / "researcher_config.yaml").write_text(
        yaml.safe_dump({"runtime": runtime})
    )


def _cap(avail_mb, total_mb=64000, cpus=16, load=2.0):
    return dl.SystemCapacity(
        total_mem_mb=total_mb, available_mem_mb=avail_mb,
        cpu_count=cpus, load_avg_1m=load, source="proc",
    )


# --- headroom math ---------------------------------------------------------

def test_idle_box_allows_large_run(tmp_path):
    """An idle node with lots of free RAM and an UNCAPPED static budget lets a
    run claim a big (multi-gig) headroom slice."""
    _write_cfg(tmp_path, {"resource_budget": {"memory_mb": 0}})  # uncapped
    limits, explain = dl.resolve_dynamic_limits(
        tmp_path, capacity=_cap(avail_mb=50000)
    )
    # 80% of (50000 - 2048 reserve) ≈ 38361 MB — a real multi-gig allowance.
    assert explain["dynamic"] == "on"
    assert limits.address_space_mb is not None
    assert limits.address_space_mb > 30000


def test_busy_box_shrinks_the_run(tmp_path):
    """When the node is nearly full, the headroom bound shrinks toward the
    minimum so one run can't finish off the box."""
    _write_cfg(tmp_path, {"resource_budget": {"memory_mb": 0}})
    limits, explain = dl.resolve_dynamic_limits(
        tmp_path, capacity=_cap(avail_mb=2500)  # only 2.5GB free, 2GB reserved
    )
    # spare = 500MB * 0.8 = 400 -> floored to min_mem_mb (512).
    assert limits.address_space_mb == 512


def test_declared_ceiling_is_never_exceeded(tmp_path):
    """Even on a wide-open idle box, the run never gets more than the
    researcher's declared hard cap."""
    _write_cfg(tmp_path, {"resource_budget": {"memory_mb": 4096}})
    limits, explain = dl.resolve_dynamic_limits(
        tmp_path, capacity=_cap(avail_mb=500000)  # 500GB free
    )
    assert limits.address_space_mb == 4096  # capped at the declared 4GB


def test_requested_size_bounds_the_run(tmp_path):
    """A run that declares it needs ~8GB gets min(declared, requested, headroom)."""
    _write_cfg(tmp_path, {"resource_budget": {"memory_mb": 0}})
    limits, explain = dl.resolve_dynamic_limits(
        tmp_path, requested_mem_mb=8192, capacity=_cap(avail_mb=500000)
    )
    assert limits.address_space_mb == 8192


def test_disabled_policy_keeps_static(tmp_path):
    _write_cfg(tmp_path, {
        "resource_budget": {"memory_mb": 4096},
        "dynamic_resources": {"enabled": False},
    })
    limits, explain = dl.resolve_dynamic_limits(
        tmp_path, capacity=_cap(avail_mb=500000)
    )
    assert explain["dynamic"] == "disabled"
    assert limits.address_space_mb == 4096


def test_no_capacity_signal_falls_back_to_static(tmp_path):
    _write_cfg(tmp_path, {"resource_budget": {"memory_mb": 4096}})
    nocap = dl.SystemCapacity(source="none")
    limits, explain = dl.resolve_dynamic_limits(tmp_path, capacity=nocap)
    assert explain["dynamic"] == "no_capacity_signal"
    assert limits.address_space_mb == 4096


def test_custom_policy_fraction_and_reserve(tmp_path):
    _write_cfg(tmp_path, {
        "resource_budget": {"memory_mb": 0},
        "dynamic_resources": {"mem_fraction": 0.5, "mem_reserve_mb": 4096},
    })
    limits, _ = dl.resolve_dynamic_limits(tmp_path, capacity=_cap(avail_mb=20000))
    # (20000 - 4096) * 0.5 = 7952
    assert limits.address_space_mb == 7952


# --- probe + fail-open -----------------------------------------------------

def test_probe_capacity_never_raises():
    cap = dl.probe_capacity()
    assert isinstance(cap, dl.SystemCapacity)
    # On a real Linux box this should pick up SOME signal; on a weird host it
    # degrades to source="none" without raising.
    assert cap.source in ("psutil", "proc", "none")


def test_load_dynamic_policy_defaults(tmp_path):
    pol = dl.load_dynamic_policy(tmp_path)
    assert pol["enabled"] is True
    assert 0 < pol["mem_fraction"] <= 1


def test_idle_cpus_estimate():
    cap = _cap(avail_mb=1000, cpus=16, load=4.0)
    assert cap.idle_cpus == 12.0
    # never negative even under heavy load
    busy = _cap(avail_mb=1000, cpus=4, load=20.0)
    assert busy.idle_cpus == 0.0
