"""HTTP hardening: CORS allowlist, security headers, size limit, rate limit,
bearer token (when enabled), and secret redaction in logs."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient

from courts_analyst.app import mcp
from courts_analyst.config import Settings
from courts_analyst.http_security import SECURITY_HEADERS, RateLimit, http_middleware
from courts_analyst.logging_config import JsonFormatter, RedactSecrets

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}
ALLOWED = "https://analyst.example.gov"


def _client(**overrides: object) -> Iterator[TestClient]:
    s = Settings(_env_file=None, **overrides)  # type: ignore[call-arg]
    app = mcp.http_app(middleware=http_middleware(s))
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from _client(http_allowed_origins=[ALLOWED], http_max_request_bytes=4096)


@pytest.fixture
def authed() -> Iterator[TestClient]:
    yield from _client(http_bearer_token=SecretStr("s3cret-token-value"))


def test_security_headers_everywhere(client: TestClient) -> None:
    for r in (
        client.get("/health"),
        client.post("/mcp", json=INIT, headers=MCP_HEADERS),
    ):
        for k, v in SECURITY_HEADERS:
            assert r.headers[k.decode()] == v.decode()


def test_mcp_still_works(client: TestClient) -> None:
    r = client.post("/mcp", json=INIT, headers=MCP_HEADERS)
    assert r.status_code == 200
    assert "federal-courts-analyst" in r.text or "serverInfo" in r.text


def test_cors_allowlist(client: TestClient) -> None:
    pre = {
        "access-control-request-method": "POST",
        "access-control-request-headers": "content-type",
    }
    ok = client.options("/mcp", headers={"origin": ALLOWED, **pre})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ALLOWED
    bad = client.options("/mcp", headers={"origin": "https://evil.example", **pre})
    assert bad.status_code == 400
    assert "access-control-allow-origin" not in bad.headers
    simple = client.get("/health", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_request_size_limit(client: TestClient) -> None:
    big = json.dumps({**INIT, "pad": "x" * 5000})
    r = client.post("/mcp", content=big, headers=MCP_HEADERS)
    assert r.status_code == 413 and r.json()["error"] == "request_too_large"

    def chunks() -> Iterator[bytes]:  # no content-length: counted as it streams
        yield big[:3000].encode()
        yield big[3000:].encode()

    r = client.post("/mcp", content=chunks(), headers=MCP_HEADERS)
    assert r.status_code == 413


def test_bearer_token(authed: TestClient) -> None:
    assert authed.get("/health").status_code == 200  # health checks stay open
    assert authed.get("/version").status_code == 200
    r = authed.post("/mcp", json=INIT, headers=MCP_HEADERS)
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
    wrong = {**MCP_HEADERS, "authorization": "Bearer nope"}
    assert authed.post("/mcp", json=INIT, headers=wrong).status_code == 401
    good = {**MCP_HEADERS, "authorization": "Bearer s3cret-token-value"}
    assert authed.post("/mcp", json=INIT, headers=good).status_code == 200


def test_no_auth_by_default(client: TestClient) -> None:
    assert client.post("/mcp", json=INIT, headers=MCP_HEADERS).status_code == 200


async def test_rate_limit_token_bucket() -> None:
    now = [0.0]
    calls = []

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        calls.append(1)

    sent: list[dict] = []  # type: ignore[type-arg]

    async def send(m):  # type: ignore[no-untyped-def]
        sent.append(m)

    limiter = RateLimit(app, per_minute=3, clock=lambda: now[0])
    scope = {"type": "http", "path": "/mcp", "headers": [], "client": ("1.2.3.4", 1)}
    for _ in range(3):
        await limiter(scope, None, send)  # type: ignore[arg-type]
    assert len(calls) == 3
    await limiter(scope, None, send)  # type: ignore[arg-type]
    assert sent[0]["status"] == 429
    assert dict(sent[0]["headers"])[b"retry-after"] == b"20"
    now[0] = 20.0  # one token back
    await limiter(scope, None, send)  # type: ignore[arg-type]
    assert len(calls) == 4
    other = {**scope, "client": ("5.6.7.8", 1)}
    await limiter(other, None, send)  # type: ignore[arg-type]
    assert len(calls) == 5  # buckets are per client
    await limiter({**scope, "path": "/health"}, None, send)  # type: ignore[arg-type]
    assert len(calls) == 6  # health is never limited


def test_origins_parse_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_ALLOWED_ORIGINS", "https://a.example/, https://b.example")
    assert Settings(_env_file=None).http_allowed_origins == [  # type: ignore[call-arg]
        "https://a.example",
        "https://b.example",
    ]


def test_secrets_redacted_from_logs() -> None:
    secret = "sk-ant-THIS-IS-A-TEST-KEY"
    record = logging.makeLogRecord(
        {"msg": "calling with %s", "args": (secret,), "headers": {"x-api-key": secret}}
    )
    RedactSecrets([secret]).filter(record)
    line = JsonFormatter().format(record)
    assert secret not in line and "[redacted]" in line


def test_settings_collect_secrets() -> None:
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        anthropic_api_key=SecretStr("sk-ant-1234567890"),
        http_bearer_token=SecretStr("bearer-1234567890"),
    )
    assert set(s.secrets()) == {"sk-ant-1234567890", "bearer-1234567890"}
