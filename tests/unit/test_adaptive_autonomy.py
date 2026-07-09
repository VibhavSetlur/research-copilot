"""Adaptive autonomy — trust-driven floor-gate flexing.

v3.3 makes ``adaptive`` the default autonomy level: the researcher never
picks a mode. The gate SET flexes with the project's resolved
``gate_strictness`` (trust-score driven):

  strict  → all 8 gates fire (== autopilot)
  normal  → irreversible + real-cost gates fire; reversible ones flow
  light   → only irreversible / real-money gates fire

These tests pin the per-gate floors and the fail-safe behavior.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_os.server.autopilot_gate import (
    _GATE_FLOOR,
    _STRICTNESS_RANK,
    enforce_autopilot_gate,
)
from research_os.server.errors import RoError
from research_os.tools.actions.state.config import (
    gate_is_active,
    normalize_autonomy_level,
)


def _write_cfg(root: Path, *, autonomy: str, gate_strictness: str | None = None,
               project_tier: str | None = None) -> None:
    cfg_dir = root / "inputs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    block: dict = {"interaction": {"autonomy_level": autonomy}}
    if gate_strictness is not None:
        block["gate_strictness"] = gate_strictness
    if project_tier is not None:
        block["project_tier"] = project_tier
    (cfg_dir / "researcher_config.yaml").write_text(yaml.safe_dump(block))


# (tool_name, arguments, gate_key) for every adaptive-classified gate.
GATES: list[tuple[str, dict, str]] = [
    ("tool_package_install", {"packages": ["numpy"]}, "tool_package_install"),
    ("tool_search", {"query": "lit", "source": "paid"},
     "search_paid_sources"),
    ("tool_typst_compile", {}, "tool_typst_compile"),
    ("tool_audit", {"scope": "step", "dimension": "reproducibility"},
     "tool_audit:reproducibility"),
    ("sys_file_write",
     {"filepath": "synthesis/paper.typ", "content": "x", "force": True},
     "sys_file_write:synthesis_force"),
    ("tool_task", {"operation": "run", "command": "ls"}, "tool_task:run"),
]


def _prep_gate_target(root, gate_key):
    """Create on-disk state a gate needs to actually fire.

    The synthesis-force gate only trips on an OVERWRITE of an existing
    file (a fresh write destroys nothing), so materialize the target.
    """
    if gate_key == "sys_file_write:synthesis_force":
        syn = root / "synthesis"
        syn.mkdir(parents=True, exist_ok=True)
        (syn / "paper.typ").write_text("existing deliverable")


# ── normalization ───────────────────────────────────────────────────────

def test_adaptive_is_default():
    assert normalize_autonomy_level(None) == "adaptive"
    assert normalize_autonomy_level("") == "adaptive"
    assert normalize_autonomy_level("nonsense") == "adaptive"


def test_adaptive_recognized():
    assert normalize_autonomy_level("adaptive") == "adaptive"


def test_coaching_still_aliases_supervised():
    assert normalize_autonomy_level("coaching") == "supervised"


def test_gate_is_active():
    assert gate_is_active("adaptive") is True
    assert gate_is_active("autopilot") is True
    assert gate_is_active("supervised") is False
    assert gate_is_active("manual") is False
    assert gate_is_active(None) is True  # default adaptive is gate-active


# ── strict strictness == full autopilot set ─────────────────────────────

@pytest.mark.parametrize("tool_name,arguments,gate_key", GATES)
def test_adaptive_strict_blocks_all_gates(tmp_path, tool_name, arguments, gate_key):
    """At strict strictness, adaptive fires every floor gate (== autopilot)."""
    _write_cfg(tmp_path, autonomy="adaptive", gate_strictness="strict")
    _prep_gate_target(tmp_path, gate_key)
    with pytest.raises(RoError) as exc:
        enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)
    assert exc.value.what == "autopilot_gate_blocked"


# ── light strictness: only the light-floor gates fire ───────────────────

@pytest.mark.parametrize("tool_name,arguments,gate_key", GATES)
def test_adaptive_light_only_irreversible(tmp_path, tool_name, arguments, gate_key):
    """At light strictness, only light-floor (irreversible/$$) gates fire."""
    _write_cfg(tmp_path, autonomy="adaptive", gate_strictness="light")
    _prep_gate_target(tmp_path, gate_key)
    floor = _GATE_FLOOR[gate_key]
    should_fire = _STRICTNESS_RANK["light"] >= _STRICTNESS_RANK[floor]
    if should_fire:
        with pytest.raises(RoError):
            enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)
    else:
        # must NOT raise — rigorous project flows through reversible gate
        enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)


@pytest.mark.parametrize("tool_name,arguments,gate_key", GATES)
def test_adaptive_normal_intermediate(tmp_path, tool_name, arguments, gate_key):
    """At normal strictness, light+normal gates fire; strict-only ones flow."""
    _write_cfg(tmp_path, autonomy="adaptive", gate_strictness="normal")
    _prep_gate_target(tmp_path, gate_key)
    floor = _GATE_FLOOR[gate_key]
    should_fire = _STRICTNESS_RANK["normal"] >= _STRICTNESS_RANK[floor]
    if should_fire:
        with pytest.raises(RoError):
            enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)
    else:
        enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)


# ── confirmed bypass + non-gate-active levels ───────────────────────────

@pytest.mark.parametrize("tool_name,arguments,gate_key", GATES)
def test_confirmed_bypasses_adaptive(tmp_path, tool_name, arguments, gate_key):
    _write_cfg(tmp_path, autonomy="adaptive", gate_strictness="strict")
    _prep_gate_target(tmp_path, gate_key)
    args = dict(arguments)
    args["confirmed"] = True
    enforce_autopilot_gate(tool_name, args, tmp_path)  # no raise


@pytest.mark.parametrize("tool_name,arguments,gate_key", GATES)
def test_supervised_never_gated_here(tmp_path, tool_name, arguments, gate_key):
    """supervised handles asks in-flow; the server gate is a no-op for it."""
    _write_cfg(tmp_path, autonomy="supervised", gate_strictness="strict")
    enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)  # no raise


# ── fail-safe: missing config defaults to adaptive+strict (full gates) ──

@pytest.mark.parametrize("tool_name,arguments,gate_key", GATES)
def test_no_config_defaults_safe(tmp_path, tool_name, arguments, gate_key):
    """No researcher_config → _read_autonomy returns 'supervised' (safe no-op)."""
    # No config written. The gate reads 'supervised' fallback → no raise.
    enforce_autopilot_gate(tool_name, dict(arguments), tmp_path)  # no raise


def test_light_floor_gates_are_irreversible():
    """Sanity: the light-floor gates are exactly the irreversible/$$ set."""
    light_gates = {k for k, v in _GATE_FLOOR.items() if v == "light"}
    assert light_gates == {
        "tool_package_install",
        "tool_git (operation=rollback)",
        "dead_end_abandon",
        "search_paid_sources",
    }
