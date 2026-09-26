"""Fetcher: idempotent re-runs, edition pinning, retries and throttling."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from courts_analyst.pipeline.tables.fetch import (
    EditionChangedError,
    Fetcher,
    FetchError,
    NotFoundError,
)

URL = "https://www.uscourts.gov/sites/default/files/data_tables/jb_x1a_0930.2020.xlsx"
BODY = b"edition bytes"
SHA = hashlib.sha256(BODY).hexdigest()


class Server:
    """Scripted responses; records every request."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def make(server: Server, sleeps: list[float] | None = None) -> Fetcher:
    log = sleeps if sleeps is not None else []
    return Fetcher(
        httpx.Client(transport=httpx.MockTransport(server)),
        min_interval=0,
        backoff=1,
        max_retries=2,
        sleep=log.append,
    )


def ok(body: bytes = BODY) -> httpx.Response:
    return httpx.Response(
        200, content=body, headers={"Last-Modified": "Mon, 01 Feb 2021 00:00:00 GMT"}
    )


def test_first_fetch_downloads(tmp_path: Path) -> None:
    server = Server(ok())
    res = make(server).fetch(URL, tmp_path / "a.xlsx")
    assert res.status == "downloaded"
    assert res.sha256 == SHA
    assert (tmp_path / "a.xlsx").read_bytes() == BODY
    # Last-Modified is copied to mtime so later If-Modified-Since is honest.
    assert int((tmp_path / "a.xlsx").stat().st_mtime) == 1612137600


def test_pinned_rerun_makes_no_request(tmp_path: Path) -> None:
    dest = tmp_path / "a.xlsx"
    dest.write_bytes(BODY)
    before = dest.stat().st_mtime_ns
    server = Server(ok())
    fetcher = make(server)
    res = fetcher.fetch(URL, dest, expected_sha256=SHA)
    assert res.status == "cached"
    assert fetcher.requests == 0 and not server.requests
    assert dest.stat().st_mtime_ns == before


def test_unpinned_rerun_sends_if_modified_since(tmp_path: Path) -> None:
    dest = tmp_path / "a.xlsx"
    dest.write_bytes(BODY)
    server = Server(httpx.Response(304))
    res = make(server).fetch(URL, dest)
    assert res.status == "not_modified"
    assert "If-Modified-Since" in server.requests[0].headers
    assert dest.read_bytes() == BODY


def test_unpinned_same_bytes_is_not_a_write(tmp_path: Path) -> None:
    dest = tmp_path / "a.xlsx"
    dest.write_bytes(BODY)
    before = dest.stat().st_mtime_ns
    res = make(Server(ok())).fetch(URL, dest)
    assert res.status == "not_modified"
    assert dest.stat().st_mtime_ns == before


def test_changed_edition_raises_and_keeps_file(tmp_path: Path) -> None:
    dest = tmp_path / "a.xlsx"
    dest.write_bytes(b"corrupted local copy")
    with pytest.raises(EditionChangedError) as err:
        make(Server(ok(b"silently revised"))).fetch(URL, dest, expected_sha256=SHA)
    assert err.value.expected == SHA
    assert dest.read_bytes() == b"corrupted local copy"
    assert not list(tmp_path.glob("*.part"))


def test_changed_edition_on_fresh_download(tmp_path: Path) -> None:
    with pytest.raises(EditionChangedError):
        make(Server(ok(b"other"))).fetch(URL, tmp_path / "a.xlsx", expected_sha256=SHA)
    assert not (tmp_path / "a.xlsx").exists()


def test_retries_503_with_backoff(tmp_path: Path) -> None:
    sleeps: list[float] = []
    server = Server(httpx.Response(503), httpx.Response(503), ok())
    res = make(server, sleeps).fetch(URL, tmp_path / "a.xlsx")
    assert res.status == "downloaded"
    assert len(server.requests) == 3
    assert sleeps == [1, 2]  # exponential


def test_gives_up_after_max_retries(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="gave up after 3 tries"):
        make(Server(httpx.Response(503))).fetch(URL, tmp_path / "a.xlsx")


def test_transport_errors_are_retried(tmp_path: Path) -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return ok()

    fetcher = Fetcher(
        httpx.Client(transport=httpx.MockTransport(flaky)),
        min_interval=0,
        backoff=0,
        sleep=lambda _s: None,
    )
    assert fetcher.fetch(URL, tmp_path / "a.xlsx").status == "downloaded"


def test_404_is_not_retried(tmp_path: Path) -> None:
    server = Server(httpx.Response(404))
    with pytest.raises(NotFoundError):
        make(server).fetch(URL, tmp_path / "a.xlsx")
    assert len(server.requests) == 1


def test_other_4xx_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="HTTP 403"):
        make(Server(httpx.Response(403))).fetch(URL, tmp_path / "a.xlsx")


def test_throttle_spaces_requests() -> None:
    sleeps: list[float] = []
    now = {"t": 100.0}
    fetcher = Fetcher(
        httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x"))
        ),
        min_interval=2.0,
        sleep=sleeps.append,
        clock=lambda: now["t"],
    )
    fetcher.get_text(URL)
    now["t"] += 0.5
    fetcher.get_text(URL)
    assert sleeps == [pytest.approx(1.5)]


def test_context_manager_closes() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with Fetcher(client):
        pass
    assert client.is_closed
