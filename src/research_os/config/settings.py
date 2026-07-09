"""Central Pydantic settings — env-derived credentials for research data sources only.

Research OS does NOT manage LLM provider keys (OpenAI / Anthropic / etc.).
Your AI client (Claude Code, OpenCode, Antigravity IDE, …) owns its own model
access. We only inject keys for the literature / search / scraping APIs the
MCP server uses internally.
"""

from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-derived configuration."""

    # Literature & search APIs (all optional — public endpoints work without keys)
    SEMANTIC_SCHOLAR_API_KEY: Optional[str] = None
    S2_API_KEY: Optional[str] = None  # alias used by some SDKs
    CROSSREF_API_KEY: Optional[str] = None
    NCBI_API_KEY: Optional[str] = None
    FIRECRAWL_API_KEY: Optional[str] = None
    FIRECRAWL: Optional[str] = None  # alias
    SERPAPI_API_KEY: Optional[str] = None
    SERPAPI: Optional[str] = None  # alias

    # Runtime knobs
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
