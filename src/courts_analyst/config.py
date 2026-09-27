"""Server configuration loaded from environment variables or a .env file.

Every field can be overridden by an environment variable of the same name
(upper- or lower-case). Copy `.env.example` to `.env` for local development.
Nothing here is required at startup: missing API keys only disable the
features that need them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Typed settings for the MCP server, pipelines and agent."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Transport ─────────────────────────────────────────────────────────────
    # "stdio"           — local subprocess (Claude Desktop / Claude Code / Zed)
    # "streamable-http" — remote HTTP server (containers, cloud deploys)
    #
    # app.py also auto-selects HTTP when a platform injects DATABRICKS_APP_PORT
    # or PORT, so you usually do NOT need to set this on a cloud host.
    mcp_transport: Literal["stdio", "streamable-http"] = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    # ── Data ──────────────────────────────────────────────────────────────────
    # DATA_DIR holds raw downloads (data/raw) and build outputs (data/build).
    # DUCKDB_PATH defaults to <DATA_DIR>/build/courts.duckdb (official tables);
    # IDB_DUCKDB_PATH to <DATA_DIR>/build/idb.duckdb (FJC civil IDB).
    data_dir: Path = Path("data")
    duckdb_path: Path | None = None
    idb_duckdb_path: Path | None = None
    # Cohort handles (Phase 5). Unset → in-memory only; handles are
    # deterministic, so a restart just means calling find_cases again. Set a
    # writable path (never inside data/build, which is mounted read-only) to
    # keep handles across restarts in HTTP mode.
    cohort_store_path: Path | None = None

    # ── External services (all optional) ──────────────────────────────────────
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    courtlistener_api_token: SecretStr | None = None

    # ── Logging ───────────────────────────────────────────────────────────────
    # LOG_FORMAT=auto → JSON when serving HTTP, human-readable otherwise.
    log_level: LogLevel = "INFO"
    log_format: Literal["auto", "json", "pretty"] = "auto"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator(
        "anthropic_api_key",
        "openai_api_key",
        "courtlistener_api_token",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # `FOO_API_KEY=` in a .env file means "not set", not "empty key".
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def resolved_duckdb_path(self) -> Path:
        """Where the analytical DuckDB file lives."""
        return self.duckdb_path or self.data_dir / "build" / "courts.duckdb"

    @property
    def resolved_idb_path(self) -> Path:
        """Where the civil IDB DuckDB file lives (no party names in it)."""
        return self.idb_duckdb_path or self.data_dir / "build" / "idb.duckdb"

    @property
    def idb_parties_path(self) -> Path:
        """IDB party names (PII). Kept outside data/build, which is what gets
        mounted into the server; the server never reads this file."""
        return self.data_dir / "private" / "idb_parties.parquet"


settings = Settings()
