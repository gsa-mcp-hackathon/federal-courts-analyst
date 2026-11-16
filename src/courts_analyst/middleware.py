"""Request logging for tool calls: name, argument hash, latency, result size.

Arguments are logged as a hash, not verbatim, so logs never hold what a user
typed; ``LOG_TOOL_ARGUMENTS=true`` with ``LOG_LEVEL=DEBUG`` adds them verbatim
for local debugging only. OpenTelemetry spans for Phoenix come in Phase 10.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

from courts_analyst.config import settings

logger = logging.getLogger("courts_analyst.requests")


def args_hash(arguments: dict[str, Any] | None) -> str:
    blob = json.dumps(arguments or {}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:12]


class RequestLogging(Middleware):
    async def on_call_tool(
        self, context: MiddlewareContext[Any], call_next: Any
    ) -> Any:
        name = getattr(context.message, "name", "?")
        arguments = getattr(context.message, "arguments", None)
        start = time.perf_counter()
        status = "ok"
        size = None
        try:
            result = await call_next(context)
            structured = getattr(result, "structured_content", None)
            if structured is not None:
                size = len(json.dumps(structured, default=str))
                if isinstance(structured, dict) and structured.get("status"):
                    status = str(structured["status"])
            return result
        except Exception as exc:
            status = f"error:{type(exc).__name__}"
            raise
        finally:
            extra: dict[str, Any] = {
                "tool": name,
                "args_sha": args_hash(arguments),
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "result_bytes": size,
                "status": status,
            }
            if settings.log_tool_arguments and logger.isEnabledFor(logging.DEBUG):
                extra["arguments"] = arguments
            logger.info("tool call", extra=extra)
