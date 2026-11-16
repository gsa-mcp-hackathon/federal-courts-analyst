"""The request desk's write-safety suite on the fixture catalog: every case
behaves as specified (ADR 0013, Phase 9b exit criteria)."""

from __future__ import annotations

from typing import Any

from courts_analyst.evaluation.write_safety import CASES, report, run


def test_every_write_safety_case_passes(core_db: Any) -> None:
    results = run(core_db)
    failed = [(r.id, r.expect, r.observed, r.wrote) for r in results if not r.passed]
    assert not failed, failed
    assert len(results) == len(CASES) >= 15
    assert f"**{len(CASES)} of {len(CASES)} passed.**" in report(results)
