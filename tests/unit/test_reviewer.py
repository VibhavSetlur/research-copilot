"""Reviewer-response scaffold tests — draft, compile, audit."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_os.tools.actions.synthesis.reviewer import (
    DEFAULT_PERSONAS,
    audit_reviewer_responses,
    rebuttal_draft,
    reviewer_response_compile,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _scaffold_project(root: Path, with_paper: bool = True) -> None:
    """Minimal Research-OS-shaped project root."""
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    (root / "synthesis").mkdir(parents=True, exist_ok=True)
    if with_paper:
        (root / "synthesis" / "paper.md").write_text(
            "# A study of widgets\n\n"
            "## Abstract\nWe found things.\n\n"
            "## Methods\nWe did analysis.\n\n"
            "## Results\nNumbers were computed.\n\n"
            "## Discussion\nThis matters.\n\n"
            "## References\n[1] Doe 2024.\n",
            encoding="utf-8",
        )
    # Methods record + one step with findings_vs_literature + outputs.
    (root / "workspace" / "methods.md").write_text(
        "# Methods\nWe used a t-test.\n", encoding="utf-8"
    )
    step = root / "workspace" / "01_eda"
    (step / "literature").mkdir(parents=True, exist_ok=True)
    (step / "literature" / "findings_vs_literature.md").write_text(
        "# Findings vs literature\n\n## CONFIRMS\nSmith 2019.\n", encoding="utf-8"
    )
    figs = step / "outputs" / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    (figs / "fig1.png").write_text("PNG", encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _scaffold_project(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# rebuttal_draft
# ---------------------------------------------------------------------------


def test_rebuttal_draft_writes_expected_file(project):
    res = rebuttal_draft(
        project,
        comment="The reported effect lacks a confidence interval.",
        persona="statistician",
    )
    assert res["status"] == "success"
    out = project / res["rebuttal_path"]
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "# Rebuttal" in text
    assert "Statistician" in text
    assert "Reviewer comment" in text
    assert "confidence interval" in text
    assert "Evidence" in text


def test_rebuttal_draft_flags_missing_supplied_evidence(project):
    res = rebuttal_draft(
        project,
        comment="Where is the figure?",
        persona="presentation_critic",
        evidence_paths=["workspace/does_not_exist.md"],
    )
    assert res["status"] == "success"
    assert "workspace/does_not_exist.md" in res["evidence_missing"]
    text = (project / res["rebuttal_path"]).read_text(encoding="utf-8")
    assert "do not exist on disk" in text


def test_rebuttal_draft_surfaces_existing_evidence(project):
    res = rebuttal_draft(
        project,
        comment="Show me the methods record.",
        persona="reproducibility_advocate",
        evidence_paths=["workspace/methods.md"],
    )
    assert res["evidence_supplied"] == ["workspace/methods.md"]
    text = (project / res["rebuttal_path"]).read_text(encoding="utf-8")
    assert "workspace/methods.md" in text


def test_rebuttal_draft_rejects_empty_comment(project):
    res = rebuttal_draft(project, comment="", persona="statistician")
    assert res["status"] == "error"


def test_rebuttal_draft_rejects_unknown_persona(project):
    res = rebuttal_draft(
        project, comment="anything", persona="not_a_real_persona"
    )
    assert res["status"] == "error"


# ---------------------------------------------------------------------------
# reviewer_response_compile
# ---------------------------------------------------------------------------


def test_compile_errors_when_no_rebuttals(project):
    res = reviewer_response_compile(project)
    assert res["status"] == "error"


def test_compile_produces_markdown_response(project):
    rebuttal_draft(
        project,
        comment="Effect lacks CI.",
        persona="statistician",
    )
    rebuttal_draft(
        project,
        comment="No DOI for the data.",
        persona="reproducibility_advocate",
    )
    res = reviewer_response_compile(project)
    assert res["status"] == "success"
    assert res["rebuttal_count"] == 2
    md = project / res["response_md"]
    assert md.exists()
    text = md.read_text(encoding="utf-8")
    assert "Response to reviewers" in text
    assert "Statistician" in text
    assert "Reproducibility Advocate" in text


def test_compile_pdf_when_typst_available(project):
    """When typst is on PATH, the PDF compiles; otherwise PDF is skipped
    but the markdown is still non-empty."""
    rebuttal_draft(project, comment="X.", persona="statistician")
    res = reviewer_response_compile(project)
    assert res["status"] == "success"
    md_text = (project / res["response_md"]).read_text(encoding="utf-8")
    assert len(md_text.strip()) > 0, "response markdown is empty"
    import shutil as _sh
    if _sh.which("typst"):
        if res.get("response_pdf"):
            pdf_path = project / res["response_pdf"]
            assert pdf_path.exists() and pdf_path.stat().st_size > 0, (
                "typst is on PATH but PDF was not produced / is empty"
            )


# ---------------------------------------------------------------------------
# audit_reviewer_responses
# ---------------------------------------------------------------------------


def _write_rebuttal(project: Path, name: str, body: str) -> Path:
    out = project / "workspace" / "reviewer" / "rebuttals" / f"{name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out


def test_audit_warns_when_no_rebuttals(project):
    res = audit_reviewer_responses(project)
    assert res["status"] == "warning"
    assert res["audited"] == 0


def test_audit_flags_handwaving(project):
    _write_rebuttal(
        project,
        "statistician_handwave",
        "# Rebuttal — Statistician\n\n## Reviewer comment\n> Effect lacks CI.\n\n"
        "## Response\nWe believe the result is robust and future work "
        "will address this concern.\n\n"
        "## Evidence\n- `workspace/methods.md`\n",
    )
    res = audit_reviewer_responses(project)
    assert res["status"] == "warning"
    assert res["failed"] >= 1
    issues = res["warnings"][0]["issues"]
    assert any("hand-waving" in i for i in issues)


def test_audit_flags_missing_evidence(project):
    _write_rebuttal(
        project,
        "novelty_critic_no_evidence",
        "# Rebuttal\n\n## Reviewer comment\n> No novelty.\n\n"
        "## Response\nWe agree and have revised the introduction.\n\n"
        "## Evidence\nNone applicable.\n",
    )
    res = audit_reviewer_responses(project)
    assert res["status"] == "warning"
    issues = res["warnings"][0]["issues"]
    assert any("no evidence path cited" in i for i in issues)


def test_audit_passes_on_well_cited_rebuttal(project):
    _write_rebuttal(
        project,
        "statistician_cited",
        "# Rebuttal — Statistician\n\n## Reviewer comment\n> Effect lacks CI.\n\n"
        "## Response\nWe agree. The revised Results section now reports the "
        "95% CI (0.21, 0.43) alongside the point estimate; see "
        "`workspace/01_eda/outputs/figures/fig1.png` and the regenerated "
        "table in `workspace/methods.md`.\n\n"
        "## Evidence\n- `workspace/methods.md`\n"
        "- `workspace/01_eda/outputs/figures/fig1.png`\n",
    )
    res = audit_reviewer_responses(project)
    assert res["status"] == "success"
    assert res["passed"] == 1
    assert res["failed"] == 0


def test_audit_writes_report(project):
    _write_rebuttal(
        project,
        "statistician_x",
        "# Rebuttal\n\n## Reviewer comment\n> X\n\n## Response\nObviously the "
        "result holds.\n\n## Evidence\n`workspace/methods.md`\n",
    )
    audit_reviewer_responses(project)
    report = project / "workspace" / "reviewer" / "audit_report.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Reviewer-response audit" in text


# ---------------------------------------------------------------------------
# Protocol YAML parses
# ---------------------------------------------------------------------------


def test_reviewer_response_protocol_yaml_parses():
    proto_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "research_os"
        / "protocols"
        / "synthesis"
        / "reviewer_response.yaml"
    )
    assert proto_path.exists()
    data = yaml.safe_load(proto_path.read_text(encoding="utf-8"))
    assert data["id"] == "reviewer_response"
    assert data["schema_version"] == "3.0"
    assert "steps" in data and len(data["steps"]) >= 5
    # Every step has an id + description.
    for s in data["steps"]:
        assert s.get("id")
        assert s.get("description")
