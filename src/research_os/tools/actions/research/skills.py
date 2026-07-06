"""Self-improving skill distillation.

Research OS already records Reflexion-style lessons after each step
(``research/lessons.py`` → ``workspace/.lessons/lessons.jsonl``) and
surfaces the top-K relevant ones on future turns. That loop is
*per-project* and *per-turn*: it never crystallizes a recurring pattern
into a durable, reusable procedure, and it never carries what the AI
learned about THIS researcher into the NEXT project.

This module closes both gaps:

  1. ``distill_skills(root)`` — cluster the project's lessons by tag,
     find patterns that recur at or above a frequency threshold, and
     crystallize each cluster into a reusable SKILL.md under
     ``workspace/.skills/``. A skill is a distilled "when you hit X,
     do Y (it worked) / avoid Z (it didn't)" card — procedural memory,
     not a one-off lesson.

  2. ``promote_skills(root)`` — lift the project-wide / methodology
     skills into the cross-project profile
     (``~/.config/research-os/profile.yaml`` → ``learned_skills``), so
     the SAME researcher starting a NEW project inherits what RO learned.
     This is the two-way learning surface: lessons flow up into the
     profile; ``research-os init`` reads the profile back down.

Design constraints (mirrors lessons.py):
  * Pure stdlib + yaml. No network, no model call — distillation is a
    deterministic aggregation the AI can trigger and then narrate.
  * Idempotent: re-running updates existing skill cards in place
    (keyed by a stable slug) instead of duplicating them.
  * Conservative: only patterns seen ``min_occurrences`` times become
    skills, so noise doesn't pollute the registry.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("research_os.skills")

_DEFAULT_MIN_OCCURRENCES = 2
_SKILL_VERSION = "1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lessons_log(root: Path) -> Path:
    """Return the path to read lessons from (new canonical path, or legacy fallback)."""
    from research_os.tools.actions.research.lessons import _lessons_read_path
    return _lessons_read_path(root)


def _skills_dir(root: Path) -> Path:
    p = root / "workspace" / ".skills"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_lessons(root: Path) -> list[dict[str, Any]]:
    p = _lessons_log(root)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "general"


def _cluster_lessons(
    lessons: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group lessons by their primary tag (first tag), or 'general'.

    Tag-based clustering matches how lessons_consult ranks by tag overlap,
    so a distilled skill aligns with the retrieval key the AI already uses.
    """
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lesson in lessons:
        tags = lesson.get("tags") or []
        key = tags[0] if tags else "general"
        clusters[key].append(lesson)
    return clusters


def _render_skill_md(
    tag: str,
    cluster: list[dict[str, Any]],
) -> tuple[str, str]:
    """Render a SKILL.md (frontmatter + body) for a tag cluster.

    Returns (slug, markdown). The format is Hermes-compatible
    (YAML frontmatter: name / description / version / metadata) so the
    same file can be installed into a Hermes skills dir verbatim.
    """
    slug = _slug(tag)
    worked = [c.get("what_worked", "").strip() for c in cluster if c.get("what_worked", "").strip()]
    didnt = [c.get("what_didnt", "").strip() for c in cluster if c.get("what_didnt", "").strip()]
    recs = [c.get("recommendation", "").strip() for c in cluster if c.get("recommendation", "").strip()]
    n_fail = sum(1 for c in cluster if c.get("outcome") == "failure")
    # Dedupe while preserving order.
    def _uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for it in items:
            k = it.lower()
            if k not in seen:
                seen.add(k)
                out.append(it)
        return out

    worked, didnt, recs = _uniq(worked), _uniq(didnt), _uniq(recs)
    desc = (
        f"Distilled from {len(cluster)} lesson(s) ({n_fail} failure) tagged "
        f"'{tag}'. When working on {tag}-related steps, apply these."
    )
    fm = [
        "---",
        f"name: ro-{slug}",
        f"description: {json.dumps(desc)}",
        f"version: {_SKILL_VERSION}",
        "author: research-os (auto-distilled)",
        "license: project-local",
        "metadata:",
        "  source: research-os/lessons",
        f"  tag: {json.dumps(tag)}",
        f"  lessons_count: {len(cluster)}",
        f"  failures: {n_fail}",
        f"  distilled_at: {json.dumps(_now())}",
        "  hermes:",
        f"    tags: {json.dumps([tag, 'research-os', 'distilled'])}",
        "---",
    ]
    body = [f"# Skill: {tag}", ""]
    body.append(
        f"Crystallized from {len(cluster)} recorded lesson(s) on '{tag}'. "
        "This is procedural memory — consult it before repeating the pattern.\n"
    )
    if recs:
        body.append("## Do this")
        body.extend(f"- {r}" for r in recs)
        body.append("")
    if worked:
        body.append("## What worked")
        body.extend(f"- {w}" for w in worked)
        body.append("")
    if didnt:
        body.append("## What to avoid")
        body.extend(f"- {d}" for d in didnt)
        body.append("")
    return slug, "\n".join(fm) + "\n\n" + "\n".join(body).rstrip() + "\n"


