"""Environment snapshot schema — reproducibility capture of the runtime."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EnvironmentSnapshot(BaseModel):
    """A captured snapshot of the runtime environment for reproducibility."""

    id: str
    captured_at: str | None = None
    python_version: str | None = None
    platform: str | None = None
    packages: dict[str, str] = Field(default_factory=dict)
    env_vars: dict[str, str] = Field(default_factory=dict)
    git_commit: str | None = None
    extra: dict = Field(default_factory=dict)
