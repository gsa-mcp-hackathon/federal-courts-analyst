"""Resumable, verified download of the FJC civil IDB file.

The civil file is one ~330 MB zip that the FJC replaces in place every
quarter. So, unlike the uscourts.gov tables:

- The download streams to ``<dest>.part`` and resumes with an HTTP ``Range``
  request after an interruption. ``If-Range`` carries the validator recorded
  when the download started, so a release that changes mid-download restarts
  from zero instead of splicing two releases together.
- The manifest pins one release (sha256, size, Last-Modified, ETag). A local
  file matching the pin means no request at all. If the server now has a
  different release, :class:`ReleaseChangedError` is raised and nothing on
  disk changes, unless the caller accepts the new release (``accept_new``).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from courts_analyst.pipeline.tables.fetch import (
    RETRY_STATUS,
    USER_AGENT,
    FetchError,
    NotFoundError,
    sha256_file,
)

log = logging.getLogger("courts_analyst.pipeline.idb")

DownloadStatus = Literal["cached", "downloaded", "resumed"]


class ReleaseChangedError(RuntimeError):
    """The server has a different release than the one pinned in the manifest."""

    def __init__(self, url: str, expected: str, actual: str) -> None:
        super().__init__(
            f"{url} is a different release than the pinned one (sha256 "
            f"{expected[:12]}… pinned, {actual[:12]}… on the server). The FJC "
            "replaces this file each quarter. Re-run with --accept-new-release "
            "to build from the new release and update data/manifest/idb.yaml."
        )
        self.url, self.expected, self.actual = url, expected, actual


@dataclass(frozen=True, slots=True)
class DownloadResult:
    url: str
    path: Path
    sha256: str
    size: int
    status: DownloadStatus
    last_modified: str | None
    etag: str | None
    requests: int


@dataclass(frozen=True, slots=True)
class Pin:
    """What the manifest knows about the release we build from."""

    sha256: str | None = None


def _validator(resp: httpx.Response) -> str | None:
    value: str | None = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
    return value


class Downloader:
    """Streaming GET with resume, retries and sha256 verification."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        chunk_size: int = 1 << 20,
        max_retries: int = 5,
        backoff: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(120.0, connect=15.0),
        )
        self._chunk = chunk_size
        self._max_retries = max_retries
        self._backoff = backoff
        self._sleep = sleep
        self.requests = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Downloader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def download(
        self, url: str, dest: Path, pin: Pin | None = None, *, accept_new: bool = False
    ) -> DownloadResult:
        """Make ``dest`` hold the pinned release of ``url`` (or the newest one).

        Raises :class:`ReleaseChangedError` when the server's bytes differ from
        the pin and ``accept_new`` is false; ``dest`` is left untouched.
        """
        pin = pin or Pin()
        start = self.requests
        if (
            dest.is_file()
            and pin.sha256
            and not accept_new
            and sha256_file(dest) == pin.sha256
        ):
            return DownloadResult(
                url, dest, pin.sha256, dest.stat().st_size, "cached", None, None, 0
            )

        part = dest.with_name(dest.name + ".part")
        meta_path = dest.with_name(dest.name + ".part.json")
        resumed = False
        headers_seen: dict[str, str | None] = {}
        for attempt in range(self._max_retries + 1):
            meta = _read_meta(meta_path) if part.is_file() else {}
            offset = part.stat().st_size if part.is_file() and meta else 0
            headers = {}
            if offset and meta.get("validator"):
                headers = {"Range": f"bytes={offset}-", "If-Range": meta["validator"]}
            try:
                status = self._stream(url, part, meta_path, headers, headers_seen)
            except (httpx.TransportError, _Retry) as exc:
                if attempt == self._max_retries:
                    raise FetchError(
                        f"{url}: gave up after {attempt + 1} tries"
                    ) from exc
                delay = self._backoff * 2**attempt
                log.warning("%s: %s; resuming in %.0fs", url, exc, delay)
                self._sleep(delay)
                continue
            resumed = resumed or status == 206
            break

        sha = sha256_file(part)
        size = part.stat().st_size
        expected = headers_seen.get("total")
        if expected is not None and int(expected) != size:
            part.unlink()
            meta_path.unlink(missing_ok=True)
            raise FetchError(f"{url}: got {size} bytes, server said {expected}")
        if pin.sha256 and sha != pin.sha256 and not accept_new:
            part.unlink()
            meta_path.unlink(missing_ok=True)
            raise ReleaseChangedError(url, pin.sha256, sha)
        part.replace(dest)
        meta_path.unlink(missing_ok=True)
        log.info("downloaded %s (%d bytes, sha256 %s…)", url, size, sha[:12])
        return DownloadResult(
            url,
            dest,
            sha,
            size,
            "resumed" if resumed else "downloaded",
            headers_seen.get("last_modified"),
            headers_seen.get("etag"),
            self.requests - start,
        )

    def _stream(
        self,
        url: str,
        part: Path,
        meta_path: Path,
        headers: dict[str, str],
        seen: dict[str, str | None],
    ) -> int:
        self.requests += 1
        with self._client.stream("GET", url, headers=headers) as resp:
            if resp.status_code in (404, 410):
                raise NotFoundError(f"{url}: HTTP {resp.status_code}")
            if resp.status_code in RETRY_STATUS:
                raise _Retry(f"HTTP {resp.status_code}")
            if resp.status_code == 206:
                mode = "ab"
                total = resp.headers.get("Content-Range", "").rpartition("/")[2]
            elif resp.status_code == 200:
                mode = "wb"  # fresh start, or the release changed under If-Range
                total = resp.headers.get("Content-Length")
                _write_meta(meta_path, {"validator": _validator(resp)})
            else:
                raise FetchError(f"{url}: HTTP {resp.status_code}")
            seen["total"] = total if total and total.isdigit() else None
            seen["last_modified"] = resp.headers.get("Last-Modified")
            seen["etag"] = resp.headers.get("ETag")
            part.parent.mkdir(parents=True, exist_ok=True)
            with part.open(mode) as out:
                for chunk in resp.iter_bytes(self._chunk):
                    out.write(chunk)
            return resp.status_code


class _Retry(Exception):
    """A retryable HTTP status."""


def _read_meta(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str)}


def _write_meta(path: Path, data: dict[str, str | None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