def distill_skills(
    root: Path,
    *,
    min_occurrences: int = _DEFAULT_MIN_OCCURRENCES,
) -> dict[str, Any]:
    """Crystallize recurring lessons into reusable SKILL.md cards.

    A tag cluster becomes a skill when it has >= ``min_occurrences``
    lessons. Idempotent: rewrites the slug's card each run.
    """
    lessons = _read_lessons(root)
    if not lessons:
        return {
            "status": "success",
            "skills_written": 0,
            "skills": [],
            "advice": "No lessons recorded yet — nothing to distill. "
            "Record lessons with tool_lessons(operation='record') as you work.",
        }
    clusters = _cluster_lessons(lessons)
    skills_dir = _skills_dir(root)
    written: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for tag, cluster in sorted(clusters.items()):
        if len(cluster) < min_occurrences:
            skipped.append({"tag": tag, "count": len(cluster)})
            continue
        slug, md = _render_skill_md(tag, cluster)
        path = skills_dir / f"{slug}.SKILL.md"
        path.write_text(md)
        written.append({
            "tag": tag,
            "slug": slug,
            "path": str(path.relative_to(root)),
            "lessons_count": len(cluster),
        })
    return {
        "status": "success",
        "skills_written": len(written),
        "skills": written,
        "skipped_below_threshold": skipped,
        "min_occurrences": min_occurrences,
        "skills_dir": str(skills_dir.relative_to(root)),
        "advice": (
            f"Distilled {len(written)} skill(s) into {skills_dir.name}/. "
            "Call tool_skills(operation='promote') to lift the durable ones "
            "into your cross-project profile so future projects inherit them."
            if written
            else "No tag cluster reached the threshold yet. Keep recording "
            f"lessons — patterns seen {min_occurrences}+ times become skills."
        ),
    }


def promote_skills(
    root: Path,
    *,
    min_occurrences: int = _DEFAULT_MIN_OCCURRENCES,
    write_hermes_cards: bool = True,
) -> dict[str, Any]:
    """Promote project-wide / methodology skills into the cross-project profile.

    Lessons scoped ``project`` or ``methodology`` are the ones worth
    carrying across projects (a ``step``-scoped lesson is usually too
    local). Their distilled cards are stored under ``learned_skills`` in
    ``~/.config/research-os/profile.yaml`` keyed by slug, so
    ``research-os init`` can surface them in the next project.

    Self-improvement loop: when ``write_hermes_cards`` is true and a Hermes
    skills dir exists (``~/.hermes/skills/``), each promoted lesson is ALSO
    written as a real SKILL.md card there (under ``research-os-learned/``) so
    Hermes can actually LOAD it as a skill on the next project — not just read
    it from RO's profile. This is how the researcher's accumulated know-how
    becomes part of the agent's pullable skill set over time.
    """
    from research_os.tools.actions.state.config import (
        load_profile,
        save_profile,
    )

    lessons = [
        lesson for lesson in _read_lessons(root)
        if lesson.get("scope") in {"project", "methodology"}
    ]
    if not lessons:
        return {
            "status": "success",
            "promoted": 0,
            "advice": "No project/methodology-scoped lessons to promote. "
            "Cross-project learning lifts durable lessons (scope='project' "
            "or 'methodology'), not step-local ones.",
        }
    clusters = _cluster_lessons(lessons)
    profile = load_profile()
    learned = profile.get("learned_skills")
    if not isinstance(learned, dict):
        learned = {}
    promoted: list[dict[str, Any]] = []
    for tag, cluster in sorted(clusters.items()):
        if len(cluster) < min_occurrences:
            continue
        slug = _slug(tag)
        recs = sorted({
            c.get("recommendation", "").strip()
            for c in cluster
            if c.get("recommendation", "").strip()
        })
        entry = {
            "tag": tag,
            "recommendations": recs,
            "lessons_count": len(cluster),
            "updated_at": _now(),
        }
        # Merge: accumulate the max lessons_count seen, union recs.
        prior = learned.get(slug)
        if isinstance(prior, dict):
            prior_recs = prior.get("recommendations") or []
            entry["recommendations"] = sorted(set(recs) | set(prior_recs))
            entry["lessons_count"] = max(
                len(cluster), int(prior.get("lessons_count", 0) or 0)
            )
        learned[slug] = entry
        promoted.append({"slug": slug, "tag": tag, "lessons_count": len(cluster)})
    profile["learned_skills"] = learned
    save_res = save_profile(profile)

    # Self-improvement loop: write promoted lessons as loadable Hermes SKILL.md
    # cards so the agent can actually pull them next project (best-effort).
    hermes_cards: list[str] = []
    if write_hermes_cards and promoted:
        try:
            import os
            # Honor an explicit Hermes home override (tests + named profiles)
            # so we never write into the wrong/real profile unexpectedly.
            home_override = os.environ.get("HERMES_HOME")
            hermes_skills = (
                Path(home_override) / "skills" if home_override
                else Path.home() / ".hermes" / "skills"
            )
            if hermes_skills.is_dir():
                base = hermes_skills / "research-os-learned"
                base.mkdir(parents=True, exist_ok=True)
                for p in promoted:
                    slug = p["slug"]
                    entry = learned.get(slug, {})
                    recs = entry.get("recommendations") or []
                    card_dir = base / slug
                    card_dir.mkdir(parents=True, exist_ok=True)
                    body = (
                        "---\n"
                        f"name: ro-learned-{slug}\n"
                        f"description: Research-OS learned practice for "
                        f"{p['tag']} (distilled across this user's projects).\n"
                        "metadata:\n  hermes:\n    tags: [research-os, learned]\n"
                        f"    category: research\n---\n\n"
                        f"# Learned: {p['tag']}\n\n"
                        "## When to use\n"
                        f"When working on {p['tag']} in a research project.\n\n"
                        "## Practice (distilled from past projects)\n"
                        + "\n".join(f"- {r}" for r in recs)
                        + "\n\n## Source\n"
                        "Distilled + promoted by Research-OS from "
                        f"{entry.get('lessons_count', 0)} recurring lesson(s).\n"
                    )
                    (card_dir / "SKILL.md").write_text(body, encoding="utf-8")
                    hermes_cards.append(str(card_dir / "SKILL.md"))
        except Exception:
            hermes_cards = []  # best-effort; never fail promotion on card write

    return {
        "status": "success",
        "promoted": len(promoted),
        "skills": promoted,
        "profile_path": save_res.get("profile_path"),
        "hermes_cards_written": hermes_cards,
        "advice": (
            f"Promoted {len(promoted)} skill(s) to your cross-project profile"
            + (f" + {len(hermes_cards)} loadable Hermes card(s)" if hermes_cards else "")
            + ". New projects (research-os init) now inherit them"
            + ("; Hermes can load them as skills." if hermes_cards else ".")
            if promoted
            else "No project/methodology cluster reached the threshold yet."
        ),
    }


