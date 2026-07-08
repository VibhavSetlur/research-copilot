"""Tests for the per-figure interactivity gate (Theme 20)."""

from __future__ import annotations

import csv
import json
from pathlib import Path


from research_os.tools.actions.audit.figure_interactivity import (
    OVERRIDE_PATTERN,
    _csv_rows,
    _csv_shape_at_least,
    _detect_kind,
    audit_figure_interactivity,
    figure_interactive_autogen,
)


def _png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    return path


def _scatter_csv(path: Path, n: int = 300) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["x", "y", "gene"])
        for i in range(n):
            w.writerow([i * 0.1, (i % 7) * 0.5, f"GENE{i}"])
    return path


def _heatmap_csv(path: Path, rows: int = 60, cols: int = 60) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sample"] + [f"S{j}" for j in range(cols)])
        for i in range(rows):
            w.writerow([f"G{i}"] + [str(i * j * 0.01) for j in range(cols)])
    return path


def _graphml(path: Path) -> Path:
    path.write_text(
        '<?xml version="1.0"?>'
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">'
        '<graph><node id="A"/><node id="B"/><node id="C"/>'
        '<edge source="A" target="B"/><edge source="B" target="C"/>'
        '</graph></graphml>'
    )
    return path


# ──────────────────────────────────────────────────────────────────────
# kind detection
# ──────────────────────────────────────────────────────────────────────


def test_detect_kind_scatter_via_data_csv(tmp_path: Path):
    fig = _png(tmp_path / "01_volcano.png")
    _scatter_csv(tmp_path / "01_volcano_data.csv")
    assert _detect_kind(fig) == "scatter"


def test_detect_kind_skips_low_volume_scatter(tmp_path: Path):
    fig = _png(tmp_path / "01_volcano.png")
    _scatter_csv(tmp_path / "01_volcano_data.csv", n=50)
    # Below threshold but the name matches — naming hit produces "scatter"
    # so the gate still flags it. That's intentional.
    assert _detect_kind(fig) == "scatter"


def test_detect_kind_heatmap_via_matrix(tmp_path: Path):
    fig = _png(tmp_path / "02_x.png")
    _heatmap_csv(tmp_path / "02_x_matrix.csv")
    assert _detect_kind(fig) == "heatmap"


def test_detect_kind_network_via_graphml(tmp_path: Path):
    fig = _png(tmp_path / "03_n.png")
    _graphml(tmp_path / "03_n.graphml")
    assert _detect_kind(fig) == "network"


def test_detect_kind_other_for_unflagged_bar(tmp_path: Path):
    fig = _png(tmp_path / "04_bar.png")
    assert _detect_kind(fig) == "other"


def test_csv_rows_counts_correctly(tmp_path: Path):
    p = tmp_path / "d.csv"
    p.write_text("a,b\n1,2\n3,4\n5,6\n")
    assert _csv_rows(p) == 3


def test_csv_shape_at_least(tmp_path: Path):
    p = _heatmap_csv(tmp_path / "x.csv", rows=60, cols=60)
    assert _csv_shape_at_least(p, rows=50, cols=50) is True
    assert _csv_shape_at_least(p, rows=100, cols=50) is False


def test_override_pattern_matches():
    m = OVERRIDE_PATTERN.search("<!-- ro:interactive-not-applicable, reason: x -->")
    assert m and m.group(1).strip() == "x"


# ──────────────────────────────────────────────────────────────────────
# audit gate
# ──────────────────────────────────────────────────────────────────────


