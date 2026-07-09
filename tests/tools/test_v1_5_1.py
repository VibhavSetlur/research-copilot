"""v1.5.1 regression tests.

Covers:

* Theme 3 — rigor_signals_scan (trust_score 0-100 + recommended_strictness)
* Theme 3 — resolve_gate_strictness honours researcher_config override + auto
* Theme 3 — self_certify persists + has_active_certification matches scope
* Theme 3 — step_has_skip_annotation honours `<!-- ro:skip lit_loop -->`
* Theme 5 — detect_quick_intent matches each documented trigger
* Theme 5 — quick_route shape (is_quick + complexity='quick')
* Theme 5 — promote_to_step creates a numbered step with provenance
* Theme 5 — project_tier_strictness throwaway -> light mapping
"""

from __future__ import annotations


import yaml

from research_os.project_ops import scaffold_minimal_workspace


# ---------------------------------------------------------------------------
# Theme 3 — rigor signals
# ---------------------------------------------------------------------------


def test_rigor_signals_scan_strict_on_empty_project(tmp_path):
    """A bare workspace should score low and recommend strict gates."""
    from research_os.tools.actions.state.rigor_signals import rigor_signals_scan

    scaffold_minimal_workspace(tmp_path, "Test")
    res = rigor_signals_scan(tmp_path)
    assert res["status"] == "success"
    assert 0 <= res["trust_score"] <= 100
    assert res["trust_score"] < 50, (
        f"empty project should score <50; got {res['trust_score']}"
    )
    assert res["recommended_strictness"] == "strict"
    assert len(res["signals"]) == 6  # methods, citations, git, prereg, scripts, summaries


def test_rigor_signals_scan_light_on_well_set_project(tmp_path):
    """A project with methods.md + citations + git + preregistration should
    score high and recommend light gates."""
    from research_os.tools.actions.state.rigor_signals import rigor_signals_scan

    scaffold_minimal_workspace(tmp_path, "Test")
    # Substantive methods.md
    methods = tmp_path / "workspace" / "methods.md"
    methods.write_text(
        "# Methods\n\n"
        + "- Cohort recruitment per (Smith 2024) protocol with explicit IRB approval.\n"
        + "- Sample preparation followed (Doe 2022) standard procedures with two modifications.\n"
        + "- Statistical analysis pre-registered at OSF; primary endpoint per (Lee 2023).\n"
        + "- Sensitivity tests covered three robustness checks per (Patel 2021).\n"
        + "- Multiple-comparison adjustment via Benjamini-Hochberg at FDR 0.05.\n"
        + "Detailed description of every analytic choice, " * 30
    )
    # Citations
    (tmp_path / "workspace" / "citations.md").write_text(
        "\n".join(f"- Citation entry {i} body text" for i in range(20))
    )
    # PDFs
    pdf_dir = tmp_path / "inputs" / "literature"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for i in range(12):
        (pdf_dir / f"paper_{i}.pdf").write_bytes(b"%PDF-1.4\n")
    # Git
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    # Preregistration
    (tmp_path / "preregistration.md").write_text("# Preregistration\n\nAims, hypotheses, analysis plan.\n")
    # Heavy-comment script + substantive step summary
    step = tmp_path / "workspace" / "02_eda"
    (step / "scripts").mkdir(parents=True)
    (step / "scripts" / "eda.py").write_text(
        "# Comment line\n" * 12 + "x = 1\ny = 2\nz = 3\n"
    )
    (step / "step_summary.yaml").write_text(yaml.safe_dump({
        "step_id": "02_eda",
        "findings": "Detailed substantive findings prose " * 20,
        "decision": "Detailed substantive decision prose " * 20,
        "literature": {"claims_grounded": 3},
    }))

    res = rigor_signals_scan(tmp_path)
    assert res["status"] == "success"
    assert res["trust_score"] >= 50, (
        f"well-set project should score >=50; got {res['trust_score']}"
    )


def test_resolve_gate_strictness_config_wins(tmp_path):
    """researcher_config.gate_strictness=strict short-circuits trust_score."""
    from research_os.tools.actions.state.rigor_signals import resolve_gate_strictness

    scaffold_minimal_workspace(tmp_path, "Test")
    cfg_path = tmp_path / "inputs" / "researcher_config.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump({
        "gate_strictness": "strict",
    }))

    res = resolve_gate_strictness(tmp_path)
    assert res["resolved"] == "strict"
    assert res["source"] == "config"

    # auto follows trust score (low on empty project)
    cfg_path.write_text(yaml.safe_dump({
        "gate_strictness": "auto",
    }))
    res_auto = resolve_gate_strictness(tmp_path)
    assert res_auto["resolved"] == "strict"
    assert res_auto["source"] == "auto"


def test_self_certify_persists_and_matches_scope(tmp_path):
    """self_certify writes the cert; has_active_certification picks it up by scope."""
    from research_os.tools.actions.state.certifications import (
        has_active_certification,
        list_certifications,
        self_certify,
    )

    scaffold_minimal_workspace(tmp_path, "Test")

    res = self_certify(
        tmp_path,
        domain="literature_loop",
        scope="all steps",
        rationale="Researcher conducted full systematic review off-platform last month.",
    )
    assert res["status"] == "success"
    assert res["active_count"] == 1

    listed = list_certifications(tmp_path)
    assert listed["count"] == 1

    # Scope = 'all steps' matches any step.
    check = has_active_certification(tmp_path, "literature_loop", step_id="03_eda")
    assert check["active"] is True

    # Bad domain rejected.
    bad = self_certify(tmp_path, domain="unknown_thing", scope="all", rationale="x")
    assert bad["status"] == "error"

    # Empty rationale rejected.
    bad2 = self_certify(tmp_path, domain="stack_plan", scope="step 02", rationale="")
    assert bad2["status"] == "error"


