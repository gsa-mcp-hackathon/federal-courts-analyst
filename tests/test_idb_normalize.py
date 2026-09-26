"""Normalizing the delivered IDB text: encoding, control bytes, quoted tabs, schema."""

from __future__ import annotations

from pathlib import Path

import pytest

from courts_analyst.pipeline.idb.normalize import MalformedRowError, normalize_zip
from courts_analyst.pipeline.idb.schema import SchemaError, match_schema
from tests.idb_rows import COLUMNS, row, write_zip


def _lines(path: Path) -> list[list[str]]:
    return [ln.split("\t") for ln in path.read_text(encoding="utf-8").splitlines()]


def test_clean_rows_pass_through(tmp_path: Path) -> None:
    z = write_zip(tmp_path / "a.zip", [row(), row(DOCKET="2000002")])
    stats, cols = normalize_zip(z, "cv88on.txt", tmp_path / "out.tsv")
    assert stats.rows == 2 and stats.columns == 46 and stats.schema == "civil-1988-on"
    assert [c.name for c in cols] == COLUMNS
    out = _lines(tmp_path / "out.tsv")
    assert out[0] == COLUMNS and len(out) == 3
    assert not stats.repaired_rows and stats.control_bytes == 0
    # CRLF is gone; the last field is clean.
    assert out[1][-1] == "2020"


def test_latin1_and_control_bytes(tmp_path: Path) -> None:
    header = "\t".join(COLUMNS).encode()
    bad = row(PLT="XPLT", DEF="XDEF").encode()
    bad = bad.replace(b"XPLT", b"CAF\xc9\x00 INC").replace(b"XDEF", b"A\x1cB")
    z = write_zip(tmp_path / "a.zip", [], raw=header + b"\r\n" + bad + b"\r\n")
    stats, _ = normalize_zip(z, "cv88on.txt", tmp_path / "out.tsv")
    out = _lines(tmp_path / "out.tsv")
    plt, dfn = COLUMNS.index("PLT"), COLUMNS.index("DEF")
    assert out[1][plt] == "CAFÉ  INC"
    assert out[1][dfn] == "A B"
    assert stats.control_bytes == 2 and stats.non_ascii_bytes == 1


def test_quoted_tab_in_party_name_is_repaired(tmp_path: Path) -> None:
    shifted = row(DEF='"\tBUDZIK"')
    assert shifted.count("\t") == 46  # one too many
    z = write_zip(tmp_path / "a.zip", [row(), shifted])
    stats, _ = normalize_zip(z, "cv88on.txt", tmp_path / "out.tsv")
    assert stats.repaired_rows == [3]
    out = _lines(tmp_path / "out.tsv")
    assert len(out[2]) == 46
    assert out[2][COLUMNS.index("DEF")] == " BUDZIK"
    assert out[2][COLUMNS.index("TAPEYEAR")] == "2020"


def test_unrepairable_row_fails_with_line_number(tmp_path: Path) -> None:
    z = write_zip(tmp_path / "a.zip", [row(), row(DEF="A\tB")])
    with pytest.raises(MalformedRowError, match="line 3: 47 fields"):
        normalize_zip(z, "cv88on.txt", tmp_path / "out.tsv")


def test_header_drift_fails_loudly(tmp_path: Path) -> None:
    extra = [*COLUMNS, "NEWCOL"]
    z = write_zip(tmp_path / "a.zip", [], header=extra)
    with pytest.raises(SchemaError, match=r"unknown columns \['NEWCOL'\]"):
        normalize_zip(z, "cv88on.txt", tmp_path / "out.tsv")


def test_schema_messages() -> None:
    assert match_schema(COLUMNS)[0] == "civil-1988-on"
    with pytest.raises(SchemaError, match=r"missing columns \['TAPEYEAR'\]"):
        match_schema(COLUMNS[:-1])
    swapped = [COLUMNS[1], COLUMNS[0], *COLUMNS[2:]]
    with pytest.raises(SchemaError, match="different order"):
        match_schema(swapped)
