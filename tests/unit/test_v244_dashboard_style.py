"""v2.4.4 — dashboard scaffold CSS rewrite + protocol updates.

Covers:

* The dashboard scaffold (``_DASHBOARD_HTML``) carries the new
  cream-bg + italic-serif + muted-accent identity, plus the existing
  section IDs the audit gate expects.
* ``audit_color_palette`` accepts the new Research-OS accent palette
  without warning (so the new dashboard ships clean).
* ``figure_guidelines.yaml`` and ``visualization_workflow.yaml`` carry
  the new spacing-discipline + render → view → v2 loop language.
* ``synthesis_dashboard.yaml`` references ``apply_research_os_style``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROTOCOLS_DIR = REPO_ROOT / "src" / "research_os" / "protocols"


# ---------------------------------------------------------------------------
# Dashboard scaffold CSS
# ---------------------------------------------------------------------------


def test_dashboard_scaffold_uses_cream_background():
    from research_os.tools.actions.synthesis.scaffold import _DASHBOARD_HTML
    # Cream variable in :root.
    assert "--bg: #FBF8F3" in _DASHBOARD_HTML
    # And used on body / html.
    assert "background: var(--bg)" in _DASHBOARD_HTML


def test_dashboard_scaffold_carries_full_accent_palette():
    """The five accents are the visual identity — navy / olive / forest /
    oxblood / mustard. Each must appear as a CSS variable."""
    from research_os.tools.actions.synthesis.scaffold import _DASHBOARD_HTML
    for cssvar, hex_ in (
        ("--accent:", "#1F4D7A"),
        ("--accent-gold:", "#9B7E2D"),
        ("--accent-green:", "#3F6049"),
        ("--accent-red:", "#9B3737"),
        ("--accent-mustard:", "#C3A14E"),
    ):
        assert cssvar in _DASHBOARD_HTML, f"missing {cssvar} in dashboard CSS"
        assert hex_ in _DASHBOARD_HTML, f"missing palette colour {hex_}"


def test_dashboard_scaffold_uses_serif_for_titles():
    from research_os.tools.actions.synthesis.scaffold import _DASHBOARD_HTML
    # serif stack + italic on h1/h2 (the look-vs-default differentiator).
    assert "EB Garamond" in _DASHBOARD_HTML
    assert "font-style: italic" in _DASHBOARD_HTML
    # h1 + h2 both italic serif.
    assert "header h1" in _DASHBOARD_HTML
    assert "section h2" in _DASHBOARD_HTML


def test_dashboard_scaffold_preserves_section_ids():
    """The default (scroll-lite-narrative) carries the stable section IDs the
    audit gates lint. Per-archetype sections (key-findings/comparison/panels)
    are composed by their own archetype, not the default — 3.2.8 turned the
    single fixed dashboard into a composable archetype system."""
    from research_os.tools.actions.synthesis.scaffold import _DASHBOARD_HTML
    for sid in (
        'id="headline"',
        'id="methods"',
        'id="limitations"',
        'id="references"',
    ):
        assert sid in _DASHBOARD_HTML, f"section {sid} missing from default"


def test_dashboard_archetypes_compose_and_stamp():
    """Every dashboard archetype composes cleanly, stamps data-archetype for
    the design audit, and leaves no template placeholders behind."""
    from research_os.tools.actions.synthesis.scaffold import (
        DASHBOARD_ARCHETYPES, _compose_dashboard,
    )
    assert set(DASHBOARD_ARCHETYPES) == {
        "single-viewport-brief", "scroll-lite-narrative",
        "comparison-scorecard", "multi-panel-exploratory",
    }
    for arch in DASHBOARD_ARCHETYPES:
        html = _compose_dashboard(arch)
        assert f'data-archetype="{arch}"' in html
        assert 'id="headline"' in html
        assert "__DASH_" not in html, f"placeholder left in {arch}"


def test_dashboard_palette_selection_swaps_tokens():
    """Choosing a palette swaps the :root tokens to that palette's hexes."""
    from research_os.tools.actions.synthesis.scaffold import _compose_dashboard
    from research_os.tools.actions.viz.palettes import PALETTES
    html = _compose_dashboard("scroll-lite-narrative", "clinical")
    assert PALETTES["clinical"]["light"]["primary"] in html
    assert PALETTES["ro_house"]["light"]["ground"] not in html.split("</style>")[0]