def list_skills(root: Path) -> dict[str, Any]:
    """List distilled project-local skills + promoted cross-project skills."""
    from research_os.tools.actions.state.config import load_profile

    local: list[dict[str, Any]] = []
    sdir = root / "workspace" / ".skills"
    if sdir.exists():
        for f in sorted(sdir.glob("*.SKILL.md")):
            local.append({"slug": f.stem.replace(".SKILL", ""),
                          "path": str(f.relative_to(root))})
    profile = load_profile()
    learned = profile.get("learned_skills")
    cross = []
    if isinstance(learned, dict):
        cross = [
            {"slug": k, "tag": v.get("tag"),
             "lessons_count": v.get("lessons_count")}
            for k, v in learned.items()
            if isinstance(v, dict)
        ]
    return {
        "status": "success",
        "project_skills": local,
        "cross_project_skills": cross,
        "n_project": len(local),
        "n_cross_project": len(cross),
    }


# Curated domain → skill-tag recommendations so a FRESH project with no history
# still gets sensible "load these capabilities" suggestions on the first turn.
# Tags are advisory labels the AI/Hermes can match against available skills.
_DOMAIN_SKILL_TAGS: dict[str, list[str]] = {
    "clinical": ["survival-analysis", "rct-design", "regression", "paper-writing"],
    "genomics": ["bioinformatics", "sequence-analysis", "stats", "viz"],
    "finance": ["time-series", "econometrics", "risk-modeling", "viz"],
    "nlp": ["text-processing", "embeddings", "eval-harness", "viz"],
    "ml": ["model-eval", "experiment-tracking", "reproducibility", "viz"],
    "psychology": ["experimental-design", "mixed-models", "power-analysis"],
    "ecology": ["spatial-stats", "mixed-models", "viz"],
    "physics": ["simulation", "numerical-methods", "viz"],
    "economics": ["causal-inference", "panel-data", "econometrics"],
    "social_science": ["survey-analysis", "causal-inference", "mixed-models"],
}
# Mode → capability tags every project in that mode benefits from.
_MODE_SKILL_TAGS: dict[str, list[str]] = {
    "analysis": ["stats", "viz", "paper-writing"],
    "tool_build": ["software-testing", "api-design", "benchmarking"],
    "exploration": ["data-profiling", "rapid-prototyping"],
    "notebook": ["jupyter", "viz"],
    "multi_study": ["meta-analysis", "evidence-synthesis"],
    "hybrid": ["software-testing", "stats", "viz"],
}


