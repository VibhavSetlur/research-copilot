"""Wizard UX hardening: identity validation + early already-exists exit."""
from __future__ import annotations

import types

import pytest

from research_os import wizard


def test_email_regex():
    assert wizard._EMAIL_RE.match("a@b.co")
    assert not wizard._EMAIL_RE.match("not-an-email")
    assert not wizard._EMAIL_RE.match("a@b")


def test_orcid_regex():
    assert wizard._ORCID_RE.match("0000-0002-1825-0097")
    assert wizard._ORCID_RE.match("0000-0002-1825-009X")
    assert not wizard._ORCID_RE.match("1825-0097")


def test_prompt_validated_reprompts_then_accepts(monkeypatch):
    answers = iter(["garbage", "you@uni.edu"])
    monkeypatch.setattr(wizard.tui, "text", lambda *a, **k: next(answers))
    out = wizard._prompt_validated("Email", wizard._EMAIL_RE, "you@uni.edu")
    assert out == "you@uni.edu"


def test_prompt_validated_blank_accepts(monkeypatch):
    monkeypatch.setattr(wizard.tui, "text", lambda *a, **k: "")
    assert wizard._prompt_validated("ORCID", wizard._ORCID_RE, "0000-...") == ""


def test_run_wizard_exits_early_when_already_initialized(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / ".os_state").mkdir(parents=True)
    monkeypatch.setattr(wizard.logo, "render", lambda **k: "")
    args = types.SimpleNamespace(directory=str(root), force=False, name=None)
    with pytest.raises(SystemExit) as exc:
        wizard.run_wizard(args)
    assert exc.value.code == 1


def test_slugify_empty_falls_back():
    """A name with no slug-safe chars must fall back, not yield '---'.
    (CWC-2)"""
    assert wizard.slugify("!!!") == "research-project"
    assert wizard.slugify("   ") == "research-project"
    assert wizard.slugify("My Cool Project!") == "my-cool-project"
    assert wizard.slugify("---") == "research-project"


def test_wizard_docstring_is_3_step():
    """Docstring must say '3-step', not the old '7-step'."""
    assert "3-step" in wizard.__doc__
    assert "7-step" not in wizard.__doc__


def test_wizard_result_has_output_types_and_venue():
    """WizardResult must carry the new Step-2 fields with correct defaults."""
    r = wizard.WizardResult(
        target_dir=__import__("pathlib").Path("/tmp"),
        project_name="test",
        domain="",
        question="",
        questions=[],
        ides=[],
        force=False,
        run_verify=False,
        start_server=False,
        create_dir_needed=False,
    )
    assert r.output_types == ["paper", "figures"]
    assert r.target_venue == ""
