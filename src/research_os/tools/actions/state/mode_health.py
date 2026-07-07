"""Mode-aware project-health checks for the daemon self-check.

The daemon's base self-check (structure, interrupted runs, intake, compliance)
is mode-agnostic. But what "healthy in-progress work" looks like differs by
workspace mode: a tool_build project needs its eval benchmark + inner repo, a
notebook project's notebooks should have run against the current data, a
multi_study program needs its shared codebook + roll-up keeping pace, an
exploration project shouldn't leave promote-worthy probes stranded in scratch.

This module computes those mode-specific signals BY SHAPE from disk
(stdlib-only, no daemon import — it lives reasoning-side so both the daemon
self-check AND tool_structure_audit can reuse it). Every check is read-only and
fail-open: any error yields no finding rather than raising.

Mode work-dir layout (all at PROJECT ROOT, not under workspace/, except
exploration's scratch): tool_build → spec/ decisions/ eval/ + inner project/;
notebook → notebooks/ data/ outputs/; multi_study → studies/ shared/ roll_up/;
hybrid → analysis spine + tool/; exploration → workspace/scratch.

Each finding: {severity, source='mode_health', message, code}.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _only_placeholder(p: Path) -> bool:
    """True if a dir contains nothing but the seeded README/template stubs."""
    try:
        if not p.is_dir():
            return False
        real = [
            f for f in p.iterdir()
            if f.name.lower() not in ("readme.md", ".gitkeep", ".gitignore")
        ]
        return len(real) == 0
    except Exception:
        return False


def _read_mode(root: Path) -> str:
    """Best-effort workspace mode read (defaults to 'analysis')."""
    # Prefer the canonical reader so we agree with the rest of the system
    # (handles quoting, state vs config precedence, etc.).
    try:
        from research_os.tools.actions.state.config import get_workspace_mode
        m = (get_workspace_mode(root) or "").strip()
        if m:
            return m
    except Exception:
        pass
    try:
        cfg = root / "inputs" / "researcher_config.yaml"
        if cfg.is_file():
            import re
            m = re.search(r'^\s*mode:\s*["\']?([a-z_]+)',
                          cfg.read_text(encoding="utf-8"), re.MULTILINE)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return "analysis"


def _f(sev: str, code: str, msg: str) -> dict[str, Any]:
    return {"severity": sev, "source": "mode_health", "message": msg, "code": code}


def _has_any(p: Path, pattern: str) -> bool:
    try:
        return p.is_dir() and any(p.glob(pattern))
    except Exception:
        return False


def _check_tool_build(root: Path) -> list[dict]:
    out: list[dict] = []
    # eval/ defines "done" — a tool_build project with no benchmark can't know
    # when it's finished. (work dirs live at project root.)
    evald = root / "eval"
    if evald.is_dir() and _only_placeholder(evald):
        out.append(_f("warn", "tool_build_no_eval",
                      "tool_build: eval/ has only the template — define the "
                      "benchmark that decides 'done' before building further."))
    spec = root / "spec"
    if spec.is_dir() and _only_placeholder(spec):
        out.append(_f("warn", "tool_build_no_spec",
                      "tool_build: spec/ has only the template — capture what the "
                      "tool must do (and not do) before implementing."))
    dec = root / "decisions"
    if dec.is_dir() and not _has_any(dec, "*.md"):
        out.append(_f("info", "tool_build_no_decisions",
                      "tool_build: no decision records yet — log key design "
                      "choices in decisions/ as ADRs so the rationale survives."))
    # The inner tool repo (project/) should exist + carry tests once building.
    proj = root / "project"
    if proj.is_dir() and any(proj.iterdir()):
        has_tests = _has_any(proj, "**/test_*.py") or _has_any(proj, "**/tests")
        has_code = _has_any(proj, "**/*.py") or _has_any(proj, "**/*.rs") \
            or _has_any(proj, "**/*.go") or _has_any(proj, "**/*.js")
        if has_code and not has_tests:
            out.append(_f("warn", "tool_build_no_tests",
                          "tool_build: the inner project/ has code but no tests "
                          "— a tool isn't 'done' until its eval/tests pass."))
    return out


def _check_notebook(root: Path) -> list[dict]:
    out: list[dict] = []
    nb = root / "notebooks"
    if not nb.is_dir():
        return out
    notebooks = list(nb.glob("*.ipynb")) + list(nb.glob("**/*.ipynb"))
    if not notebooks:
        out.append(_f("info", "notebook_none_yet",
                      "notebook mode: no notebooks in notebooks/ yet — create "
                      "one to start the analysis."))
        return out
    data_dir = root / "data"
    try:
        newest_data = max((p.stat().st_mtime for p in data_dir.rglob("*")
                           if p.is_file()), default=0.0) if data_dir.is_dir() else 0.0
        stale = [n.name for n in notebooks if n.stat().st_mtime < newest_data]
        if stale and newest_data > 0:
            out.append(_f("warn", "notebook_stale_vs_data",
                          f"notebook mode: {len(stale)} notebook(s) are older "
                          "than the data under data/ — re-run them so outputs "
                          "reflect the current inputs."))
    except Exception:
        pass
    return out


def _check_multi_study(root: Path) -> list[dict]:
    out: list[dict] = []
    studies = root / "studies"
    sub_dirs: list[Path] = []
    if studies.is_dir():
        sub_dirs = [d for d in studies.iterdir() if d.is_dir()]
        if not sub_dirs:
            out.append(_f("info", "multi_study_no_studies",
                          "multi_study: studies/ has no sub-studies yet — create "
                          "the first study to start the program."))
    shared = root / "shared"
    if shared.is_dir():
        if not _has_any(shared, "*"):
            out.append(_f("warn", "multi_study_no_shared",
                          "multi_study: shared/ is empty — define the program-wide "
                          "commons (codebook, preregistration, governing protocol) "
                          "so sub-studies stay comparable."))
        else:
            # The shared codebook is the thing that keeps sub-studies comparable —
            # verify it exists and isn't just a placeholder, not merely that
            # shared/ has *some* file.
            has_codebook = _has_any(shared, "codebook*") or _has_any(shared, "**/codebook*")
            if not has_codebook:
                out.append(_f("warn", "multi_study_no_codebook",
                              "multi_study: shared/ has no codebook — add a shared "
                              "codebook so every sub-study measures the same things "
                              "the same way."))
    # Roll-up staleness: if any sub-study has newer work than the newest file in
    # roll_up/, the cross-study synthesis has fallen behind.
    roll_up = root / "roll_up"
    if roll_up.is_dir() and sub_dirs:
        try:
            newest_study = max(
                (p.stat().st_mtime for d in sub_dirs for p in d.rglob("*")
                 if p.is_file()), default=0.0)
            newest_rollup = max(
                (p.stat().st_mtime for p in roll_up.rglob("*") if p.is_file()),
                default=0.0)
            if newest_study > 0 and newest_study > newest_rollup:
                out.append(_f("info", "multi_study_rollup_stale",
                              "multi_study: a sub-study has newer work than roll_up/ "
                              "— refresh the cross-study synthesis so it reflects the "
                              "latest results."))
        except Exception:
            pass
    return out


def _check_exploration(root: Path) -> list[dict]:
    out: list[dict] = []
    scratch = root / "workspace" / "scratch"
    if not scratch.is_dir():
        return out
    try:
        scratch_files = [p for p in scratch.rglob("*") if p.is_file()]
        import re
        ws = root / "workspace"
        promoted = [d for d in ws.iterdir()
                    if d.is_dir() and re.match(r"^\d{1,3}_", d.name)] if ws.is_dir() else []
        if len(scratch_files) >= 8 and not promoted:
            out.append(_f("info", "exploration_unpromoted",
                          "exploration: lots of scratch work but nothing promoted "
                          "to a numbered step yet — promote the probes that "
                          "panned out so the findings are kept + provenanced."))
    except Exception:
        pass
    return out


def _check_hybrid(root: Path) -> list[dict]:
    out: list[dict] = []
    # hybrid = analysis spine + a tool/ half. If the tool half has code but no
    # tests, the software side is unguarded.
    tool = root / "tool"
    if tool.is_dir() and any(tool.iterdir()):
        has_tests = _has_any(tool, "**/test_*.py") or _has_any(tool, "**/tests")
        has_code = _has_any(tool, "**/*.py") or _has_any(tool, "**/*.rs") \
            or _has_any(tool, "**/*.go")
        if has_code and not has_tests:
            out.append(_f("info", "hybrid_tool_untested",
                          "hybrid: the tool/ half has code but no tests — the "
                          "software side needs its own tests before the analysis "
                          "relies on it."))
    return out


def _check_analysis(root: Path) -> list[dict]:
    """Health checks for the default analysis (numbered-step) mode.

    Checks that the workspace has made meaningful progress: at least one
    numbered step exists once the project is past the intake stage, and
    that the synthesis dir hasn't been pre-populated with empty stubs.
    Fail-open: any missing directory or IO error silently returns nothing.
    """
    out: list[dict] = []
    ws = root / "workspace"
    if not ws.is_dir():
        return out
    try:
        import re
        steps = [d for d in ws.iterdir()
                 if d.is_dir() and re.match(r"^\d{1,3}_", d.name)]
        # Only warn once the intake exists (project has been started).
        intake = root / "inputs" / "intake.md"
        if intake.exists() and not steps:
            out.append(_f("info", "analysis_no_steps",
                          "analysis: intake exists but no numbered step "
                          "(workspace/NN_*) yet — create the first step to "
                          "start the analysis."))
        # Synthesis pre-populated before any steps are complete is likely
        # AI noise — surface it so the researcher can review.
        synthesis = root / "synthesis"
        if synthesis.is_dir() and not steps:
            real_syn = [f for f in synthesis.rglob("*") if f.is_file()
                        and f.name.lower() not in ("readme.md", ".gitkeep")]
            if real_syn:
                out.append(_f("info", "analysis_premature_synthesis",
                              "analysis: synthesis/ has content but no numbered "
                              "step has been completed yet — confirm the "
                              "deliverable is intentional at this stage."))
    except Exception:
        pass
    return out


_MODE_CHECKS = {
    "analysis": _check_analysis,
    "tool_build": _check_tool_build,
    "notebook": _check_notebook,
    "multi_study": _check_multi_study,
    "exploration": _check_exploration,
    "hybrid": _check_hybrid,
}


def mode_health_findings(root: Path, mode: str | None = None) -> list[dict]:
    """Return mode-specific health findings for the project (fail-open)."""
    try:
        root = Path(root)
        m = (mode or _read_mode(root)).strip()
        checker = _MODE_CHECKS.get(m)
        if checker is None:
            return []
        return checker(root)
    except Exception:
        return []
