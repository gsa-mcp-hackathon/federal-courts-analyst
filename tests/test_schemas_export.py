"""The committed JSON Schemas for the frontend are current (`make schemas`)."""

from __future__ import annotations

from pathlib import Path

from courts_analyst.schemas import OUT, main, render


def test_committed_schemas_are_current() -> None:
    for name, text in render().items():
        path = OUT / name
        assert path.is_file(), f"{name} missing: run `make schemas`"
        assert path.read_text() == text, f"{name} is stale: run `make schemas`"


def test_main_writes_files(tmp_path: Path) -> None:
    assert main(tmp_path) == 0
    assert len(list(tmp_path.glob("*.schema.json"))) == len(render())
