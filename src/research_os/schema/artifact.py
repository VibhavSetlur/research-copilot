"""Artifact schema — content-addressed storage records and manifests."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    """A content-addressed artifact record."""

    id: str
    content_hash: str
    path: str | None = None
    media_type: str = "application/octet-stream"
    size_bytes: int | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: str | None = None


class ArtifactManifest(BaseModel):
    """A manifest indexing a collection of artifacts."""

    id: str
    artifacts: list[Artifact] = Field(default_factory=list)
    version: str = "1"
    metadata: dict = Field(default_factory=dict)

    def by_hash(self, h: str) -> Artifact | None:
        """Return the first artifact matching content hash ``h``, or None."""
        for artifact in self.artifacts:
            if artifact.content_hash == h:
                return artifact
        return None