def recommend_skills(
    root: Path, domain: str | None = None, workspace_mode: str | None = None,
    *, task_intent: str | None = None, protocol: str | None = None,
) -> dict[str, Any]:
    """Forward-looking, intake-driven skill recommendations for THIS project
    AND (when given) THIS task.

    Unlike ``distill_skills`` (backward-looking — crystallizing past lessons),
    this answers "given what this project IS (domain + mode + question) and
    what the AI is ABOUT TO DO (task_intent / protocol), which capabilities
    should the AI / Hermes load NOW?" It is the universal skill-pull reflex:
    every task, the agent figures out what it needs, pulls the matching
    skills, loads + uses them, then keeps working inside Research-OS.

    Surfaced on the first setup turn (project-level) AND on every route
    (task-level), so the agent starts each task with the right skills instead
    of discovering them late. Sources, in priority order: the TASK-SPECIFIC
    capability for this protocol/sub-intent, the researcher's own cross-project
    ``learned_skills`` relevant to this domain/tag, project-local distilled
    skills already present, and a curated domain/mode → tag map. By-shape +
    fail-open.
    """
    from research_os.tools.actions.state.config import load_profile

    recs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(name: str, reason: str, source: str) -> None:
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        recs.append({"name": name, "reason": reason, "source": source})

    dom = (domain or "").strip().lower()
    mode = (workspace_mode or "analysis").strip().lower()
    intent = (task_intent or "").strip().lower()
    proto = (protocol or "").strip()

    # 0. TASK-SPECIFIC first — the capability the AI needs for THIS exact task
    #    leads, so the recommendation answers "what do I need to do THIS" before
    #    the general domain/mode picks. Concrete science-pack protocol skills +
    #    the coarser sub-intent tag layer.
    try:
        from research_os.tools.actions.research.science_pack import (
            SUB_INTENT_SKILL_TAGS,
            science_skills_for,
        )
        if proto:
            for s in science_skills_for(dom, mode, protocol=proto):
                # Only the protocol-specific picks here (domain/mode added below).
                if proto in s.get("reason", ""):
                    _add(s["name"], s["reason"], s["source"])
        for tag in SUB_INTENT_SKILL_TAGS.get(intent, []):
            _add(tag, f"capability for a '{intent}' task", "task_intent")
    except Exception:
        pass

    # 1. The researcher's OWN distilled skills whose tag matches this domain/mode.
    try:
        learned = load_profile().get("learned_skills")
        if isinstance(learned, dict):
            for slug, meta in learned.items():
                if not isinstance(meta, dict):
                    continue
                tag = str(meta.get("tag") or "").lower()
                if dom and (dom in tag or tag in dom):
                    _add(slug, f"your distilled skill for {tag or dom}",
                         "learned_profile")
    except Exception:
        pass

    # 2. Project-local distilled skills already present.
    try:
        sdir = root / "workspace" / ".skills"
        if sdir.exists():
            for f in sorted(sdir.glob("*.SKILL.md")):
                _add(f.stem.replace(".SKILL", ""),
                     "already distilled in this project", "project_local")
    except Exception:
        pass

    # 3. Curated domain + mode tags (the fresh-project fallback).
    for tag in _DOMAIN_SKILL_TAGS.get(dom, []):
        _add(tag, f"common for {dom} research", "domain_map")
    for tag in _MODE_SKILL_TAGS.get(mode, []):
        _add(tag, f"useful in {mode} mode", "mode_map")

    # 4. Concrete K-Dense science skills for this domain/mode/protocol (the
    # capability layer that pairs with RO's guidance). These are real
    # installable skills in the open Agent-Skills standard.
    try:
        from research_os.tools.actions.research.science_pack import (
            science_skills_for,
        )
        for s in science_skills_for(dom, mode, protocol=proto or None):
            _add(s["name"], s["reason"], s["source"])
    except Exception:
        pass

    return {
        "status": "success",
        "domain": dom or None,
        "workspace_mode": mode,
        "task_intent": intent or None,
        "protocol": proto or None,
        "recommended_skills": recs[:12],
        "note": (
            "This is the universal skill-pull reflex: figure out what THIS task "
            "needs, load these capabilities (Hermes skills, the science pack, or "
            "your own distilled ones), USE them, then keep working inside "
            "Research-OS. Task-specific picks lead. Not prescriptive."
        ),
    }


__all__ = ["distill_skills", "promote_skills", "list_skills", "recommend_skills"]
