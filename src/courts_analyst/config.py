"""Server configuration loaded from environment variables or a .env file.

Every field can be overridden by an environment variable of the same name
(upper- or lower-case). Copy `.env.example` to `.env` for local development.
Nothing here is required at startup: missing API keys only disable the
features that need them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    # Containers; set 127.0.0.1 locally.
    mcp_host: str = "0.0.0.0"  # nosec B104
    mcp_port: int = 8000

    # ── HTTP hardening (Phase 6; see http_security.py) ────────────────────────
    # CORS allowlist, comma-separated ("https://a.example,https://b.example").
    # Empty: no cross-origin browser access.
    http_allowed_origins: Annotated[list[str], NoDecode] = []
    # Requests larger than this get 413.
    http_max_request_bytes: int = 1_048_576
    # Per client (MCP session, else address); 0 disables.
    http_rate_limit_per_minute: int = 120
    # Optional bearer token for the deployed demo; /health and /version stay open.
    http_bearer_token: SecretStr | None = None
    # POST /api/ask per client per minute (each one calls a paid model); 0
    # disables. On top of the general limit above.
    http_ask_rate_limit_per_minute: int = 10

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

    # ── Request desk (ADR 0013) ────────────────────────────────────────────────
    # Sandbox write workflow. Unset path → in memory (a restart empties it).
    # Set a writable path, never inside data/build (mounted read-only).
    desk_store_path: Path | None = None
    # Staff routes and the staff screen need this token (X-Desk-Staff-Token).
    # Unset → the staff side is off.
    desk_staff_token: SecretStr | None = None
    # Register the two staff tools (record_official_response, publish_answer)
    # on MCP, e.g. to play the statistics office from Claude Desktop.
    desk_staff_mode: bool = False

    # ── External services (all optional) ──────────────────────────────────────
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    courtlistener_api_token: SecretStr | None = None

    # ── Agent (Phase 7) ───────────────────────────────────────────────────────
    # "anthropic:<model>" or "openai:<model>"; the web app's /api/ask uses it.
    agent_model: str = "anthropic:claude-sonnet-5"
    # CourtListener docket lookups: "auto" (live with a token, else the cached
    # fixture), "fixture" (never call out) or "off".
    agent_courtlistener: Literal["auto", "fixture", "off"] = "auto"
    # Put question, answer and tool arguments in trace spans verbatim (else a
    # hash). Local debugging only, like LOG_TOOL_ARGUMENTS.
    agent_trace_content: bool = False

    # ── Web app and eval results (served over HTTP) ──────────────────────────
    # Relative to the working directory, like DATA_DIR (/app in the image).
    web_dist_dir: Path = Path("web/dist")
    eval_results_dir: Path = Path("eval/results")

    # ── Logging ───────────────────────────────────────────────────────────────
    # LOG_FORMAT=auto → JSON when serving HTTP, human-readable otherwise.
    log_level: LogLevel = "INFO"
    log_format: Literal["auto", "json", "pretty"] = "auto"
    # Tool arguments are logged as a hash. Set true (with LOG_LEVEL=DEBUG) to
    # also log them verbatim while debugging; never in a deployment.
    log_tool_arguments: bool = False

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator(
        "anthropic_api_key",
        "openai_api_key",
        "courtlistener_api_token",
        "http_bearer_token",
        "desk_staff_token",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        # `FOO_API_KEY=` in a .env file means "not set", not "empty key".
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("http_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [v.strip().rstrip("/") for v in value.split(",") if v.strip()]
        return value

    def secrets(self) -> list[str]:
        """Every configured secret value, for log redaction."""
        return [
            s.get_secret_value()
            for s in (
                self.anthropic_api_key,
                self.openai_api_key,
                self.courtlistener_api_token,
                self.http_bearer_token,
            )
            if s is not None and len(s.get_secret_value()) >= 8
        ]

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