def test_dashboard_scaffold_has_print_stylesheet():
    """audit_print_friendly warns when @media print is missing — keep it."""
    from research_os.tools.actions.synthesis.scaffold import _DASHBOARD_HTML
    assert "@media print" in _DASHBOARD_HTML


def test_dashboard_scaffold_no_external_resources():
    """The dashboard must remain self-contained (single .html file,
    email-able). No <link href="http or <script src="http allowed.
    Strip HTML comments before the check so the warning text in the
    AI-facing comments (which itself names these forbidden patterns)
    doesn't trigger a false positive."""
    import re

    from research_os.tools.actions.synthesis.scaffold import _DASHBOARD_HTML
    body = re.sub(r"<!--.*?-->", "", _DASHBOARD_HTML, flags=re.S)
    assert "src=\"http://" not in body
    assert "src=\"https://" not in body
    assert "href=\"http://" not in body
    assert "href=\"https://" not in body


def test_dashboard_scaffold_points_at_style_helper():
    """The HTML comment should point the AI at apply_research_os_style
    so the figures embedded in the dashboard share its palette."""
    from research_os.tools.actions.synthesis.scaffold import _DASHBOARD_HTML
    assert "apply_research_os_style" in _DASHBOARD_HTML


# ---------------------------------------------------------------------------
# audit_color_palette accepts the new accent set
# ---------------------------------------------------------------------------


def test_audit_color_palette_accepts_research_os_accents():
    # 3.2.8: audit_color_palette no longer polices membership against a
    # hardcoded RESEARCH_OS_ACCENT allow-list — it JUDGES quality (neon +
    # restraint). The RO house palette's own colours must pass cleanly: no
    # neon, and they ARE the declared palette so nothing is off-palette.
    from research_os.tools.actions.audit.dashboard_content import audit_color_palette
    from research_os.tools.actions.viz.palettes import palette_hexes

    html = "".join(
        f"<span style='color:{c}'>x</span>"
        for c in sorted(palette_hexes("ro_house"))
    )
    res = audit_color_palette(html)
    assert res["blockers"] == [], res["blockers"]
    assert res["warnings"] == [], (
        f"RO house palette tripped {len(res['warnings'])} warnings"
    )


def test_audit_color_palette_full_dashboard_scaffold_passes():
    """End-to-end: the scaffold itself must pass audit_color_palette."""
    from research_os.tools.actions.audit.dashboard_content import (
        audit_color_palette,
    )
    from research_os.tools.actions.synthesis.scaffold import _DASHBOARD_HTML
    res = audit_color_palette(_DASHBOARD_HTML)
    assert res["warnings"] == [], (
        f"dashboard scaffold tripped palette audit: {res['warnings']}"
    )


# ---------------------------------------------------------------------------
# Protocol YAML updates
# ---------------------------------------------------------------------------


def _load_protocol(rel_path: str) -> dict:
    return yaml.safe_load((PROTOCOLS_DIR / rel_path).read_text()) or {}


def test_figure_guidelines_protocol_bumped():
    data = _load_protocol("visualization/figure_guidelines.yaml")
    parts = tuple(int(x) for x in str(data["version"]).split("."))
    assert parts >= (3, 0, 0)


def test_figure_guidelines_carries_style_preset_block():
    text = (PROTOCOLS_DIR / "visualization" / "figure_guidelines.yaml").read_text()
    assert "apply_research_os_style" in text
    assert "research_os_style_preset" in text
    # The first-render spacing discipline block exists and lists
    # the v1-not-v2 commitments.
    assert "first_render_spacing_discipline" in text
    # Render → view → v2 loop language.
    assert "render → view" in text or "render → open" in text or "view → v2" in text


