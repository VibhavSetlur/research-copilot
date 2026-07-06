"""State ledger migration layer.

Provides :func:`migrate_state` and :func:`load_state` to read a
``state_ledger.json`` file from disk, auto-upgrade it when its
``schema_version`` is older than :data:`StateLedger.SCHEMA_VERSION`, and
return a validated :class:`~research_os.schema.state.StateLedger` instance.

Design notes
------------
* Migration functions are registered in ``_MIGRATIONS``, keyed by the
  *from*-version they handle (i.e. the version they upgrade *away from*).
  They are applied in ascending key order until ``raw["schema_version"]``
  equals the current :data:`StateLedger.SCHEMA_VERSION`.
* A legacy dict that has no ``schema_version`` key is treated as
  ``schema_version = 0`` and normalised to ``schema_version = 1`` by the
  built-in ``_migrate_0_to_1`` function.
* All migrations are idempotent: running them on an already-current dict
  is safe and returns the dict unchanged.
* Only stdlib + pydantic are imported.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Callable

from research_os.schema.state import StateLedger

# ---------------------------------------------------------------------------
# Internal migration registry
# ---------------------------------------------------------------------------

# Each entry maps from-version (int) → callable that upgrades a raw dict
# *in-place* from that version to the next and returns the modified dict.
_MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def _register(from_version: int) -> Callable:
    """Decorator: register a migration function for *from_version*."""

    def _decorator(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _MIGRATIONS[from_version] = fn
        return fn

    return _decorator


# ---------------------------------------------------------------------------
# Migration functions (one per version step)
# ---------------------------------------------------------------------------


@_register(0)
def _migrate_0_to_1(raw: dict) -> dict:
    """Normalise a legacy dict (no ``schema_version``) to schema version 1.

    Injects ``schema_version: 1`` and fills any missing required fields
    (``id``, ``entries``) with safe defaults so that
    :meth:`StateLedger.model_validate` succeeds.
    """
    raw.setdefault("id", str(uuid.uuid4()))
    raw.setdefault("entries", [])
    raw["schema_version"] = 1
    return raw


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def migrate_state(raw: dict) -> dict:
    """Upgrade *raw* (a deserialised ledger dict) to the current schema version.

    The function applies migration steps in ascending version order until
    ``raw["schema_version"]`` equals :data:`StateLedger.SCHEMA_VERSION`.
    It is safe to call on an already-current dict — no changes are made.

    Parameters
    ----------
    raw:
        A dictionary read from a ``state_ledger.json`` file (or constructed
        in tests).  Modified in-place **and** returned.

    Returns
    -------
    dict
        The same *raw* dict, upgraded to the current schema version.
    """
    # Treat a missing key as schema_version 0 (pre-versioning legacy).
    if "schema_version" not in raw:
        raw["schema_version"] = 0

    target = StateLedger.SCHEMA_VERSION
    for from_ver in sorted(_MIGRATIONS):
        if raw["schema_version"] >= target:
            break
        if raw["schema_version"] == from_ver:
            raw = _MIGRATIONS[from_ver](raw)

    return raw


def load_state(root: Path) -> StateLedger:
    """Read the state ledger for the project rooted at *root*.

    Looks for ``<root>/.os_state/state_ledger.json``.

    * **Missing file** → returns a fresh :class:`StateLedger` with a new UUID.
    * **Outdated schema** → runs :func:`migrate_state` before validation.
    * **Malformed JSON** → raises :class:`ValueError` with a clear message.
    * **Current-schema file** → validates and returns directly.

    Parameters
    ----------
    root:
        Project root directory (``Path`` object).  The ledger file is
        expected at ``root / ".os_state" / "state_ledger.json"``.

    Returns
    -------
    StateLedger
        A validated Pydantic model instance.

    Raises
    ------
    ValueError
        If the ledger file exists but cannot be parsed as JSON.
    """
    ledger_path = root / ".os_state" / "state_ledger.json"

    if not ledger_path.exists():
        return StateLedger(id=str(uuid.uuid4()))

    try:
        raw: dict = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"State ledger at {ledger_path} contains malformed JSON: {exc}"
        ) from exc

    if raw.get("schema_version") != StateLedger.SCHEMA_VERSION:
        raw = migrate_state(raw)

    return StateLedger.model_validate(raw)