def test_strict_mode_blocks_missing_companion(tmp_path: Path):
    _png(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano_data.csv")
    res = audit_figure_interactivity(tmp_path, strictness="strict", autogen=False)
    assert res["status"] == "success"
    assert len(res["blockers"]) == 1
    assert res["blockers"][0]["kind"] == "scatter"


def test_normal_mode_warns_and_autogens(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano_data.csv")
    res = audit_figure_interactivity(tmp_path, strictness="normal", autogen=True)
    assert res["status"] == "success"
    assert len(res["blockers"]) == 0
    assert len(res["warnings"]) == 1
    # Autogen wrote the companion
    assert fig.with_suffix(".html").exists()


def test_light_mode_warns_only(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano_data.csv")
    res = audit_figure_interactivity(tmp_path, strictness="light", autogen=False)
    assert len(res["blockers"]) == 0
    assert len(res["warnings"]) == 1
    # Light + autogen=False → no companion written
    assert not fig.with_suffix(".html").exists()


def test_override_skips_gate(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano_data.csv")
    fig.with_suffix(".caption.md").write_text(
        "<!-- ro:interactive-not-applicable, reason: poster only -->"
    )
    res = audit_figure_interactivity(tmp_path, strictness="strict", autogen=False)
    assert len(res["blockers"]) == 0
    assert len(res["overrides"]) == 1
    assert "poster only" in res["overrides"][0]["reason"]


def test_companion_existing_passes(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano_data.csv")
    fig.with_suffix(".html").write_text("<html>handcrafted</html>")
    res = audit_figure_interactivity(tmp_path, strictness="strict", autogen=False)
    assert len(res["blockers"]) == 0
    assert any(p["companion"] for p in res["passes"])


def test_audit_writes_log(tmp_path: Path):
    _png(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "01_demo" / "outputs" / "figures" / "01_volcano_data.csv")
    audit_figure_interactivity(tmp_path, strictness="normal", autogen=True)
    log = tmp_path / "workspace" / "logs" / "figure_interactivity_audit.md"
    assert log.exists()
    body = log.read_text()
    assert "Figure interactivity audit" in body


def test_audit_no_workspace_no_findings(tmp_path: Path):
    res = audit_figure_interactivity(tmp_path, strictness="strict", autogen=False)
    assert res["status"] == "success"
    assert res["blockers"] == [] and res["warnings"] == []


# ──────────────────────────────────────────────────────────────────────
# autogen output sanity
# ──────────────────────────────────────────────────────────────────────


def test_autogen_scatter_writes_vega_lite_spec(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "x" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "x" / "outputs" / "figures" / "01_volcano_data.csv")
    res = figure_interactive_autogen(fig, tmp_path)
    assert res["status"] == "success"
    html = fig.with_suffix(".html").read_text()
    assert "vegaEmbed" in html
    assert "ro-auto-generated" in html
    # The embedded spec parses as JSON
    import re
    m = re.search(r"const spec = (\{.*?\});", html, re.DOTALL)
    assert m
    spec = json.loads(m.group(1).replace("<\\/", "</"))
    assert spec["mark"]["type"] == "point" or spec["mark"] == "point"


def test_autogen_heatmap_uses_viridis(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "x" / "outputs" / "figures" / "02_h.png")
    _heatmap_csv(tmp_path / "workspace" / "x" / "outputs" / "figures" / "02_h_matrix.csv")
    res = figure_interactive_autogen(fig, tmp_path)
    assert res["status"] == "success"
    html = fig.with_suffix(".html").read_text()
    assert "viridis" in html


def test_autogen_network_inlines_vis_network(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "x" / "outputs" / "figures" / "03_n.png")
    _graphml(tmp_path / "workspace" / "x" / "outputs" / "figures" / "03_n.graphml")
    res = figure_interactive_autogen(fig, tmp_path)
    assert res["status"] == "success"
    html = fig.with_suffix(".html").read_text()
    assert "vis.Network" in html
    assert "ro-auto-generated" in html


def test_autogen_idempotent(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "x" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "x" / "outputs" / "figures" / "01_volcano_data.csv")
    res1 = figure_interactive_autogen(fig, tmp_path)
    assert res1["status"] == "success"
    res2 = figure_interactive_autogen(fig, tmp_path)
    assert res2["status"] == "exists"


def test_autogen_html_is_offline(tmp_path: Path):
    """No external src=https:// in the generated HTML."""
    import re
    fig = _png(tmp_path / "workspace" / "x" / "outputs" / "figures" / "01_volcano.png")
    _scatter_csv(tmp_path / "workspace" / "x" / "outputs" / "figures" / "01_volcano_data.csv")
    figure_interactive_autogen(fig, tmp_path)
    html = fig.with_suffix(".html").read_text()
    bad = re.findall(r'(?:src|href)\s*=\s*["\']https?://[^"\']+["\']', html)
    assert not bad, f"external refs: {bad[:3]}"


def test_autogen_skipped_without_data(tmp_path: Path):
    fig = _png(tmp_path / "workspace" / "x" / "outputs" / "figures" / "99_volcano.png")
    res = figure_interactive_autogen(fig, tmp_path)
    # No data csv → scatter detected by name but data file missing
    assert res["status"] == "skipped"
