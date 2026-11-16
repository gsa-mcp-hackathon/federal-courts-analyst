"""HTTP hardening for the streamable-HTTP server (Phase 6).

Pure ASGI middleware, outermost first:

1. **Security headers** on every response (nosniff, no framing, no referrer,
   a locked-down CSP for this JSON API, HSTS).
2. **CORS** with an explicit allowlist (``HTTP_ALLOWED_ORIGINS``); empty means
   no cross-origin browser access at all.
3. **Request size limit** (``HTTP_MAX_REQUEST_BYTES``): 413 on a declared or
   streamed body over the limit.
4. **Rate limit** per client (``HTTP_RATE_LIMIT_PER_MINUTE``; token bucket
   keyed by MCP session id, else client address): 429 with Retry-After.
5. **Bearer token** (``HTTP_BEARER_TOKEN``, optional, for the deployed demo):
   401 without it. ``/health`` and ``/version`` stay open for health checks.

The MCP endpoint's own Host/Origin checks (FastMCP) still apply behind these.
"""

from __future__ import annotations

import hmac
import json
import math
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from courts_analyst.config import Settings

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

OPEN_PATHS = frozenset({"/health", "/version"})

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
)


async def _json(send: Send, status: int, body: dict[str, Any], headers=()) -> None:  # type: ignore[no-untyped-def]
    raw = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(raw)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": raw})


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k, v) for k, v in SECURITY_HEADERS if k not in present
                ]
            await send(message)

        await self.app(scope, receive, with_headers)


class BodyTooLarge(Exception):
    pass


class RequestSizeLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for k, v in scope.get("headers", []):
            if k == b"content-length" and v.isdigit() and int(v) > self.max_bytes:
                await self._reject(send)
                return
        seen = 0
        started = False

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise BodyTooLarge
            return message

        async def tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, tracking)
        except BodyTooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        await _json(
            send,
            413,
            {"error": "request_too_large", "max_bytes": self.max_bytes},
        )


class RateLimit:
    """Token bucket per client: ``per_minute`` requests, bursting to that many."""

    def __init__(
        self, app: ASGIApp, per_minute: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.app = app
        self.rate = per_minute / 60.0
        self.capacity = float(per_minute)
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def _key(self, scope: Scope) -> str:
        for k, v in scope.get("headers", []):
            if k == b"mcp-session-id":
                session: str = v.decode(errors="replace")
                return "s:" + session[:128]
        client = scope.get("client") or ("?", 0)
        return "a:" + str(client[0])

    def _take(self, key: str) -> float:
        """0 if allowed, else seconds until a token is available."""
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                if len(self._buckets) > 10_000:
                    self._buckets.pop(next(iter(self._buckets)))
                return 0.0
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / self.rate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in OPEN_PATHS:
            await self.app(scope, receive, send)
            return
        wait = self._take(self._key(scope))
        if wait:
            await _json(
                send,
                429,
                {"error": "rate_limited", "retry_after_seconds": math.ceil(wait)},
                [(b"retry-after", str(math.ceil(wait)).encode())],
            )
            return
        await self.app(scope, receive, send)


class BearerAuth:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected = ("Bearer " + token).encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") in OPEN_PATHS
            or scope.get("method") == "OPTIONS"
        ):
            await self.app(scope, receive, send)
            return
        given = next(
            (v for k, v in scope.get("headers", []) if k == b"authorization"), b""
        )
        if not hmac.compare_digest(given, self.expected):
            await _json(
                send,
                401,
                {"error": "unauthorized"},
                [(b"www-authenticate", b'Bearer realm="federal-courts-analyst"')],
            )
            return
        await self.app(scope, receive, send)


MCP_HEADERS = [
    "authorization",
    "content-type",
    "mcp-session-id",
    "mcp-protocol-version",
    "last-event-id",
]


def http_middleware(settings: Settings) -> list[Middleware]:
    """The middleware stack for ``mcp.run(transport="http", middleware=...)``."""
    stack = [
        Middleware(SecurityHeaders),
        Middleware(
            CORSMiddleware,
            allow_origins=list(settings.http_allowed_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=MCP_HEADERS,
            expose_headers=["mcp-session-id"],
            max_age=600,
        ),
        Middleware(RequestSizeLimit, max_bytes=settings.http_max_request_bytes),
    ]
    if settings.http_rate_limit_per_minute > 0:
        stack.append(
            Middleware(RateLimit, per_minute=settings.http_rate_limit_per_minute)
        )
    if settings.http_bearer_token is not None:
        stack.append(
            Middleware(BearerAuth, token=settings.http_bearer_token.get_secret_value())
        )
    return stack
