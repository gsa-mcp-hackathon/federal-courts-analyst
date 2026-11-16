"""The hand-transcribed IDB codebook and data-break registry."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from courts_analyst.core.courts import COURTS, DISTRICTS
from courts_analyst.pipeline.idb.codebook import (
    CODEBOOK_DIR,
    load_codebook,
    load_data_breaks,
)
from courts_analyst.pipeline.idb.schema import CIVIL_1988_ON

CB = load_codebook()

# Row names of JB-2024 Table C-2 that a nature-of-suit group may use.
C2_CATEGORIES = {
    "Contract Actions",
    "Real Property Actions",
    "Tort Actions",
    "Actions Under Statutes",
}


def test_every_coded_column_has_a_codebook_file() -> None:
    fields = {c.field for c in CIVIL_1988_ON if c.role == "code"}
    assert fields <= set(CB), fields - set(CB)
    assert set(CB) == fields


@pytest.mark.parametrize("name", sorted(CB))
def test_codes_have_labels_and_are_unique(name: str) -> None:
    f = CB[name]
    codes = [c.code for c in f.codes]
    assert len(codes) == len(set(codes))
    assert all(c.label.strip() for c in f.codes)
    assert not set(codes) & set(f.missing)


@pytest.mark.parametrize("name", sorted(CB))
def test_validity_ranges_are_ordered(name: str) -> None:
    for c in CB[name].codes:
        if c.valid_from and c.valid_to:
            assert c.valid_from <= c.valid_to, c


def test_districts_cover_every_court_once() -> None:
    courts = [c.court for c in CB["district"].codes]
    assert len(courts) == len(set(courts)) == 94
    assert set(courts) == set(DISTRICTS)


def test_circuits_map_to_registry() -> None:
    assert {c.court for c in CB["circuit"].codes} == {
        code for code, court in COURTS.items() if court.level == "circuit"
    }


def test_origin_13_validity_matches_codebook() -> None:
    o13 = CB["origin"].by_code()["13"]
    assert str(o13.valid_from) == "2016-07-01"
    assert o13.group == "mdl_direct"
    assert CB["origin"].by_code()["6"].group == "mdl_transfer"


def test_nos_codes_placed_in_c2_hierarchy() -> None:
    for c in CB["nos"].codes:
        assert c.category in C2_CATEGORIES, c.code
        assert c.group and c.line, c.code
    # The TCPA is counted with other statutes in C-2, not consumer credit.
    assert CB["nos"].by_code()["485"].group == "Other Statutory Actions"
    assert CB["nos"].by_code()["367"].line == "Health Care/Pharma"


def test_codebook_rejects_bad_files(tmp_path: Path) -> None:
    bad = tmp_path / "origin.yaml"
    base = (CODEBOOK_DIR / "origin.yaml").read_text()
    bad.write_text(base + '  - {code: "1", label: Duplicate}\n')
    with pytest.raises(ValidationError, match="duplicate code"):
        load_codebook.__wrapped__(tmp_path)
    # An unquoted comma in a flow mapping creates a stray key: rejected.
    bad.write_text(base + '  - {code: "99", label: Yes, type unknown}\n')
    with pytest.raises(ValidationError):
        load_codebook.__wrapped__(tmp_path)
    bad.write_text(
        base.replace(
            "valid_from: 2016-07-01", "valid_from: 2016-07-01\n    valid_to: 2015-01-01"
        )
    )
    with pytest.raises(ValidationError, match="valid_from after valid_to"):
        load_codebook.__wrapped__(tmp_path)


def test_codebook_file_name_must_match_field(tmp_path: Path) -> None:
    (tmp_path / "wrong.yaml").write_text((CODEBOOK_DIR / "jury.yaml").read_text())
    with pytest.raises(ValueError, match="must match file name"):
        load_codebook.__wrapped__(tmp_path)


def test_data_breaks_registry() -> None:
    breaks = load_data_breaks()
    ids = {b.id for b in breaks}
    assert {"origin-13-mdl-direct", "nos-485-tcpa", "judge-fields-blank"} <= ids
    for b in breaks:
        assert b.summary and b.detail and b.source
        if b.field in CB:
            known = set(CB[b.field].by_code())
            assert set(b.codes) <= known, b.id


def test_data_breaks_reject_duplicate_ids(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    item = (
        "  - {id: x, field: null, date: 2020-01-01, kind: event, summary: s, "
        "detail: d, source: s}\n"
    )
    p.write_text("breaks:\n" + item + item)
    with pytest.raises(ValueError, match="duplicate"):
        load_data_breaks.__wrapped__(p)
