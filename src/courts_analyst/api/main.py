"""The HTTP app: MCP at ``/mcp``, the REST and agent API at ``/api``, and
the web build (``web/dist``, Phase 8) at ``/``, all in one process.

FastMCP's Starlette app is the outer app, so its lifespan (the MCP session
manager), its Host/Origin guard and our hardening middleware
(``http_security``: headers, CORS, size limit, rate limit, bearer token)
cover every route. The FastAPI app is mounted inside it at ``/api``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.routing import Mount

from courts_analyst import SERVER_NAME, __version__
from courts_analyst.api.routes import (
    ask,
    courts,
    desk,
    eval,
    explain,
    figures,
    methodology,
)
from courts_analyst.api.web import WebApp
from courts_analyst.config import Settings, settings
from courts_analyst.http_security import http_middleware

log = logging.getLogger("courts_analyst.api")


def build_api() -> FastAPI:
    api = FastAPI(
        title=f"{SERVER_NAME} API",
        version=__version__,
        description="REST explorer endpoints (same envelopes as the MCP tools) "
        "and the agent's SSE stream.",
        # No Swagger page: the security headers' CSP (default-src 'none') would
        # block its CDN assets. The schema is at /api/openapi.json.
        docs_url=None,
        openapi_url="/openapi.json",
        redoc_url=None,
    )

    @api.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {
                "error": "invalid_request",
                "message": "Some parameters are missing or invalid.",
                "details": jsonable_encoder(
                    [
                        {
                            "loc": e.get("loc"),
                            "msg": e.get("msg"),
                            "type": e.get("type"),
                        }
                        for e in exc.errors()
                    ]
                ),
            },
            status_code=422,
        )

    for module in (figures, courts, explain, eval, methodology, ask, desk):
        api.include_router(module.router)
    return api


def _check_desk(cfg: Settings) -> None:
    """With a persistent desk store, compare saved citations with the catalog
    at startup (ADR 0013: a rebuilt catalog may have revised a cited
    figure). Best effort: the app starts either way."""
    if cfg.desk_store_path is None:
        return
    from courts_analyst.core.desk.service import check_staleness
    from courts_analyst.tools._common import get_db, get_desk

    try:
        report = check_staleness(get_db(), get_desk())
    except Exception:  # missing catalog, unreadable store: log and carry on
        log.warning("desk staleness check skipped", exc_info=True)
        return
    if report.data is not None:
        log.info("desk staleness check", extra=report.data.model_dump())


def build_app(cfg: Settings = settings, **http_app_kwargs: Any) -> Any:
    """The combined ASGI app (what ``app.main`` serves over HTTP)."""
    from courts_analyst.app import mcp

    app = mcp.http_app(
        path="/mcp",
        middleware=http_middleware(cfg),
        allowed_origins=list(cfg.http_allowed_origins) or None,
        **http_app_kwargs,
    )
    api = build_api()
    api.state.settings = cfg
    app.state.api = api
    app.router.routes.insert(0, Mount("/api", app=api))
    _check_desk(cfg)
    if cfg.web_dist_dir.is_dir():
        app.router.routes.append(Mount("/", app=WebApp(cfg.web_dist_dir), name="web"))
    return app