def test_figure_guidelines_view_loop_is_mandatory():
    text = (PROTOCOLS_DIR / "visualization" / "figure_guidelines.yaml").read_text()
    # The protocol must NAME the open-the-PNG action explicitly so the
    # AI does it rather than just reading the script.
    assert "sys_file_read" in text or "OPEN the PNG" in text
    # And the loop must require v2 on failure.
    assert "v2" in text.lower()


def test_visualization_workflow_protocol_bumped():
    # The protocol must stay at or above the version where its
    # verify-render + style steps landed; later bumps are fine.
    data = _load_protocol("visualization/visualization_workflow.yaml")
    parts = tuple(int(x) for x in str(data["version"]).split("."))
    assert parts >= (3, 0, 0)


def test_visualization_workflow_has_verify_step():
    text = (
        PROTOCOLS_DIR / "visualization" / "visualization_workflow.yaml"
    ).read_text()
    assert "visually_verify_render" in text
    assert "apply_research_os_style" in text


def test_synthesis_dashboard_protocol_bumped():
    data = _load_protocol("synthesis/synthesis_dashboard.yaml")
    parts = tuple(int(x) for x in str(data["version"]).split("."))
    assert parts >= (3, 0, 0)


def test_synthesis_dashboard_references_style_helper():
    text = (
        PROTOCOLS_DIR / "synthesis" / "synthesis_dashboard.yaml"
    ).read_text()
    assert "apply_research_os_style" in text


# ---------------------------------------------------------------------------
# Scaffold round-trip (the v2.4.3 test of the dashboard scaffold path must
# still pass).
# ---------------------------------------------------------------------------


def test_synthesis_scaffold_dashboard_round_trips(tmp_path: Path):
    from research_os.tools.actions.synthesis.scaffold import synthesis_scaffold
    # confirmed=True bypasses the output_types intent gate (the gate is
    # tested separately in test_synthesis_check.py).
    out = synthesis_scaffold(tmp_path, kind="dashboard", confirmed=True)
    assert out["status"] == "success"
    target = tmp_path / "synthesis" / "dashboard.html"
    assert target.exists()
    body = target.read_text()
    assert "#FBF8F3" in body  # cream bg landed on disk
    assert "EB Garamond" in body  # serif stack landed
    assert "id=\"headline\"" in body  # section id preserved


# ---------------------------------------------------------------------------
# Version coherence
# ---------------------------------------------------------------------------


def test_version_files_coherent():
    """pyproject / CITATION / __init__ must all carry the canonical version.

    Reads research_os.__version__ as the single source of truth so this
    never needs a per-release edit (CLAUDE.md: all three must agree).
    """
    import research_os

    v = research_os.__version__
    checks = {
        "pyproject.toml": f'version = "{v}"',
        "CITATION.cff": f"version: {v}",
        "src/research_os/__init__.py": f'__version__ = "{v}"',
    }
    for file_rel, pattern in checks.items():
        body = (REPO_ROOT / file_rel).read_text()
        assert pattern in body, f"{file_rel} should contain {pattern!r}"


def test_changelog_has_current_entry():
    import research_os

    body = (REPO_ROOT / "CHANGELOG.md").read_text()
    current_version = research_os.__version__
    marker = f"## [{current_version}]"
    assert marker in body

    top_entry = body.split(marker, 1)[1]
    if "\n## [" in top_entry:
        top_entry = top_entry.split("\n## [", 1)[0]

    assert top_entry.lstrip().startswith("— The World-Class Architecture Overhaul (2026-07-08)")
    assert "### Added" in top_entry
    assert "### Improved" in top_entry
    assert "### Fixed / Removed" in top_entry
    assert "Documentation Drift Guard" not in top_entry
    assert "apply_research_os_style" not in top_entry
