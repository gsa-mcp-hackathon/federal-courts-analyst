"""Question bank: every item validates, ids are unique, and every expected
official figure and ranking matches the catalog built from committed fixtures."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest
import yaml

from courts_analyst.core.courts import COURTS
from courts_analyst.core.numbers import round_half_up
from courts_analyst.evaluation.bank import (
    DEFAULT_BANK,
    BankError,
    load_bank,
    select,
)
from courts_analyst.evaluation.schema import SUITES, QuestionItem, assign_split

ITEMS = load_bank()
TOOLS = {
    "server_info",
    "get_official_figure",
    "compare_courts",
    "explain_change",
    "find_cases",
    "analyze_cohort",
    "reconcile",
    "judgeship_context",
    "explain_term",
    "sample_dockets",
}


def test_bank_size_and_balance() -> None:
    assert len(ITEMS) >= 150
    counts = {s: len(select(ITEMS, suite=s)) for s in SUITES}
    assert counts["engine"] >= 30
    assert counts["e2e"] >= 50
    assert counts["explanation"] >= 20
    assert counts["tool_selection"] >= 25
    assert counts["adversarial"] >= 25
    held = sum(i.resolved_split == "test" for i in ITEMS) / len(ITEMS)
    assert 0.25 <= held <= 0.35, held
    # Every suite has both splits, so dev tuning can't see everything.
    for s in SUITES:
        splits = {i.resolved_split for i in select(ITEMS, suite=s)}
        assert splits == {"dev", "test"}, s


def test_ids_unique() -> None:
    ids = [i.id for i in ITEMS]
    assert len(ids) == len(set(ids))


def test_behaviours_all_represented() -> None:
    behaviours = {i.expected.behavior for i in ITEMS}
    assert behaviours == {"answer", "clarify", "decline"}


def test_tool_names_are_real() -> None:
    for i in ITEMS:
        assert set(i.expected_tools) <= TOOLS, i.id
        assert set(i.acceptable_tools) <= TOOLS, i.id
        for c in i.claims:
            if c.tool:
                assert c.tool in TOOLS, i.id


def test_courts_are_canonical() -> None:
    for i in ITEMS:
        for f in i.expected.figures:
            if f.ref:
                assert f.ref.court in COURTS, i.id
        for code in i.expected.ranking or []:
            assert code in COURTS, i.id
        if i.expected.engine:
            assert i.expected.engine.court in COURTS, i.id


def test_unreferenced_figures_are_idb_derived() -> None:
    """Every expected figure links to a catalog cell, unless it is computed from
    the IDB (then it's labelled so and carries a relative tolerance)."""
    for i in ITEMS:
        for f in i.expected.figures:
            if f.ref is None:
                assert f.label == "IDB-derived", i.id
                assert f.tolerance_pct, i.id
                assert "idb" in i.tags, i.id


@pytest.mark.parametrize(
    "item",
    [i for i in ITEMS if any(f.ref for f in i.expected.figures)],
    ids=lambda i: i.id,
)
def test_expected_figures_match_catalog(
    con: duckdb.DuckDBPyConnection, item: QuestionItem
) -> None:
    for f in item.expected.figures:
        if f.ref is None:
            continue
        r = f.ref
        row = con.execute(
            """SELECT o.value, m.decimals FROM observation o
               JOIN measure_def m USING (measure_id)
               WHERE measure_id = ? AND court = ? AND fiscal_year = ? AND edition = ?""",
            [r.measure, r.court, r.fiscal_year, r.edition],
        ).fetchone()
        assert row is not None, f"{item.id}: {r} not in the catalog"
        value, decimals = row
        assert round_half_up(value, decimals) == pytest.approx(f.value), item.id
        # Every listed edition prints the same value.
        for ed in f.editions:
            other = con.execute(
                """SELECT value FROM observation WHERE measure_id = ? AND court = ?
                   AND fiscal_year = ? AND edition = ?""",
                [r.measure, r.court, r.fiscal_year, ed],
            ).fetchone()
            assert other is not None, f"{item.id}: {ed}"
            assert round_half_up(other[0], decimals) == pytest.approx(f.value), (
                item.id,
                ed,
            )


@pytest.mark.parametrize(
    "item", [i for i in ITEMS if i.expected.ranking_ref], ids=lambda i: i.id
)
def test_rankings_match_catalog(
    con: duckdb.DuckDBPyConnection, item: QuestionItem
) -> None:
    ref = item.expected.ranking_ref
    assert ref is not None
    order = "DESC" if ref.order == "desc" else "ASC"
    rows = con.execute(
        f"""SELECT court FROM observation
            WHERE edition = ? AND measure_id = ? AND fiscal_year = ?
              AND court NOT LIKE 'CIR%' AND court <> 'US' AND value IS NOT NULL
            ORDER BY value {order} LIMIT ?""",  # order is a Literal, not input
        [ref.edition, ref.measure, ref.fiscal_year, ref.top_n],
    ).fetchall()
    assert [r[0] for r in rows] == item.expected.ranking


def test_revised_figures_require_both_values(con: duckdb.DuckDBPyConnection) -> None:
    """An item whose figure was revised and that doesn't name an edition must
    expect both the current and the first-published value (ADR 0004)."""
    for item in ITEMS:
        if not item.expected.must_mention_revision:
            continue
        assert "revised" in item.tags or "edition_trap" in item.tags, item.id


def _write(tmp: Path, name: str, data: object) -> Path:
    (tmp / name).write_text(yaml.safe_dump(data))
    return tmp


def test_bank_errors(tmp_path: Path) -> None:
    good = {"id": "x-one", "question": "What were filings in FY2020?"}
    with pytest.raises(BankError, match="no question files"):
        load_bank(tmp_path)
    with pytest.raises(BankError, match="file name"):
        load_bank(_write(tmp_path, "misc.yaml", [good]))
    (tmp_path / "misc.yaml").unlink()
    with pytest.raises(BankError, match="list"):
        load_bank(_write(tmp_path, "e2e.yaml", {"a": 1}))
    with pytest.raises(BankError, match="suite"):
        load_bank(_write(tmp_path, "e2e.yaml", [{**good, "suite": "engine"}]))
    with pytest.raises(BankError, match="e2e items need"):
        load_bank(_write(tmp_path, "e2e.yaml", [good]))
    claim = {"id": "c", "kind": "mentions", "any": ["x"]}
    ok = {**good, "claims": [claim]}
    with pytest.raises(BankError, match="duplicate ids"):
        load_bank(_write(tmp_path, "e2e.yaml", [ok, ok]))
    with pytest.raises(BankError, match="mapping"):
        load_bank(_write(tmp_path, "e2e.yaml", ["just text"]))
    assert len(load_bank(_write(tmp_path, "e2e.yaml", [ok]))) == 1


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"id": "Bad_ID"}, "lowercase-kebab"),
        ({"split": "test" if assign_split("x-one") == "dev" else "dev"}, "split"),
        ({"claims": [{"id": "a", "kind": "mentions"}]}, "needs `any` or `all`"),
        ({"claims": [{"id": "a", "kind": "field"}]}, "need `path`"),
        ({"claims": [{"id": "a", "kind": "tool_called"}]}, "needs `tool`"),
        (
            {"expected": {"figures": [{"value": 1, "edition": "2020"}]}},
            "look like JB-2020",
        ),
        (
            {
                "expected": {
                    "figures": [
                        {
                            "value": 1,
                            "edition": "JB-2020",
                            "ref": {
                                "measure": "m",
                                "fiscal_year": 2020,
                                "edition": "JB-2021",
                            },
                        }
                    ]
                }
            },
            "ref.edition",
        ),
    ],
)
def test_item_validation(patch: dict[str, object], message: str) -> None:
    base: dict[str, object] = {
        "id": "x-one",
        "suite": "e2e",
        "question": "What were filings in FY2020?",
        "claims": [{"id": "c", "kind": "mentions", "any": ["x"]}],
    }
    with pytest.raises(ValueError, match=message):
        QuestionItem.model_validate({**base, **patch})


@pytest.mark.parametrize(
    ("suite", "extra", "message"),
    [
        ("engine", {}, "engine items need"),
        ("tool_selection", {}, "need expected_tools"),
        ("explanation", {}, "need claims"),
        ("adversarial", {}, "needs checks"),
    ],
)
def test_suite_rules(suite: str, extra: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        QuestionItem.model_validate(
            {"id": "x-one", "suite": suite, "question": "Something long enough?"}
            | extra
        )


def test_default_bank_path() -> None:
    assert DEFAULT_BANK.is_dir()
    assert {p.stem for p in DEFAULT_BANK.glob("*.yaml")} == set(SUITES)


def test_smoke_subset() -> None:
    """The `smoke` tag is the cheap default for model runs: small, dev-only
    (never held-out items), every model-facing suite and every tool."""
    smoke = select(ITEMS, tags=["smoke"])
    assert 15 <= len(smoke) <= 25
    assert {i.resolved_split for i in smoke} == {"dev"}
    assert {i.suite for i in smoke} == set(SUITES) - {"engine"}
    tools = {t for i in smoke for t in i.expected_tools}
    assert tools == TOOLS - {"server_info"}
