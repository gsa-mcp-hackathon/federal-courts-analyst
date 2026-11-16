"""`make desk-seed / desk-check / desk-reset` (ADR 0013)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from courts_analyst.desk_cli import main


def test_needs_a_store_path(server_data: None, monkeypatch: Any) -> None:
    from courts_analyst.config import settings

    monkeypatch.setattr(settings, "desk_store_path", None)
    assert main(["check"]) == 2


def test_seed_check_reset(
    server_data: None, tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    from courts_analyst.config import settings
    from courts_analyst.tools._common import get_desk

    monkeypatch.setattr(settings, "desk_store_path", tmp_path / "desk.sqlite")
    assert main(["seed"]) == 0
    assert "filed with the statistics office" in capsys.readouterr().out
    assert main(["seed"]) == 0  # idempotent: the same key replays
    assert get_desk().one("SELECT count(*) FROM request")[0] == 1
    assert main(["check"]) == 0
    assert '"citations_checked"' in capsys.readouterr().out
    assert main(["reset"]) == 0
    assert get_desk().one("SELECT count(*) FROM request")[0] == 0
