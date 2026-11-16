"""The IDB manifest (``data/manifest/idb.yaml``): which release we build from.

Committed. It names the file URL, the codebook, the landing page and, once
fetched, the release's sha256, size, Last-Modified and ETag. ``fetch`` fills
the pins; ``build`` records them in the ``idb_release`` table so every figure
can say which IDB release it came from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

MANIFEST_VERSION = 1


@dataclass
class Release:
    """One pinned download."""

    url: str
    sha256: str | None = None
    size: int | None = None
    last_modified: str | None = None
    etag: str | None = None


@dataclass
class IdbManifest:
    dataset: str
    landing_url: str
    codebook: Release
    data: Release
    member: str
    """File name inside the zip."""
    coverage: str
    """The FJC's own description of what the release covers."""
    fy_from: int
    fy_to: int
    notes: list[str] = field(default_factory=list)

    @property
    def file_name(self) -> str:
        return self.data.url.rsplit("/", 1)[-1]


HEADER = """\
# FJC Integrated Database, civil (Phase 2). The FJC replaces the file in place
# each quarter; `python -m courts_analyst.pipeline.idb fetch` pins the release
# we build from (sha256, size, Last-Modified, ETag). A different release on the
# server fails the fetch unless --accept-new-release is given.
"""


def load_manifest(path: Path) -> IdbManifest:
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    if data.get("version") != MANIFEST_VERSION:
        raise ValueError(f"{path}: unsupported manifest version {data.get('version')}")
    return IdbManifest(
        dataset=data["dataset"],
        landing_url=data["landing_url"],
        codebook=Release(**data["codebook"]),
        data=Release(**data["data"]),
        member=data["member"],
        coverage=data["coverage"],
        fy_from=int(data["fy_from"]),
        fy_to=int(data["fy_to"]),
        notes=list(data.get("notes") or []),
    )


def dump_manifest(m: IdbManifest, path: Path) -> None:
    body = {"version": MANIFEST_VERSION, **asdict(m)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        HEADER + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=88)
    )
