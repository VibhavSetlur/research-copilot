"""Per-output PROV-O sidecar tests."""

from pathlib import Path

from research_os.daemon.provenance import capture, env_provenance
from research_os.tools.actions.state.provenance import (
    load_provenance,
    step_provenance_inventory,
    track_runtime,
    write_output_provenance,
)


def test_provenance_sidecar_written(tmp_path: Path):
    out = tmp_path / "fig.png"
    out.write_bytes(b"\x89PNG\r\n")
    sidecar = write_output_provenance(
        output_path=out, root=tmp_path,
        produced_by={"tool": "test", "script": "scripts/test.py"},
        inputs={}, params={"alpha": 0.05}, rng_seed=42,
        step_id="01_test",
    )
    assert sidecar.exists()
    assert sidecar.name == "fig.prov.json"


def test_provenance_round_trip(tmp_path: Path):
    out = tmp_path / "model.pkl"
    out.write_bytes(b"DATA")
    write_output_provenance(
        output_path=out, root=tmp_path,
        produced_by={"tool": "tool_step_pipeline_run"},
        inputs={"data": Path("input.csv")},
        params={"seed": 7},
        rng_seed=7,
        step_id="02_fit",
    )
    rec = load_provenance(out, tmp_path)
    assert rec is not None
    assert rec["step_id"] == "02_fit"
    assert rec["rng_seed"] == 7
    assert rec["params"]["seed"] == 7
    assert "sha256:" in rec["output"]["sha256"]


def test_provenance_inventory_pct(tmp_path: Path):
    step_dir = tmp_path / "workspace" / "01_eda"
    figs = step_dir / "outputs" / "figures"
    figs.mkdir(parents=True)
    # Two figures; one with sidecar, one without.
    (figs / "01_a.png").write_bytes(b"\x89PNG")
    (figs / "01_b.png").write_bytes(b"\x89PNG")
    write_output_provenance(
        output_path=figs / "01_a.png", root=tmp_path,
        step_id="01_eda",
    )
    inv = step_provenance_inventory(step_dir, tmp_path)
    assert inv["total_outputs"] == 2
    assert inv["with_provenance"] == 1
    assert inv["coverage_pct"] == 50.0


def test_track_runtime_records_wall_seconds():
    with track_runtime() as rt:
        import time

        time.sleep(0.02)
    assert rt["wall_seconds"] is not None
    assert rt["wall_seconds"] > 0


def test_env_provenance_records_offline_flag():
    prov = env_provenance(offline=True)
    assert prov["offline"] is True


def test_capture_propagates_offline_flag(tmp_path: Path):
    cap = capture(tmp_path, offline=True)
    assert cap["env"]["offline"] is True
