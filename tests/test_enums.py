"""Closed vocabularies match the data they describe."""

from __future__ import annotations

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from courts_analyst.core.courts import COURTS
from courts_analyst.core.enums import (
    DISPOSITION_GROUPS,
    EDITIONS,
    MEASURE_IDS,
    NOS_CODES,
    NOS_GROUPS,
    ORIGIN_GROUPS,
    CourtCode,
    EditionSelector,
    MeasureId,
)
from courts_analyst.core.errors import UnknownMeasureError
from courts_analyst.core.measures import get_measure, idb_measures, registry

from .conftest import MANIFEST_PATH


def test_editions_match_manifest() -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            ed = node.get("edition")
            if isinstance(ed, str):
                found.add(ed)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(manifest)
    assert found == set(EDITIONS)


def test_editions_match_catalog(con) -> None:  # type: ignore[no-untyped-def]
    rows = [
        r[0]
        for r in con.execute(
            "SELECT edition FROM edition ORDER BY pub_order"
        ).fetchall()
    ]
    assert rows == list(EDITIONS)


def test_measures_match_catalog(con) -> None:  # type: ignore[no-untyped-def]
    used = {
        r[0]
        for r in con.execute("SELECT DISTINCT measure_id FROM observation").fetchall()
    }
    assert used == set(MEASURE_IDS)
    for m in registry().values():
        tables = {
            r[0]
            for r in con.execute(
                "SELECT DISTINCT table_code FROM observation WHERE measure_id = ?",
                [m.id],
            ).fetchall()
        }
        assert tables == set(m.tables), m.id


def test_idb_rules() -> None:
    assert {k: m.idb for k, m in idb_measures().items()} == {
        "civil_cases_filed": "filed",
        "civil_cases_terminated": "terminated",
        "civil_cases_pending": "pending",
    }
    assert get_measure("weighted_civil_filings_per_judgeship").family == "per_judgeship"
    assert get_measure("authorized_judgeships").family == "judgeships"
    assert get_measure("civil_median_months_to_disposition").family == "median_months"
    assert get_measure("civil_cases_filed").family == "count"
    with pytest.raises(UnknownMeasureError) as err:
        get_measure("weighted")
    assert "try one of" in err.value.suggested_next[0]


def test_codebook_vocabularies() -> None:
    assert "442" in NOS_CODES and "Civil Rights" in NOS_GROUPS
    assert {"mdl_direct", "mdl_transfer", "original"} <= set(ORIGIN_GROUPS)
    assert set(DISPOSITION_GROUPS) == {
        "transferred_or_remanded",
        "dismissed",
        "judgment",
    }


class _M(BaseModel):
    court: CourtCode
    measure: MeasureId
    edition: EditionSelector = "latest"


def test_schema_lists_every_value() -> None:
    props = _M.model_json_schema()["properties"]
    assert props["court"]["enum"] == list(COURTS)
    assert props["measure"]["enum"] == list(MEASURE_IDS)
    assert props["edition"]["enum"][:2] == ["latest", "first_published"]


@pytest.mark.parametrize(
    "bad",
    [
        {"court": "SDNY", "measure": "civil_cases_filed"},
        {"court": "NY-S", "measure": "filings"},
        {"court": "NY-S", "measure": "civil_cases_filed", "edition": "JB2020"},
    ],
)
def test_invented_values_are_rejected(bad: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        _M.model_validate(bad)
