"""3.2.8 — the composable visual-design system (palettes + layout archetypes).

Locks the contract that the dashboard/poster scaffolds are a SELECTABLE design
system (archetype + palette), not one fixed template, and that the shared
palette module is internally consistent + professional (AA contrast, no neon).
"""
from __future__ import annotations

import tempfile
from pathlib import Path


from research_os.tools.actions.synthesis import scaffold as S
from research_os.tools.actions.viz import palettes as P


# -- palette module ----------------------------------------------------------


def test_three_professional_palettes_present():
    assert set(P.PALETTES) >= {"ro_house", "okabe_ito", "clinical"}
    assert P.DEFAULT_PALETTE in P.PALETTES


def test_every_palette_fg_passes_aa_on_its_ground():
    """Body text (fg) on the page ground must clear WCAG AA (4.5:1) in BOTH
    light and dark schemes for every shipped palette."""
    for name, p in P.PALETTES.items():
        for scheme in ("light", "dark"):
            ratio = P.contrast_ratio(p[scheme]["fg"], p[scheme]["ground"])
            assert ratio >= 4.5, f"{name}/{scheme} fg-on-ground only {ratio:.2f}:1"


def test_no_palette_accent_is_neon():
    """A professional palette never ships a neon accent."""
    for name, p in P.PALETTES.items():
        for scheme in ("light", "dark"):
            for key in ("primary", "secondary", "positive", "negative", "fifth"):
                assert not P.is_neon(p[scheme][key]), f"{name}/{scheme}/{key} is neon"


def test_neon_and_neutral_predicates():
    assert P.is_neon("#00FF00")   # pure green = neon
    assert P.is_neon("#FF00FF")   # magenta = neon
    assert not P.is_neon("#1F4D7A")  # RO navy = not neon
    assert P.is_near_neutral("#3D3A35")   # warm grey
    assert not P.is_near_neutral("#1F4D7A")  # navy has hue


def test_banned_colormaps_cover_rainbow_family():
    for cm in ("jet", "turbo", "rainbow", "hsv"):
        assert cm in P.BANNED_COLORMAPS


def test_allowed_chart_hexes_includes_palettes_and_ramps():
    allowed = P.all_allowed_chart_hexes()
    assert "#1f4d7a" in allowed            # RO navy
    assert "#0072b2" in allowed            # Okabe-Ito blue
    assert "#440154" in allowed            # viridis anchor


# -- dashboard archetype system ---------------------------------------------


def test_dashboard_has_four_archetypes():
    assert set(S.DASHBOARD_ARCHETYPES) == {
        "single-viewport-brief", "scroll-lite-narrative",
        "comparison-scorecard", "multi-panel-exploratory",
    }


def test_scroll_lite_requires_in_page_nav():
    html = S._compose_dashboard("scroll-lite-narrative")
    assert 'class="dash-nav"' in html, "scroll-lite archetype must ship in-page nav"


def test_single_viewport_brief_has_no_nav():
    html = S._compose_dashboard("single-viewport-brief")
    assert 'class="dash-nav"' not in html, "single-viewport brief must NOT scroll/nav"


def test_comparison_scorecard_has_scorecard_table():
    html = S._compose_dashboard("comparison-scorecard")
    assert 'class="scorecard"' in html


def test_multi_panel_has_panel_grid():
    html = S._compose_dashboard("multi-panel-exploratory")
    assert 'class="panel-grid"' in html


# -- poster archetype system -------------------------------------------------


def test_poster_has_four_archetypes():
    assert set(S.POSTER_ARCHETYPES) == {"classic", "billboard", "hero", "portrait"}


def test_poster_compose_substitutes_palette():
    for arch in S.POSTER_ARCHETYPES:
        typ = S._compose_poster(arch, "clinical")
        assert "__POSTER_PALETTE__" not in typ
        assert 'palette: "clinical"' in typ


def test_billboard_uses_asymmetric_grid_preset():
    assert "poster-billboard" in S._compose_poster("billboard")


# -- scaffold validation -----------------------------------------------------


def _root():
    r = Path(tempfile.mkdtemp())
    (r / "inputs").mkdir()
    return r


def test_scaffold_rejects_unknown_archetype():
    res = S.synthesis_scaffold(_root(), "dashboard", confirmed=True, archetype="nope")
    assert res["status"] == "error" and "archetype" in res["message"]


def test_scaffold_rejects_unknown_palette():
    res = S.synthesis_scaffold(_root(), "dashboard", confirmed=True, palette="nope")
    assert res["status"] == "error" and "palette" in res["message"]


def test_scaffold_rejects_archetype_on_kind_without_one():
    res = S.synthesis_scaffold(_root(), "paper", confirmed=True, archetype="classic")
    assert res["status"] == "error"


def test_scaffold_dashboard_reports_archetype_and_writes():
    res = S.synthesis_scaffold(
        _root(), "dashboard", confirmed=True, archetype="comparison-scorecard", palette="clinical"
    )
    assert res["status"] == "success"
    assert res["archetype"] == "comparison-scorecard"
    assert res["palette"] == "clinical"
    assert Path(res["path"]).read_text(encoding="utf-8").count('data-archetype="comparison-scorecard"') == 1
