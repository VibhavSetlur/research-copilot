"""4.0.3: gate + data-integrity hardening (F1-F4 from the third audit)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from research_os.project_ops import scaffold_minimal_workspace
from research_os.server.autopilot_gate import _read_autonomy_level
from research_os.server.gate_spec import resolve_declared_gate
from research_os.tools.actions.state.config import _config_path
from research_os.tools.actions.state.iteration import (
    _iteration_ledger_path,
    _load_ledger,
    _save_ledger,
)


def _proj() -> Path:
    root = Path(tempfile.mkdtemp()) / "p"
    scaffold_minimal_workspace(root, "T", mode="analysis")
    return root


# F2 — paid-tool gate must fire for case-variant source values
def test_paid_gate_fires_case_insensitively():
    for src in ("paid", "PAID", "Paid_Or_Licensed", "paid_or_licensed"):
        assert resolve_declared_gate("tool_search", {"source": src}) is not None, src
    assert resolve_declared_gate("tool_search", {"source": "free"}) is None


# F3 — a corrupt config must NOT disable floor gates (fail-safe, not fail-open)
def test_corrupt_config_fails_to_protective_level():
    root = _proj()
    cfg = _config_path(root)
    cfg.write_text("interaction:\n  autonomy_level: autopilot\n")
    assert _read_autonomy_level(root) == "autopilot"
    cfg.write_text("interaction:\n  autonomy_level: autopilot\n  : : broken [[[\n")
    # corrupt -> 'adaptive' (gates still apply), NOT 'supervised' (gates off)
    assert _read_autonomy_level(root) == "adaptive"
    cfg.unlink()
    assert _read_autonomy_level(root) == "supervised"  # truly absent = opt-out


# F4 — a corrupt iteration ledger must be backed up, not silently wiped
def test_corrupt_iteration_ledger_is_backed_up_not_wiped():
    sd = Path(tempfile.mkdtemp()) / "01_step"
    sd.mkdir(parents=True)
    _save_ledger(sd, {"step_id": "01_step", "iterations": [{"n": 1}, {"n": 2}]})
    _iteration_ledger_path(sd).write_text("iterations: [[[ broken : :")
    led = _load_ledger(sd)
    assert led["iterations"] == []  # fresh ledger
    backups = list(sd.glob("*.corrupt-*"))
    assert len(backups) == 1  # prior history preserved, recoverable


# F1 — non-ASCII deliverable labels must not collide into one folder
def test_unicode_deliverable_labels_do_not_collide():
    from research_os.tools.actions.synthesis.scaffold import synthesis_scaffold

    root = _proj()
    synthesis_scaffold(root, kind="poster", label="研究")
    synthesis_scaffold(root, kind="poster", label="🎉")
    d = root / "synthesis" / "deliverables"
    dirs = [p.name for p in d.iterdir() if p.is_dir()] if d.is_dir() else []
    # two DISTINCT unicode labels -> two distinct folders (not one "deliverable")
    assert len(set(dirs)) >= 2, dirs
    assert "deliverable" not in dirs  # no bare-collision folder
