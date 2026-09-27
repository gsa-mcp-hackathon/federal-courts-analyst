"""What every REST route shares: the envelope response, error mapping and
ETags.

Routes call the core directly (no model) and return the same ``Result``
envelope the MCP tools return, so the explorer and the agent can't disagree.
``declined`` and ``needs_clarification`` are answers (200). Core errors map
to HTTP statuses by their stable ``code``; the body says what went wrong
and what to call instead, like the MCP tool errors.

ETags are keyed on the data build (both DuckDB files' size and mtime, and
the server version) plus the request URL, so a rebuild invalidates them.
"""

from __future__ import annotations

import functools
import hashlib
from collections.abc import Callable
from typing import Any, ParamSpec

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from courts_analyst import __version__
from courts_analyst.config import settings
from courts_analyst.core.errors import CoreError

P = ParamSpec("P")

STATUS_BY_CODE: dict[str, int] = {
    "unknown_court": 422,
    "unknown_measure": 422,
    "unknown_edition": 422,
    "invalid_cohort": 422,
    "out_of_scope": 422,
    "mixed_editions": 422,
    "not_published": 404,
    "unknown_handle": 404,
    "declined": 200,
    "data_unavailable": 503,
    "timeout": 504,
    "output_too_large": 413,
    "policy_violation": 500,
}
CACHE_SECONDS = 3600


def build_hash() -> str:
    """Changes whenever the data is rebuilt or the server is upgraded."""
    parts = [__version__]
    for path in (settings.resolved_duckdb_path, settings.resolved_idb_path):
        try:
            st = path.stat()
            parts.append(f"{path.name}:{st.st_size}:{st.st_mtime_ns}")
        except OSError:
            parts.append(f"{path.name}:missing")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def error_body(err: CoreError) -> dict[str, Any]:
    return {
        "error": err.code,
        "message": err.message,
        "suggested_next": list(err.suggested_next or []),
    }


def error_response(err: CoreError) -> JSONResponse:
    return JSONResponse(error_body(err), status_code=STATUS_BY_CODE.get(err.code, 500))


def cached_json(request: Request, body: Any) -> Response:
    """A JSON response with an ETag; 304 when the client already has it."""
    tag = (
        '"'
        + hashlib.sha256(
            (
                build_hash()
                + "|"
                + str(request.url.path)
                + "?"
                + str(request.url.query)
            ).encode()
        ).hexdigest()[:24]
        + '"'
    )
    cfg = getattr(request.app.state, "settings", settings)
    scope = "private" if cfg.http_bearer_token else "public"
    headers = {"etag": tag, "cache-control": f"{scope}, max-age={CACHE_SECONDS}"}
    if tag in {t.strip() for t in request.headers.get("if-none-match", "").split(",")}:
        return Response(status_code=304, headers=headers)
    if isinstance(body, BaseModel):
        body = body.model_dump(mode="json")
    return JSONResponse(body, headers=headers)


def envelope(fn: Callable[P, BaseModel]) -> Callable[..., Any]:
    """Wrap a route body that returns a core ``Result``: errors → statuses,
    success → cached JSON. The route must take ``request: Request``."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Response:
        request: Request = kwargs["request"]
        try:
            # DuckDB queries block: keep them off the event loop.
            result = await run_in_threadpool(fn, *args, **kwargs)
        except CoreError as err:
            return error_response(err)
        return cached_json(request, result)

    return wrapper
