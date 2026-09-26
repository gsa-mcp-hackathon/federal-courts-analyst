"""Structured logging: JSON lines when serving HTTP, readable text locally.

Logs always go to stderr. In stdio mode stdout carries the MCP JSON-RPC
stream, so a single stray print or log line there breaks the client.
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


def configure_logging(level: str = "INFO", *, json_format: bool = False) -> None:
    """Route our logs to stderr in the chosen format. Safe to call twice."""
    handler = logging.StreamHandler(sys.stderr)
    formatter = (
        JsonFormatter() if json_format else logging.Formatter(PRETTY_FORMAT, "%H:%M:%S")
    )
    handler.setFormatter(formatter)

    logger = logging.getLogger("courts_analyst")
    logger.handlers[:] = [handler]
    logger.setLevel(level)
    logger.propagate = False
