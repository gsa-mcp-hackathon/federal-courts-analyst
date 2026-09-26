"""Unit: settings load from the environment and never block startup."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from courts_analyst.config import Settings

ENV_VARS = [
    "MCP_TRANSPORT",
    "MCP_HOST",
    "MCP_PORT",
    "DATA_DIR",
    "DUCKDB_PATH",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "COURTLISTENER_API_TOKEN",
    "LOG_LEVEL",
    "LOG_FORMAT",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Keep a developer's real .env out of these tests.
    monkeypatch.chdir(tmp_path)


def test_defaults_without_any_env() -> None:
    s = Settings()
    assert s.mcp_transport == "stdio"
    assert s.data_dir == Path("data")
    assert s.resolved_duckdb_path == Path("data/build/courts.duckdb")
    assert s.anthropic_api_key is None
    assert s.openai_api_key is None
    assert s.courtlistener_api_token is None
    assert s.log_level == "INFO"


def test_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", "/srv/data")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("MCP_PORT", "9001")
    s = Settings()
    assert s.resolved_duckdb_path == Path("/srv/data/build/courts.duckdb")
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-test"
    assert s.log_level == "DEBUG"
    assert s.mcp_port == 9001


def test_explicit_duckdb_path_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", "/srv/data")
    monkeypatch.setenv("DUCKDB_PATH", "/tmp/other.duckdb")
    assert Settings().resolved_duckdb_path == Path("/tmp/other.duckdb")


def test_blank_keys_count_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    assert Settings().openai_api_key is None


def test_reads_dotenv_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("COURTLISTENER_API_TOKEN=abc\n")
    token = Settings().courtlistener_api_token
    assert token is not None and token.get_secret_value() == "abc"


def test_secrets_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-very-secret")
    assert "sk-very-secret" not in repr(Settings())


def test_rejects_unknown_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")
    with pytest.raises(ValidationError):
        Settings()


def test_json_logging(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    from courts_analyst.logging_config import configure_logging

    configure_logging("INFO", json_format=True)
    logging.getLogger("courts_analyst.test").info("hello", extra={"table": "C-1"})
    line = capsys.readouterr().err.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["msg"] == "hello"
    assert record["table"] == "C-1"
    assert record["level"] == "INFO"


def test_pretty_logging_goes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    from courts_analyst.logging_config import configure_logging

    configure_logging("INFO", json_format=False)
    logging.getLogger("courts_analyst.test").warning("careful")
    out = capsys.readouterr()
    assert out.out == ""  # stdout is the stdio MCP channel
    assert "careful" in out.err
