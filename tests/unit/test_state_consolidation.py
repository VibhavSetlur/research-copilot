"""§9.5 State consolidation — lessons + thoughts path migration.

Tests the backward-compatible relocation of:
  workspace/.lessons/lessons.jsonl  → .os_state/lessons/lessons.jsonl
  workspace/.thoughts/thoughts.jsonl → .os_state/thoughts/thoughts.jsonl

Covers for BOTH stores:
  - write when neither old nor new exists → creates new .os_state/ file.
  - existing OLD file with records → on next write, records migrated +
    preserved (no loss); subsequent reads return all records.
  - reading a project that only has the old file (no write yet) → returns
    old records via fallback.
  - idempotent migration (running twice doesn't duplicate records).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.tools.actions.research.grounding import thought_log, thought_trace
from research_os.tools.actions.research.lessons import (
    _lessons_read_path,
    _lessons_write_path,
    lessons_consult,
    lessons_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NEW_LESSONS = Path(".os_state") / "lessons" / "lessons.jsonl"
_OLD_LESSONS = Path("workspace") / ".lessons" / "lessons.jsonl"
_NEW_THOUGHTS = Path(".os_state") / "thoughts" / "thoughts.jsonl"
_OLD_THOUGHTS = Path("workspace") / ".thoughts" / "thoughts.jsonl"


def _write_old_lessons(root: Path, records: list[dict]) -> None:
    p = root / _OLD_LESSONS
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _write_old_thoughts(root: Path, records: list[dict]) -> None:
    p = root / _OLD_THOUGHTS
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


# ===========================================================================
# LESSONS
# ===========================================================================


class TestLessonsNewProject:
    """Neither old nor new path exists — should create the new .os_state/ file."""

    def test_write_creates_new_path(self, tmp_path: Path):
        r = lessons_record(
            tmp_path,
            outcome="success",
            reflection="All good.",
            tags=["test"],
        )
        assert r["status"] == "success"
        new = tmp_path / _NEW_LESSONS
        assert new.exists(), "new canonical path should be created on write"
        assert not (tmp_path / _OLD_LESSONS).exists(), "old path should not be created"

    def test_log_path_in_response_is_new(self, tmp_path: Path):
        r = lessons_record(tmp_path, outcome="success", reflection="Done.")
        assert ".os_state" in r["log_path"]
        assert "lessons" in r["log_path"]

    def test_consult_returns_empty_when_nothing_recorded(self, tmp_path: Path):
        r = lessons_consult(tmp_path, task="something new")
        assert r["status"] == "success"
        assert r["n_total"] == 0


class TestLessonsMigration:
    """Old file exists, new does not — migration must happen on first write."""

    def test_old_records_preserved_after_migration(self, tmp_path: Path):
        old_records = [
            {"lesson_id": "L_001", "ts": "2025-01-01T00:00:00+00:00",
             "outcome": "failure", "scope": "step", "step_id": None,
             "tags": ["pandas"], "reflection": "Join dropped rows.",
             "what_worked": "", "what_didnt": "", "recommendation": ""},
        ]
        _write_old_lessons(tmp_path, old_records)

        # First write to a fresh project triggers migration.
        r = lessons_record(
            tmp_path,
            outcome="success",
            reflection="New lesson after migration.",
            tags=["pandas"],
        )
        assert r["status"] == "success"

        new = tmp_path / _NEW_LESSONS
        assert new.exists(), "new path should be created during migration"

        records = _read_jsonl(new)
        lesson_ids = [rec.get("lesson_id") for rec in records]
        assert "L_001" in lesson_ids, "old record must be preserved"
        assert any("New lesson" in rec.get("reflection", "") for rec in records), \
            "new record must be present"

    def test_consult_returns_all_records_after_migration(self, tmp_path: Path):
        _write_old_lessons(tmp_path, [
            {"lesson_id": "L_old", "ts": "2025-01-01T00:00:00+00:00",
             "outcome": "failure", "scope": "step", "step_id": None,
             "tags": ["stats"], "reflection": "Bootstrap failed on sparse data.",
             "what_worked": "", "what_didnt": "", "recommendation": ""},
        ])
        # Trigger migration via write.
        lessons_record(tmp_path, outcome="success", reflection="New insight.", tags=["stats"])

        r = lessons_consult(tmp_path, task="bootstrap stats", tags=["stats"])
        assert r["status"] == "success"
        lesson_ids = [ell.get("lesson_id") for ell in r["lessons"]]
        assert "L_old" in lesson_ids, "old lesson must be returned after migration"


class TestLessonsFallbackReadOnly:
    """Project has only the old file — reads fall back without triggering migration."""

    def test_read_fallback_to_old_path(self, tmp_path: Path):
        _write_old_lessons(tmp_path, [
            {"lesson_id": "L_legacy", "ts": "2025-01-01T00:00:00+00:00",
             "outcome": "success", "scope": "step", "step_id": None,
             "tags": ["legacy"], "reflection": "Old lesson.",
             "what_worked": "", "what_didnt": "", "recommendation": ""},
        ])
        # No write → no migration → only old path exists.
        read_path = _lessons_read_path(tmp_path)
        assert read_path == tmp_path / _OLD_LESSONS

        r = lessons_consult(tmp_path, task="legacy topic", tags=["legacy"])
        assert r["status"] == "success"
        lesson_ids = [ell.get("lesson_id") for ell in r["lessons"]]
        assert "L_legacy" in lesson_ids

    def test_new_path_not_created_by_read(self, tmp_path: Path):
        _write_old_lessons(tmp_path, [
            {"lesson_id": "L_x", "ts": "2025-01-01T00:00:00+00:00",
             "outcome": "success", "scope": "step", "step_id": None,
             "tags": [], "reflection": "x.", "what_worked": "", "what_didnt": "",
             "recommendation": ""},
        ])
        lessons_consult(tmp_path, task="x")
        assert not (tmp_path / _NEW_LESSONS).exists(), \
            "read-only consult must not create the new path"


class TestLessonsIdempotentMigration:
    """Running write twice must not duplicate records."""

    def test_no_duplicate_after_second_write(self, tmp_path: Path):
        _write_old_lessons(tmp_path, [
            {"lesson_id": "L_dup", "ts": "2025-01-01T00:00:00+00:00",
             "outcome": "failure", "scope": "step", "step_id": None,
             "tags": [], "reflection": "Will this duplicate?",
             "what_worked": "", "what_didnt": "", "recommendation": ""},
        ])
        # First write migrates + appends.
        lessons_record(tmp_path, outcome="success", reflection="First new.")
        # Second write must NOT re-migrate (new path now exists).
        lessons_record(tmp_path, outcome="success", reflection="Second new.")

        new = tmp_path / _NEW_LESSONS
        records = _read_jsonl(new)
        l_dup_count = sum(1 for r in records if r.get("lesson_id") == "L_dup")
        assert l_dup_count == 1, f"L_dup should appear exactly once, got {l_dup_count}"


# ===========================================================================
# THOUGHTS
# ===========================================================================


class TestThoughtsNewProject:
    """Neither old nor new path exists — should create the new .os_state/ file."""

    def test_write_creates_new_path(self, tmp_path: Path):
        r = thought_log(tmp_path, kind="thought", content="Initial reasoning.")
        assert r["status"] == "success"
        new = tmp_path / _NEW_THOUGHTS
        assert new.exists(), "new canonical path should be created on write"
        assert not (tmp_path / _OLD_THOUGHTS).exists(), "old path should not be created"

    def test_log_path_in_response_is_new(self, tmp_path: Path):
        r = thought_log(tmp_path, kind="thought", content="Test.")
        assert ".os_state" in r["log_path"]
        assert "thoughts" in r["log_path"]

    def test_trace_returns_empty_when_nothing_logged(self, tmp_path: Path):
        r = thought_trace(tmp_path)
        assert r["status"] == "success"
        assert r["n_total"] == 0


class TestThoughtsMigration:
    """Old file exists, new does not — migration must happen on first write."""

    def test_old_records_preserved_after_migration(self, tmp_path: Path):
        old_records = [
            {"trace_id": "old_trace_001", "ts": "2025-01-01T00:00:00+00:00",
             "kind": "thought", "content": "Old thought.", "step_id": None,
             "decision_id": None, "metadata": {}},
        ]
        _write_old_thoughts(tmp_path, old_records)

        r = thought_log(tmp_path, kind="action", content="New action after migration.")
        assert r["status"] == "success"

        new = tmp_path / _NEW_THOUGHTS
        assert new.exists()

        records = _read_jsonl(new)
        trace_ids = [rec.get("trace_id") for rec in records]
        assert "old_trace_001" in trace_ids, "old record must be preserved"
        assert any("New action" in rec.get("content", "") for rec in records), \
            "new record must be present"

    def test_trace_returns_all_records_after_migration(self, tmp_path: Path):
        _write_old_thoughts(tmp_path, [
            {"trace_id": "t_legacy", "ts": "2025-01-01T00:00:00+00:00",
             "kind": "thought", "content": "Old reasoning.", "step_id": "01_eda",
             "decision_id": None, "metadata": {}},
        ])
        thought_log(tmp_path, kind="observation", content="New obs.", step_id="01_eda")

        r = thought_trace(tmp_path, step_id="01_eda")
        assert r["status"] == "success"
        trace_ids = [e.get("trace_id") for e in r["entries"]]
        assert "t_legacy" in trace_ids, "old trace entry must appear after migration"


class TestThoughtsFallbackReadOnly:
    """Project has only the old file — reads fall back without migrating."""

    def test_trace_reads_from_old_path(self, tmp_path: Path):
        _write_old_thoughts(tmp_path, [
            {"trace_id": "t_old", "ts": "2025-01-01T00:00:00+00:00",
             "kind": "plan", "content": "Old plan.", "step_id": "01_eda",
             "decision_id": None, "metadata": {}},
        ])
        # No write → no migration.
        assert not (tmp_path / _NEW_THOUGHTS).exists()

        r = thought_trace(tmp_path)
        assert r["status"] == "success"
        assert r["n_total"] == 1
        assert r["entries"][0]["trace_id"] == "t_old"

    def test_new_path_not_created_by_trace(self, tmp_path: Path):
        _write_old_thoughts(tmp_path, [
            {"trace_id": "t_x", "ts": "2025-01-01T00:00:00+00:00",
             "kind": "thought", "content": "x.", "step_id": None,
             "decision_id": None, "metadata": {}},
        ])
        thought_trace(tmp_path)
        assert not (tmp_path / _NEW_THOUGHTS).exists(), \
            "read-only trace must not create the new path"


class TestThoughtsIdempotentMigration:
    """Running write twice must not duplicate records."""

    def test_no_duplicate_after_second_write(self, tmp_path: Path):
        _write_old_thoughts(tmp_path, [
            {"trace_id": "t_dup", "ts": "2025-01-01T00:00:00+00:00",
             "kind": "thought", "content": "Will this dup?", "step_id": None,
             "decision_id": None, "metadata": {}},
        ])
        thought_log(tmp_path, kind="thought", content="First new.")
        thought_log(tmp_path, kind="thought", content="Second new.")

        new = tmp_path / _NEW_THOUGHTS
        records = _read_jsonl(new)
        t_dup_count = sum(1 for r in records if r.get("trace_id") == "t_dup")
        assert t_dup_count == 1, f"t_dup should appear exactly once, got {t_dup_count}"
