"""Run records must not carry credentials.

IBM's `orchestrate evaluations` writes the IAM access token it used into each
transcript's config.yml. Thirty such files were committed before this check
(2026-11-15/16); the tokens had expired an hour after issue and were
redacted on 2026-11-17."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


def test_no_tokens_in_committed_results() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "eval/results"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    hits = []
    for rel in tracked:
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 20_000_000:
            continue
        text = path.read_text(errors="ignore")
        if JWT.search(text) or re.search(
            r"^\s*token:\s*[A-Za-z0-9_-]{40,}", text, re.M
        ):
            hits.append(rel)
    assert not hits, f"credentials in run records: {hits[:5]}"
