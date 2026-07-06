"""State ledger schema — a versioned append-only record of workflow entries."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StateLedger(BaseModel):
    """A versioned, append-only ledger of state entries."""

    id: str
    version: int = 1
    entries: list[dict] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict = Field(default_factory=dict)

    def append(self, entry: dict) -> None:
        """Append ``entry`` to the ledger and bump the version."""
        self.entries.append(entry)
        self.version += 1
