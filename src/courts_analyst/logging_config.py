"""Structured logging: JSON lines when serving HTTP, readable text locally.

Logs always go to stderr. In stdio mode stdout carries the MCP JSON-RPC
stream, so a single stray print or log line there breaks the client.

Configured secrets (API keys, the bearer token) are redacted from every
record, message and ``extra=`` field alike, so a key can't reach the logs even
if some code path logs it by mistake.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Attributes every LogRecord has; anything else was passed via `extra=`.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with any `extra=` fields merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


PRETTY_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
REDACTED = "[redacted]"


class RedactSecrets(logging.Filter):
    """Replace secret values anywhere in a record with ``[redacted]``."""

    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self.secrets = [s for s in secrets if s]

    def _clean(self, value: Any) -> Any:
        if isinstance(value, str):
            for s in self.secrets:
                value = value.replace(s, REDACTED)
            return value
        if isinstance(value, dict):
            return {k: self._clean(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return type(value)(self._clean(v) for v in value)
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.secrets:
            return True
        record.msg = self._clean(record.getMessage())
        record.args = None
        for key, value in list(vars(record).items()):
            if key not in _RESERVED:
                setattr(record, key, self._clean(value))
        return True


def configure_logging(
    level: str = "INFO", *, json_format: bool = False, secrets: list[str] | None = None
) -> None:
    """Route our logs to stderr in the chosen format. Safe to call twice."""
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RedactSecrets(secrets or []))
    formatter = (
        JsonFormatter() if json_format else logging.Formatter(PRETTY_FORMAT, "%H:%M:%S")
    )
    handler.setFormatter(formatter)

    logger = logging.getLogger("courts_analyst")
    logger.handlers[:] = [handler]
    logger.setLevel(level)
    logger.propagate = False