def test_step_skip_annotation_recognised(tmp_path):
    """conclusions.md with `<!-- ro:skip lit_loop, reason: ... -->` is detected."""
    from research_os.tools.actions.state.certifications import step_has_skip_annotation

    scaffold_minimal_workspace(tmp_path, "Test")
    step = tmp_path / "workspace" / "03_eda"
    step.mkdir(parents=True)
    (step / "conclusions.md").write_text(
        "## Findings\n\n"
        "<!-- ro:skip lit_loop, reason: project-wide review already done -->\n\n"
        "Substantive findings here.\n"
    )

    res = step_has_skip_annotation(tmp_path, "03_eda", "lit_loop")
    assert res["has_skip"] is True
    assert "project-wide" in res["reason"]

    # Non-matching gate name should NOT match.
    res2 = step_has_skip_annotation(tmp_path, "03_eda", "stack_plan")
    assert res2["has_skip"] is False


# ---------------------------------------------------------------------------
# Theme 5 — quick mode
# ---------------------------------------------------------------------------


def test_detect_quick_intent_matches_triggers():
    """Each documented quick trigger is detected; unrelated prompts are not."""
    from research_os.tools.actions.state.quick_mode import detect_quick_intent

    triggers = [
        "Just make me a plot of cohort age",
        "Sanity check on the file",
        "Exploratory only — see what the data looks like",
        "Quick look at the demographics",
        "Throwaway viz",
        "Quick check on QC",
        "Scratch idea: try clustering",
    ]
    for t in triggers:
        res = detect_quick_intent(t)
        assert res["is_quick"] is True, f"failed to detect: {t!r}"

    # Real research intent — must NOT match.
    not_quick = [
        "Run the full DE analysis with sensitivity",
        "Draft the methods section using the canonical pipeline",
        "Audit every step's literature coverage",
    ]
    for n in not_quick:
        res = detect_quick_intent(n)
        assert res["is_quick"] is False, f"false-positive on {n!r}"


def test_quick_route_returns_quick_complexity(tmp_path):
    """quick_route shape matches what tool_route expects to return verbatim."""
    from research_os.tools.actions.state.quick_mode import quick_route

    scaffold_minimal_workspace(tmp_path, "Test")
    res = quick_route(tmp_path, "Just make me a quick plot for sanity")
    assert res["is_quick"] is True
    assert res["complexity"] == "quick"
    assert res["recommended_tool"] == "tool_scratch_write"
    assert "scratch" in res["output_dir"]
    # scratch dir created
    assert (tmp_path / "workspace" / "scratch").is_dir()


def test_promote_to_step_wraps_scratch_in_provenance(tmp_path):
    """promote_to_step creates a numbered step with sidecar + summary."""
    from research_os.tools.actions.state.quick_mode import promote_to_step

    scaffold_minimal_workspace(tmp_path, "Test")
    scratch_dir = tmp_path / "workspace" / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch_fig = scratch_dir / "exploration_v1.png"
    scratch_fig.write_bytes(b"\x89PNG\r\n")

    res = promote_to_step(
        tmp_path,
        scratch_path="workspace/scratch/exploration_v1.png",
        step_slug="exploration_makes_the_cut",
        rationale="Scratch plot revealed a real cohort split worth a proper step.",
    )
    assert res["status"] == "success"
    step_id = res["step_id"]
    assert step_id.startswith("01_") or step_id.startswith("02_")
    step_path = tmp_path / res["step_dir"]
    assert step_path.is_dir()
    assert (step_path / "conclusions.md").exists()
    # step_summary.yaml retired in 3.2 — conclusions.md is the source of truth.
    assert not (step_path / "step_summary.yaml").exists()
    prov = tmp_path / res["provenance_file"]
    assert prov.exists()
    # Original scratch still there (copy, not move).
    assert scratch_fig.exists()


def test_project_tier_strictness_throwaway(tmp_path):
    """project_tier=throwaway resolves to gate_strictness=light."""
    from research_os.tools.actions.state.quick_mode import project_tier_strictness

    scaffold_minimal_workspace(tmp_path, "Test")
    cfg_path = tmp_path / "inputs" / "researcher_config.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump({
        "project_tier": "throwaway",
    }))

    res = project_tier_strictness(tmp_path)
    assert res["status"] == "success"
    assert res["project_tier"] == "throwaway"
    assert res["default_gate_strictness"] == "light"

    # production -> strict
    cfg_path.write_text(yaml.safe_dump({
        "project_tier": "production",
    }))
    res2 = project_tier_strictness(tmp_path)
    assert res2["default_gate_strictness"] == "strict"


# ---------------------------------------------------------------------------
# Router integration — tool_route returns complexity=quick on quick intents
# ---------------------------------------------------------------------------


def test_tool_route_returns_quick_complexity_on_throwaway_prompt(tmp_path):
    """The hierarchical router short-circuits to complexity='quick'."""
    from research_os.tools.actions.router import route_request

    scaffold_minimal_workspace(tmp_path, "Test")
    res = route_request(
        "Just make me a quick plot of the age distribution",
        tmp_path,
        persist_plan=False,
    )
    assert res["status"] == "success"
    assert res["complexity"] == "quick"
    assert res["shortcut_tool"] == "tool_scratch_write"
    assert res["intent_class"] == "quick"
