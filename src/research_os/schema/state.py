"""State ledger schema — a versioned append-only record of workflow entries."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field


class StateLedger(BaseModel):
    """A versioned, append-only ledger of state entries."""

    #: Current schema version.  Increment whenever a field is added or
    #: removed so that ``state_schema.migrate_state`` can upgrade older
    #: serialised ledgers.  This is distinct from the per-append ``version``
    #: counter which tracks the number of entries.
    SCHEMA_VERSION: ClassVar[int] = 1

    id: str
    version: int = 1
    schema_version: int = 1
    entries: list[dict] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict = Field(default_factory=dict)

    def append(self, entry: dict) -> None:
        """Append ``entry`` to the ledger and bump the version."""
        self.entries.append(entry)
        self.version += 1
