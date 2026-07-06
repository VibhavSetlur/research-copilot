"""Reflexion-style lessons learned (Shinn et al. 2023).

After each step / failure / completed plan, record a one-paragraph
"what worked, what didn't, what to do differently next time" entry
into ``.os_state/lessons/lessons.jsonl`` (new canonical path). On
future turns, the top-K most-relevant lessons are surfaced via
``lessons_consult`` so the AI doesn't make the same mistake twice.

Backward-compatible path resolution
------------------------------------
* **New canonical path**: ``.os_state/lessons/lessons.jsonl``
* **Legacy path**: ``workspace/.lessons/lessons.jsonl``

On **write**: if the new path does not exist yet but the legacy path
does, the legacy file's contents are migrated (appended) to the new
path first (idempotent: running twice never duplicates records, because
the new file is created during migration). Writes then go to the new
path.

On **read**: use the new path if it exists; otherwise fall back to the
legacy path so projects that have never written since upgrading still
return their old lessons.

This is the verbal-reinforcement loop Reflexion describes: the
trace becomes a textual lesson that feeds the next attempt's prompt.
Lessons are scoped (step / methodology / project-wide), tagged, and
ranked by recency + tag overlap with the current task.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("research_os.lessons")

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_NEW_LESSONS_SUBPATH = Path(".os_state") / "lessons" / "lessons.jsonl"
_OLD_LESSONS_SUBPATH = Path("workspace") / ".lessons" / "lessons.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate_lessons_if_needed(root: Path, new_path: Path) -> None:
    """One-time migration: copy legacy records to the new path.

    Idempotent — if the new path already exists (even empty) we skip,
    so a second call never duplicates records.
    """
    old_path = root / _OLD_LESSONS_SUBPATH
    if not old_path.exists() or new_path.exists():
        return
    try:
        content = old_path.read_text(encoding="utf-8", errors="replace")
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_text(content, encoding="utf-8")
        logger.debug(
            "lessons: migrated %s → %s", old_path.relative_to(root),
            new_path.relative_to(root),
        )
    except Exception as exc:  # pragma: no cover — best-effort migration
        logger.warning("lessons: migration failed (%s); writes go to new path anyway", exc)
        # Ensure the new path exists so subsequent writes don't re-trigger migration.
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.touch()


def _lessons_write_path(root: Path) -> Path:
    """Return the path to write lessons to, running migration first if needed."""
    new_path = root / _NEW_LESSONS_SUBPATH
    _migrate_lessons_if_needed(root, new_path)
    new_path.parent.mkdir(parents=True, exist_ok=True)
    return new_path


def _lessons_read_path(root: Path) -> Path:
    """Return the path to read lessons from (new if exists, else legacy)."""
    new_path = root / _NEW_LESSONS_SUBPATH
    if new_path.exists():
        return new_path
    old_path = root / _OLD_LESSONS_SUBPATH
    return old_path


# Legacy internal name kept so callers that imported it directly (e.g. tests)
# continue to work — it now always returns the canonical write path.
def _lessons_log(root: Path) -> Path:
    return _lessons_write_path(root)


def lessons_record(
    root: Path,
    *,
    trial_id: str | None = None,
    outcome: str,
    reflection: str,
    what_worked: str = "",
    what_didnt: str = "",
    recommendation: str = "",
    tags: list[str] | None = None,
    step_id: str | None = None,
    scope: str = "step",
) -> dict[str, Any]:
    """Append one Reflexion-style lesson.

    Parameters
    ----------
    outcome: ``success | failure | partial | abandoned``.
    reflection: One paragraph in the AI's own voice — what happened.
    what_worked / what_didnt: short bullets distilled from reflection.
    recommendation: what to do differently next time.
    tags: methodology / domain keywords for retrieval.
    scope: ``step | project | methodology`` — controls relevance ranking.
    """
    if outcome not in {"success", "failure", "partial", "abandoned"}:
        return {
            "status": "error",
            "message": "outcome must be success | failure | partial | abandoned",
        }
    if scope not in {"step", "project", "methodology"}:
        return {
            "status": "error",
            "message": "scope must be step | project | methodology",
        }
    if not reflection.strip():
        return {"status": "error", "message": "reflection is required"}
    rec = {
        "lesson_id": trial_id or f"L_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "ts": _now(),
        "outcome": outcome,
        "scope": scope,
        "step_id": step_id,
        "tags": [t.lower() for t in (tags or [])],
        "reflection": reflection.strip(),
        "what_worked": what_worked.strip(),
        "what_didnt": what_didnt.strip(),
        "recommendation": recommendation.strip(),
    }
    log_path = _lessons_log(root)
    with open(log_path, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return {"status": "success", **rec,
            "log_path": str(log_path.relative_to(root))}


def _read_lessons(root: Path) -> list[dict[str, Any]]:
    p = _lessons_read_path(root)
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


def _score_lesson(
    lesson: dict[str, Any], task_tags: set[str], task_keywords: set[str],
) -> float:
    """Recency + tag-overlap + keyword-overlap relevance score."""
    # Recency: exponential decay over 60 days.
    try:
        delta = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(lesson["ts"].rstrip("Z"))
        ).days
    except Exception:
        delta = 365
    recency = max(0.0, 1.0 - delta / 60.0)
    tag_score = len(set(lesson.get("tags", [])) & task_tags) * 0.5
    body = " ".join([
        lesson.get("reflection", ""),
        lesson.get("recommendation", ""),
        lesson.get("what_worked", ""),
        lesson.get("what_didnt", ""),
    ]).lower()
    kw_score = sum(1 for k in task_keywords if k in body) * 0.2
    # Failure lessons get a small boost (more actionable).
    outcome_boost = 0.3 if lesson.get("outcome") == "failure" else 0.0
    return recency + tag_score + kw_score + outcome_boost


def lessons_consult(
    root: Path,
    *,
    task: str,
    tags: list[str] | None = None,
    top_k: int = 5,
    scope_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Surface the top-K most-relevant lessons for the current task.

    Returns lessons ranked by recency + tag overlap + keyword overlap.
    Designed to be prepended to the next AI turn's system prompt under
    a ``## Prior lessons`` header.
    """
    lessons = _read_lessons(root)
    if scope_filter:
        lessons = [
            lesson for lesson in lessons
            if lesson.get("scope") in scope_filter
        ]
    task_tags = {t.lower() for t in (tags or [])}
    # Cheap keyword extraction: lowercase word tokens >3 chars.
    task_keywords = set(re.findall(r"\b[a-z]{4,}\b", task.lower()))
    scored = [
        (_score_lesson(lesson, task_tags, task_keywords), lesson)
        for lesson in lessons
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [lesson for s, lesson in scored[:top_k] if s > 0]

    if top:
        prompt_block = "## Prior lessons\n\n" + "\n".join(
            f"- **[{lesson['ts'][:10]} · {lesson['outcome']}]** "
            f"{lesson['reflection'][:200]}"
            + (f" → {lesson['recommendation'][:120]}"
               if lesson.get("recommendation") else "")
            for lesson in top
        )
    else:
        prompt_block = ""

    return {
        "status": "success",
        "task": task,
        "n_total": len(lessons),
        "n_returned": len(top),
        "lessons": top,
        "prompt_block": prompt_block,
        "advice": (
            f"{len(top)} prior lesson(s) match. Prepend `prompt_block` to "
            "the model's system prompt for this task to consult them."
            if top
            else "No prior lessons match — fresh task."
        ),
    }


__all__ = ["lessons_consult", "lessons_record"]
