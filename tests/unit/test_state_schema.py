"""Unit tests for research_os.state.state_schema (§9.3 migration layer).

The Pydantic loader is ``_load_state_pydantic`` (internal, test-only).
The canonical production loader is ``research_os.project_ops.load_state``.
"""

from __future__ import annotations

import json
import uuid

import pytest

from research_os.state.state_schema import (
    StateLedger,
    _load_state_pydantic as load_state,
    migrate_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_ledger(tmp_path, data: dict) -> None:
    """Write *data* as JSON to the canonical ledger location."""
    state_dir = tmp_path / ".os_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state_ledger.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# load_state — missing file
# ---------------------------------------------------------------------------


def test_load_state_missing_file_returns_fresh_ledger(tmp_path):
    """Missing ledger file → fresh StateLedger with a valid UUID id."""
    ledger = load_state(tmp_path)

    assert isinstance(ledger, StateLedger)
    # id must be a valid UUID string
    assert uuid.UUID(ledger.id)
    assert ledger.entries == []
    assert ledger.schema_version == StateLedger.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# load_state — current-schema round-trip
# ---------------------------------------------------------------------------


def test_load_state_current_schema_round_trips(tmp_path):
    """A ledger written with the current schema is loaded unchanged."""
    original = StateLedger(id="abc-123", schema_version=StateLedger.SCHEMA_VERSION)
    original.append({"step": "init"})

    _write_ledger(tmp_path, original.model_dump())

    loaded = load_state(tmp_path)

    assert loaded.id == "abc-123"
    assert loaded.schema_version == StateLedger.SCHEMA_VERSION
    assert loaded.version == 2  # 1 (default) + 1 append
    assert loaded.entries == [{"step": "init"}]


# ---------------------------------------------------------------------------
# migrate_state — legacy dict (no schema_version)
# ---------------------------------------------------------------------------


def test_migrate_state_injects_schema_version_into_legacy_dict():
    """A dict without schema_version is treated as v0 and upgraded to v1."""
    raw = {"id": "legacy-id", "version": 1, "entries": [{"x": 1}]}
    result = migrate_state(raw)

    assert result["schema_version"] == StateLedger.SCHEMA_VERSION
    assert result["id"] == "legacy-id"
    assert result["entries"] == [{"x": 1}]


def test_migrate_state_fills_missing_required_fields():
    """A dict with no id or entries gets safe defaults injected."""
    raw: dict = {}
    result = migrate_state(raw)

    assert result["schema_version"] == StateLedger.SCHEMA_VERSION
    assert "id" in result
    assert uuid.UUID(result["id"])  # must be a valid UUID
    assert result["entries"] == []


def test_migrate_state_does_not_overwrite_existing_id():
    """If a legacy dict already has an id, migrate_state preserves it."""
    raw = {"id": "keep-me"}
    result = migrate_state(raw)

    assert result["id"] == "keep-me"


# ---------------------------------------------------------------------------
# migrate_state — idempotency
# ---------------------------------------------------------------------------


def test_migrate_state_idempotent_on_current_dict():
    """Calling migrate_state on an already-current dict is a no-op."""
    raw = {
        "id": "already-current",
        "version": 1,
        "schema_version": StateLedger.SCHEMA_VERSION,
        "entries": [],
        "created_at": None,
        "updated_at": None,
        "metadata": {},
    }
    # Take a shallow copy to compare after
    before = dict(raw)
    result = migrate_state(raw)

    assert result == before


# ---------------------------------------------------------------------------
# load_state — malformed JSON raises ValueError
# ---------------------------------------------------------------------------


def test_load_state_malformed_json_raises_value_error(tmp_path):
    """Malformed JSON in the ledger file raises ValueError with a clear message."""
    state_dir = tmp_path / ".os_state"
    state_dir.mkdir(parents=True)
    (state_dir / "state_ledger.json").write_text("{not valid json}", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed JSON"):
        load_state(tmp_path)


# ---------------------------------------------------------------------------
# load_state — auto-migrates a legacy file
# ---------------------------------------------------------------------------


def test_load_state_migrates_legacy_file(tmp_path):
    """A legacy file on disk (no schema_version) is auto-migrated on load."""
    legacy = {"id": "old-id", "version": 3, "entries": [{"a": 1}, {"b": 2}]}
    _write_ledger(tmp_path, legacy)

    loaded = load_state(tmp_path)

    assert isinstance(loaded, StateLedger)
    assert loaded.id == "old-id"
    assert loaded.schema_version == StateLedger.SCHEMA_VERSION
    assert len(loaded.entries) == 2


# ---------------------------------------------------------------------------
# state/__init__.py re-exports
# ---------------------------------------------------------------------------


def test_state_package_exports():
    """migrate_state is re-exported from research_os.state.

    load_state (Pydantic) is intentionally NOT exported — the canonical
    production loader is research_os.project_ops.load_state (returns dict).
    _load_state_pydantic remains importable directly from state_schema for
    test use.
    """
    from research_os.state import migrate_state as ms  # noqa: F401
    assert callable(ms)

    # Verify the canonical production loader is importable and returns dicts.
    from research_os.project_ops import load_state as canonical_ls  # noqa: F401
    assert callable(canonical_ls)

    # Verify the Pydantic loader is NOT re-exported from research_os.state.
    import research_os.state as state_pkg
    assert not hasattr(state_pkg, "load_state"), (
        "research_os.state must not export load_state — "
        "use project_ops.load_state (returns dict) as the canonical loader."
    )
