"""Golden figures: hand-verified official values come out exactly, with their edition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from courts_analyst.core.numbers import round_half_up

GOLDEN = yaml.safe_load(
    (Path(__file__).parent / "golden" / "official_figures.yaml").read_text()
)


def _id(g: dict[str, Any]) -> str:
    return (
        f"{g['edition']}-{g['table']}-{g['court']}-FY{g['fiscal_year']}-{g['measure']}"
    )


def test_enough_golden_figures() -> None:
    """Plan: the six concept figures plus at least 40 more."""
    assert len(GOLDEN) >= 46
    concept = {
        (g["edition"], g["measure"], g["value"])
        for g in GOLDEN
        if g["court"] == "US" and g["fiscal_year"] == 2020
    }
    for edition, measure, value in [
        ("JB-2020", "authorized_judgeships", 673),
        ("JB-2020", "civil_filings_per_judgeship", 676),
        ("JB-2020", "weighted_civil_filings_per_judgeship", 554),
        ("JFF-2023", "authorized_judgeships", 674),
        ("JFF-2023", "civil_filings_per_judgeship", 675),
        ("JFF-2023", "weighted_civil_filings_per_judgeship", 322),
    ]:
        assert (edition, measure, value) in concept
    assert any(g["court"] == "FL-N" for g in GOLDEN)


@pytest.mark.parametrize("g", GOLDEN, ids=_id)
def test_golden_figure(con: duckdb.DuckDBPyConnection, g: dict[str, Any]) -> None:
    row = con.execute(
        """
        SELECT o.value, o.decimals, o.table_code, s.url
        FROM observation o JOIN source_file s USING (file_id)
        WHERE o.measure_id = ? AND o.court = ? AND o.fiscal_year = ? AND o.edition = ?
        """,
        [g["measure"], g["court"], g["fiscal_year"], g["edition"]],
    ).fetchone()
    assert row is not None, "figure missing from the catalog"
    value, decimals, table, url = row
    printed_decimals = (
        len(str(g["printed"]).split(".", 1)[1]) if "." in str(g["printed"]) else 0
    )
    assert decimals is not None and decimals >= printed_decimals
    assert round_half_up(value, printed_decimals) == g["value"]
    assert table == g["table"]
    assert url == g["source"]
