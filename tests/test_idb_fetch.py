"""Resumable IDB download: cache, resume, release pinning, retries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from courts_analyst.pipeline.idb.fetch import Downloader, Pin, ReleaseChangedError
from courts_analyst.pipeline.tables.fetch import FetchError, NotFoundError

URL = "https://www.fjc.gov/sites/default/files/idb/textfiles/cv88on.zip"
BODY = bytes(range(256)) * 40  # 10 KiB
SHA = hashlib.sha256(BODY).hexdigest()
ETAG = '"r1"'


class Server:
    """Serves BODY (or a new release), honouring Range/If-Range like Apache."""

    def __init__(self, body: bytes = BODY, etag: str = ETAG) -> None:
        self.body, self.etag = body, etag
        self.requests: list[httpx.Request] = []
        self.script: list[httpx.Response] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.script:
            return self.script.pop(0)
        headers = {"ETag": self.etag, "Last-Modified": "Wed, 26 Aug 2026 15:28:04 GMT"}
        rng = request.headers.get("Range")
        if rng and request.headers.get("If-Range") == self.etag:
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            part = self.body[start:]
            headers["Content-Range"] = (
                f"bytes {start}-{len(self.body) - 1}/{len(self.body)}"
            )
            return httpx.Response(206, content=part, headers=headers)
        return httpx.Response(200, content=self.body, headers=headers)


def make(server: Server) -> Downloader:
    client = httpx.Client(transport=httpx.MockTransport(server))
    return Downloader(client, chunk_size=1024, backoff=0, sleep=lambda _: None)


def test_fresh_download(tmp_path: Path) -> None:
    server = Server()
    res = make(server).download(URL, tmp_path / "cv.zip")
    assert res.status == "downloaded" and res.sha256 == SHA and res.size == len(BODY)
    assert res.etag == ETAG and res.last_modified
    assert (tmp_path / "cv.zip").read_bytes() == BODY
    assert not list(tmp_path.glob("*.part*"))


def test_pinned_local_file_sends_no_request(tmp_path: Path) -> None:
    (tmp_path / "cv.zip").write_bytes(BODY)
    server = Server()
    res = make(server).download(URL, tmp_path / "cv.zip", Pin(SHA))
    assert res.status == "cached" and res.requests == 0 and not server.requests


def test_resume_uses_range_and_if_range(tmp_path: Path) -> None:
    part = tmp_path / "cv.zip.part"
    part.write_bytes(BODY[:3000])
    (tmp_path / "cv.zip.part.json").write_text(json.dumps({"validator": ETAG}))
    server = Server()
    res = make(server).download(URL, tmp_path / "cv.zip", Pin(SHA))
    assert res.status == "resumed"
    req = server.requests[0]
    assert req.headers["Range"] == "bytes=3000-" and req.headers["If-Range"] == ETAG
    assert (tmp_path / "cv.zip").read_bytes() == BODY


def test_release_changed_mid_download_restarts(tmp_path: Path) -> None:
    """If-Range fails (new release) → server sends 200 → start over, not splice."""
    part = tmp_path / "cv.zip.part"
    part.write_bytes(b"x" * 3000)
    (tmp_path / "cv.zip.part.json").write_text(json.dumps({"validator": '"old"'}))
    server = Server()
    res = make(server).download(URL, tmp_path / "cv.zip")
    assert res.status == "downloaded"
    assert (tmp_path / "cv.zip").read_bytes() == BODY


def test_new_release_is_refused_and_leaves_file(tmp_path: Path) -> None:
    dest = tmp_path / "cv.zip"
    dest.write_bytes(b"old release")
    old = hashlib.sha256(b"old release").hexdigest()
    new_body = BODY[::-1]
    with pytest.raises(ReleaseChangedError, match="--accept-new-release"):
        make(Server(new_body, '"r2"')).download(URL, dest, Pin(SHA))
    assert dest.read_bytes() == b"old release"
    assert not list(tmp_path.glob("*.part*"))
    # Accepting it replaces the file and reports the new pin.
    res = make(Server(new_body, '"r2"')).download(URL, dest, Pin(old), accept_new=True)
    assert dest.read_bytes() == new_body and res.sha256 != old and res.etag == '"r2"'


def test_retries_transient_errors_then_resumes(tmp_path: Path) -> None:
    server = Server()
    server.script = [httpx.Response(503), httpx.Response(502)]
    res = make(server).download(URL, tmp_path / "cv.zip")
    assert res.sha256 == SHA and len(server.requests) == 3


def test_gives_up_after_retries(tmp_path: Path) -> None:
    server = Server()
    server.script = [httpx.Response(503)] * 10
    with pytest.raises(FetchError, match="gave up"):
        make(server).download(URL, tmp_path / "cv.zip")


def test_not_found_and_other_statuses(tmp_path: Path) -> None:
    server = Server()
    server.script = [httpx.Response(404)]
    with pytest.raises(NotFoundError):
        make(server).download(URL, tmp_path / "cv.zip")
    server.script = [httpx.Response(403)]
    with pytest.raises(FetchError, match="HTTP 403"):
        make(server).download(URL, tmp_path / "cv.zip")


def test_truncated_body_is_rejected(tmp_path: Path) -> None:
    server = Server()
    server.script = [
        httpx.Response(
            200, content=BODY[:100], headers={"Content-Length": str(len(BODY))}
        )
    ]
    with pytest.raises((FetchError, httpx.HTTPError)):
        make(server).download(URL, tmp_path / "cv.zip")
    assert not (tmp_path / "cv.zip").exists()
