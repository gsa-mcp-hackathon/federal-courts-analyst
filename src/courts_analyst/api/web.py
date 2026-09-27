"""The web build (``web/dist``) at ``/``: static files, the SPA fallback,
cache headers and a CSP for HTML pages.

- A file that exists is served. Vite's hashed ``/assets/*`` are immutable
  for a year; everything else must revalidate.
- Any other ``GET`` without a file extension gets ``index.html``, so deep
  links (``/editions/…``, ``/courts/FL-N``) work.
- Pages get their own CSP (scripts, styles, fonts and requests from this
  origin only; inline style attributes allowed because the SVG charts use
  them). The strict API CSP (``default-src 'none'``) stays on ``/api`` and
  ``/mcp``: ``SecurityHeaders`` only adds headers a response doesn't set.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.types import Receive, Scope, Send

PAGE_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


class WebApp:
    """ASGI app serving a Vite build with an ``index.html`` fallback."""

    def __init__(self, dist: Path) -> None:
        self.dist = dist.resolve()
        self.index = self.dist / "index.html"

    def _file(self, path: str) -> Path | None:
        rel = PurePosixPath(path.lstrip("/"))
        if any(part in ("..", "") for part in rel.parts) and str(rel) != ".":
            return None
        candidate = (self.dist / rel).resolve()
        if not candidate.is_relative_to(self.dist) or not candidate.is_file():
            return None
        return candidate

    def _response(self, path: str) -> Response:
        file = self._file(path) if path not in ("", "/") else None
        if file is not None:
            cache = IMMUTABLE if path.startswith("/assets/") else REVALIDATE
            return FileResponse(file, headers=self._headers(cache))
        if PurePosixPath(path).suffix or not self.index.is_file():
            return PlainTextResponse("Not found", status_code=404)
        return FileResponse(self.index, headers=self._headers(REVALIDATE))

    @staticmethod
    def _headers(cache: str) -> dict[str, Any]:
        return {"cache-control": cache, "content-security-policy": PAGE_CSP}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - lifespan is the outer app's
            return
        if scope["method"] not in ("GET", "HEAD"):
            response: Response = PlainTextResponse(
                "Method not allowed", status_code=405, headers={"allow": "GET, HEAD"}
            )
        else:
            response = self._response(scope["path"])
        await response(scope, receive, send)
