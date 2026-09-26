"""Polite, idempotent downloader for uscourts.gov files.

- One request at a time, at least ``min_interval`` seconds apart.
- Retries 429/5xx and network errors with exponential backoff. uscourts.gov sits
  behind Akamai, which answers bursts with 503 for several minutes.
- A file already on disk whose sha256 matches the manifest is never re-requested.
- A file on disk without a pinned sha is revalidated with ``If-Modified-Since``.
- A published edition must not change: if the server returns bytes whose sha256
  differs from the pinned one, :class:`EditionChangedError` is raised and the
  existing file is left untouched.
"""

from __future__ import annotations

import email.utils
import hashlib
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx

log = logging.getLogger("courts_analyst.pipeline.fetch")

USER_AGENT = (
    "Mozilla/5.0 (compatible; FederalCourtsAnalyst/0.1; "
    "+https://github.com/syedaun-techsur/federal-courts-analyst)"
)
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

FetchStatus = Literal["downloaded", "cached", "not_modified"]


class FetchError(RuntimeError):
    """The file couldn't be downloaded after all retries."""


class NotFoundError(FetchError):
    """The server says the file doesn't exist (404/410)."""


class EditionChangedError(RuntimeError):
    """A published edition's bytes changed. Editions are supposed to be fixed."""

    def __init__(self, url: str, expected: str, actual: str) -> None:
        super().__init__(
            f"{url} changed: pinned sha256 {expected[:12]}…, server sent "
            f"{actual[:12]}…. Published editions shouldn't change; check the "
            "file by hand, then update the manifest pin if the change is real."
        )
        self.url, self.expected, self.actual = url, expected, actual


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of one :meth:`Fetcher.fetch` call."""

    url: str
    path: Path
    sha256: str
    status: FetchStatus
    fetched_at: datetime


def sha256_file(path: Path) -> str:
    """Hex sha256 of a file's bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


class Fetcher:
    """Rate-limited HTTP GET with retries, caching and edition pinning."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        min_interval: float = 2.0,
        max_retries: int = 6,
        backoff: float = 20.0,
        max_backoff: float = 300.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(60.0, connect=15.0),
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._backoff = backoff
        self._max_backoff = max_backoff
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self.requests = 0
        """Number of HTTP requests sent (tests use it to prove idempotence)."""

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── HTTP ────────────────────────────────────────────────────────────────
    def _throttle(self) -> None:
        if self._last is not None:
            wait = self._min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        """GET with throttling and retries. Returns 200 or 304 responses."""
        for attempt in range(self._max_retries + 1):
            self._throttle()
            self.requests += 1
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.TransportError as exc:
                reason = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code in (200, 304):
                    return resp
                if resp.status_code in (404, 410):
                    raise NotFoundError(f"{url}: HTTP {resp.status_code}")
                if resp.status_code not in RETRY_STATUS:
                    raise FetchError(f"{url}: HTTP {resp.status_code}")
                reason = f"HTTP {resp.status_code}"
            if attempt == self._max_retries:
                raise FetchError(f"{url}: gave up after {attempt + 1} tries ({reason})")
            delay = min(self._backoff * 2**attempt, self._max_backoff)
            log.warning("%s: %s; retrying in %.0fs", url, reason, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    def get_text(self, url: str) -> str:
        """GET a page and return its text (used for discovery)."""
        return self.get(url).text

    # ── Files ───────────────────────────────────────────────────────────────
    def fetch(
        self, url: str, dest: Path, expected_sha256: str | None = None
    ) -> FetchResult:
        """Download ``url`` to ``dest`` unless an identical copy is already there.

        With ``expected_sha256`` (a pinned, published edition) a matching local
        file means no request at all, and different server bytes raise
        :class:`EditionChangedError`.
        """
        now = datetime.now(UTC)
        if dest.is_file():
            local_sha = sha256_file(dest)
            if expected_sha256 and local_sha == expected_sha256:
                return FetchResult(url, dest, local_sha, "cached", now)
            headers: dict[str, str] = {}
            if not expected_sha256:
                mtime = dest.stat().st_mtime
                headers["If-Modified-Since"] = email.utils.formatdate(
                    mtime, usegmt=True
                )
            resp = self.get(url, headers)
            if resp.status_code == 304:
                return FetchResult(url, dest, local_sha, "not_modified", now)
        else:
            resp = self.get(url)

        body = resp.content
        sha = hashlib.sha256(body).hexdigest()
        if expected_sha256 and sha != expected_sha256:
            raise EditionChangedError(url, expected_sha256, sha)
        if dest.is_file() and sha256_file(dest) == sha:
            return FetchResult(url, dest, sha, "not_modified", now)

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(body)
        if lm := resp.headers.get("Last-Modified"):
            parsed = email.utils.parsedate_to_datetime(lm)
            ts = parsed.timestamp()
            os.utime(tmp, (ts, ts))
        tmp.replace(dest)
        log.info("downloaded %s (%d bytes)", url, len(body))
        return FetchResult(url, dest, sha, "downloaded", now)
