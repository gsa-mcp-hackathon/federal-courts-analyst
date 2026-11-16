"""Read an xlsx or PDF table into one neutral shape: a :class:`Grid`.

A grid has a title, the notes printed under the table, one header *path* per
value column ("Weighted Filings per Judgeship Civil") and the data rows. Table
parsers then map header paths to measures by label, never by position, so a
table whose columns move between editions still parses to the same schema.

- **xlsx:** header paths come from the header rows, expanding merged cells and
  filling a blank group header from the left within the same parent group.
- **PDF:** columns come from the x-positions of the numbers in the data rows.
  Header words attach to the column they sit over. Phrases that the table
  family names as *group* headers ("Unweighted Filings per Judgeship") span
  every column between the midpoints to their neighbouring group headers.

Each cell keeps what was printed (``text``), the parsed number, how many
decimals were displayed, any footnote markers, and a ``ref`` to the exact
spreadsheet cell or PDF page/line/column.
"""

from __future__ import annotations

import itertools
import re
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARKERS = "¹²³⁴⁵⁶⁷⁸⁹⁰*†‡§"
_MARKER_RE = re.compile(f"[{re.escape(MARKERS)}]")
_NA = {"", "-", "–", "—", "na", "n/a", "nan", "(x)", "x", "--", "…"}
_NUMBER = re.compile(r"^\(?-?\d[\d,]*(\.\d+)?\)?$|^-?\.\d+$")


class GridError(ValueError):
    """The file doesn't look like the table we expected."""


@dataclass(frozen=True, slots=True)
class Cell:
    """One printed value."""

    text: str
    value: float | None
    decimals: int | None
    markers: tuple[str, ...]
    ref: str


@dataclass(slots=True)
class Row:
    """A data row: its label as printed, plus one cell (or None) per column."""

    label: str
    label_markers: tuple[str, ...]
    label_ref: str
    cells: list[Cell | None]


@dataclass(slots=True)
class Grid:
    """A parsed table, independent of the file format."""

    title: str
    headers: list[str]
    """Header path per value column, as printed (markers kept)."""
    rows: list[Row]
    notes: list[str] = field(default_factory=list)
    """Note paragraphs printed with the table, in order."""
    pages: int = 1
    page_headers: list[list[str]] = field(default_factory=list)
    """PDF only: the header paths read on each page that repeats the header.
    Parsers check they map to the same measures (text can differ: typos)."""


# ── Cell text helpers ───────────────────────────────────────────────────────


def split_markers(text: str) -> tuple[str, tuple[str, ...]]:
    """``'Judgeships ¹'`` → ``('Judgeships', ('¹',))``."""
    markers = tuple(_MARKER_RE.findall(text))
    return " ".join(_MARKER_RE.sub(" ", text).split()), markers


def parse_number(text: str) -> tuple[float | None, int | None, bool]:
    """Parse a printed number. Returns ``(value, decimals, is_number)``.

    Dashes and NA markers give ``(None, None, True)``: a real "no value" cell.
    Text that isn't a number gives ``(None, None, False)``.
    """
    t = text.strip().replace(" ", "")
    if t.lower() in _NA:
        return None, None, True
    if not _NUMBER.match(t):
        return None, None, False
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "")
    decimals = len(t.split(".", 1)[1]) if "." in t else 0
    value = float(t)
    return (-value if neg else value), decimals, True


def normalize_header(path: str) -> str:
    """Lowercase words only, for matching header paths against rules."""
    text, _ = split_markers(path)
    text = text.replace("U.S.", "US").replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _decimals_from_format(fmt: str | None) -> int | None:
    if not fmt or fmt == "General":
        return None
    section = fmt.split(";", 1)[0]
    m = re.search(r"0\.(0+)", section)
    if m:
        return len(m.group(1))
    return 0 if "0" in section or "#" in section else None


def _general_decimals(value: float) -> int:
    """Decimals Excel shows for a General cell (up to ~10 significant digits)."""
    text = f"{value:.10g}"
    return len(text.split(".", 1)[1]) if "." in text and "e" not in text else 0


# ── xlsx ────────────────────────────────────────────────────────────────────

RowLabelTest = Callable[[str], bool]


def read_xlsx(path: Path, is_row_label: RowLabelTest, sheet: int = 0) -> Grid:
    """Read the first worksheet of an official table workbook."""
    import openpyxl

    with warnings.catch_warnings():
        # Many AO workbooks lack a default style; openpyxl warns and copes.
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[sheet]
    merged_origin: dict[tuple[int, int], tuple[int, int]] = {}
    for rng in ws.merged_cells.ranges:
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                merged_origin[(r, c)] = (rng.min_row, rng.min_col)

    grid_rows = [list(r) for r in ws.iter_rows(max_row=6)]
    ncols = ws.max_column

    def text(r: int, c: int) -> str:
        v = ws.cell(row=r, column=c).value
        return "" if v is None else str(v).replace("_x000D_", "").strip()

    def merged_text(r: int, c: int) -> str:
        origin = merged_origin.get((r, c))
        return text(*origin) if origin else text(r, c)

    # Title: the first non-empty text cell mentioning "Table".
    title = ""
    title_row = 0
    for row in grid_rows[:6]:
        for cell in row:
            if isinstance(cell.value, str) and "table" in cell.value.lower():
                title, title_row = text(cell.row, cell.column), cell.row
                break
        if title:
            break
    if not title:
        raise GridError(f"{path.name}: no table title found")

    # Data rows: column-A labels that the family recognises.
    data_rows = [
        r
        for r in range(title_row + 1, ws.max_row + 1)
        if text(r, 1) and is_row_label(split_markers(text(r, 1))[0])
    ]
    if not data_rows:
        raise GridError(f"{path.name}: no data rows recognised")
    first, last = data_rows[0], data_rows[-1]

    header_rows = [
        r
        for r in range(title_row + 1, first)
        if any(merged_text(r, c) for c in range(2, ncols + 1))
    ]

    def own(r: int, c: int) -> bool:
        """True unless (r, c) is a non-origin cell inside a merged range."""
        origin = merged_origin.get((r, c))
        return origin is None or origin == (r, c)

    def is_value_cell(r: int, c: int) -> bool:
        t = text(r, c)
        return bool(t) and own(r, c) and parse_number(split_markers(t)[0])[2]

    # Value columns: any column holding a number (or a dash) in a data row.
    value_cols = [
        c for c in range(2, ncols + 1) if any(is_value_cell(r, c) for r in data_rows)
    ]

    # Header paths, filling blank group headers from the left within a parent.
    levels: list[list[str]] = []
    for i, r in enumerate(header_rows):
        level = [merged_text(r, c) for c in range(1, ncols + 1)]
        is_leaf = i == len(header_rows) - 1
        if not is_leaf:
            for c in range(1, ncols):
                if level[c] or (r, c + 1) in merged_origin:
                    continue
                parent_same = all(levels[j][c] == levels[j][c - 1] for j in range(i))
                if level[c - 1] and parent_same and c + 1 in value_cols:
                    level[c] = level[c - 1]
        levels.append(level)

    headers = [
        " ".join(dict.fromkeys(lv[c - 1] for lv in levels if lv[c - 1])).strip()
        for c in value_cols
    ]

    rows: list[Row] = []
    for r in data_rows:
        label, label_markers = split_markers(text(r, 1))
        cells: list[Cell | None] = []
        for c in value_cols:
            cell = ws.cell(row=r, column=c)
            raw = text(r, c)
            if not own(r, c):
                cells.append(None)
                continue
            cells.append(
                _xlsx_cell(
                    cell.value, raw, cell.number_format, f"{ws.title}!{cell.coordinate}"
                )
            )
        # A marker printed in its own cell right of a value belongs to that value.
        for idx, c in enumerate(value_cols):
            m = split_markers(text(r, c + 1))
            if c + 1 not in value_cols and not m[0] and m[1] and cells[idx]:
                old = cells[idx]
                assert old is not None
                cells[idx] = Cell(
                    old.text, old.value, old.decimals, old.markers + m[1], old.ref
                )
        rows.append(Row(label, label_markers, f"{ws.title}!A{r}", cells))

    notes = [
        text(r, c)
        for r in range(last + 1, ws.max_row + 1)
        for c in range(1, ncols + 1)
        if own(r, c) and len(text(r, c)) > 3
    ]
    return Grid(title=title, headers=headers, rows=rows, notes=_dedupe(notes))


def _xlsx_cell(
    value: Any, raw: str, number_format: str | None, ref: str
) -> Cell | None:
    if value is None:
        return None
    if isinstance(value, bool):  # pragma: no cover - never in these tables
        return None
    if isinstance(value, int | float):
        dec = _decimals_from_format(number_format)
        if dec is None:
            dec = _general_decimals(float(value))
        return Cell(raw, float(value), dec, (), ref)
    body, markers = split_markers(raw)
    num, dec, ok = parse_number(body)
    if not ok:
        return None
    return Cell(raw, num, dec, markers, ref)


def _dedupe(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i.strip()))


# ── PDF ─────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Word:
    text: str
    x0: float
    x1: float
    top: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def _page_words(page: Any) -> list[_Word]:
    """Words on a page; tiny digits set against a word become footnote markers.

    Some editions print footnote markers as small plain digits ("2015" then a
    raised "1") rather than superscript characters.
    """
    raw = page.extract_words(extra_attrs=["size"])
    if not raw:
        return []
    sizes = sorted(float(w["size"]) for w in raw)
    body = sizes[len(sizes) // 2]
    out: list[_Word] = []
    for w in raw:
        word = _Word(w["text"], float(w["x0"]), float(w["x1"]), float(w["top"]))
        small = float(w["size"]) < 0.8 * body
        if small and re.fullmatch(r"\d{1,2}", word.text) and out:
            prev = out[-1]
            if 0 <= word.x0 - prev.x1 <= 3 and abs(prev.top - word.top) <= 4:
                out[-1] = _Word(
                    prev.text + word.text.translate(_SUPERSCRIPT),
                    prev.x0,
                    word.x1,
                    prev.top,
                )
                continue
        out.append(word)
    return out


def _lines(words: list[_Word], tol: float = 4.0) -> list[list[_Word]]:
    out: list[list[_Word]] = []
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        if out and abs(out[-1][0].top - w.top) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in out]


def _phrases(line: list[_Word], gap: float = 4.0) -> list[_Word]:
    """Join words closer than ``gap`` points into phrases."""
    out: list[_Word] = []
    for w in line:
        if out and w.x0 - out[-1].x1 <= gap:
            p = out[-1]
            out[-1] = _Word(f"{p.text} {w.text}", p.x0, w.x1, p.top)
        else:
            out.append(_Word(w.text, w.x0, w.x1, w.top))
    return out


def _is_value(text: str) -> bool:
    body, _ = split_markers(text)
    return bool(body) and parse_number(body)[2]


@dataclass(slots=True)
class _Column:
    x0: float
    x1: float

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2


_TITLE_END = re.compile(r"period[s]? ending|during the|continued\)?$", re.I)


def read_pdf(
    path: Path,
    is_row_label: RowLabelTest,
    group_headers: Sequence[str] = (),
    group_fit: str = "midpoint",
) -> Grid:
    """Read a text-based official table PDF (all pages) into a :class:`Grid`."""
    import pdfplumber

    group_res = [re.compile(g, re.I) for g in group_headers]
    title = ""
    headers: list[str] | None = None
    columns: list[_Column] | None = None
    rows: list[Row] = []
    notes: list[str] = []
    page_headers: list[list[str]] = []

    with pdfplumber.open(path) as pdf:
        npages = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, start=1):
            words = _page_words(page)
            lines = _lines(words)
            data_idx = [i for i, ln in enumerate(lines) if _data_line(ln, is_row_label)]
            if not data_idx:
                continue
            first = data_idx[0]
            # Title block ends at the line with "Period Ending" / "During the".
            title_end = next(
                (i for i in range(first) if _TITLE_END.search(_text(lines[i]))), -1
            )
            if not title and title_end >= 0:
                title = "\n".join(_text(lines[i]) for i in range(title_end + 1))
            header_lines = lines[title_end + 1 : first] if title_end >= 0 else []

            # Every page gets its own columns: continuation pages are often
            # shifted, and repeat the header (which must say the same thing).
            columns = _columns([lines[i] for i in data_idx])
            if header_lines:
                this_page = _pdf_headers(header_lines, columns, group_res, group_fit)
                page_headers.append(this_page)
                if headers is None:
                    headers = this_page
            elif headers is None:
                raise GridError(f"{path.name} p{pno}: data before any header")
            if len(columns) != len(headers):
                raise GridError(
                    f"{path.name} p{pno}: {len(columns)} value columns but "
                    f"{len(headers)} headers"
                )

            for i in data_idx:
                rows.append(_pdf_row(lines[i], columns, pno, i))
            tail = lines[data_idx[-1] + 1 :]
            notes.extend(_pdf_notes(tail))

    if not rows or headers is None:
        raise GridError(f"{path.name}: no data rows recognised")
    return Grid(
        title=title,
        headers=headers,
        rows=rows,
        notes=_dedupe(notes),
        pages=npages,
        page_headers=page_headers,
    )


def _text(line: list[_Word]) -> str:
    return " ".join(w.text for w in line)


def _label_and_values(line: list[_Word]) -> tuple[list[_Word], list[_Word]]:
    """Label = first word plus following non-value words; then the values."""
    label = [line[0]]
    i = 1
    while i < len(line) and not _is_value(line[i].text):
        label.append(line[i])
        i += 1
    return label, [
        w for w in line[i:] if _is_value(w.text) or not split_markers(w.text)[0]
    ]


def _data_line(line: list[_Word], is_row_label: RowLabelTest) -> bool:
    label, values = _label_and_values(line)
    text, _ = split_markers(" ".join(w.text for w in label))
    return bool(values) and bool(text) and is_row_label(text)


def _columns(lines: list[list[_Word]]) -> list[_Column]:
    """Cluster value words across data lines by right edge (numbers align right)."""
    cols: list[_Column] = []
    for line in lines:
        _, values = _label_and_values(line)
        for w in values:
            if not split_markers(w.text)[0]:
                continue
            for c in cols:
                if abs(c.x1 - w.x1) <= 6 or (w.x0 < c.x1 and w.x1 > c.x0):
                    c.x0, c.x1 = min(c.x0, w.x0), max(c.x1, w.x1)
                    break
            else:
                cols.append(_Column(w.x0, w.x1))
    cols.sort(key=lambda c: c.x1)
    return cols


def _nearest(cols: list[_Column], x: float) -> int:
    return min(range(len(cols)), key=lambda i: abs(cols[i].xc - x))


def _zones(cols: list[_Column]) -> list[tuple[float, float]]:
    """Horizontal zone of each column: halfway to its neighbours."""
    xs = [c.xc for c in cols]
    half = (xs[1] - xs[0]) / 2 if len(xs) > 1 else (cols[0].x1 - cols[0].x0)
    bounds = [xs[0] - half] + [(a + b) / 2 for a, b in itertools.pairwise(xs)]
    bounds.append(xs[-1] + ((xs[-1] - xs[-2]) / 2 if len(xs) > 1 else half))
    return list(itertools.pairwise(bounds))


def _group_blocks(
    groups: list[_Word], cols: list[_Column], leaves: list[str] | None = None
) -> list[tuple[int, int]] | None:
    """Assign each group header a contiguous block of columns.

    Group labels are centred over the columns they cover, and blocks on one
    line sit side by side. Try every split into adjacent blocks and keep the
    one whose block centres best match the label centres; leaving columns at
    the right edge uncovered is penalised (group rows run to the table edge),
    uncovered columns at the left (the judgeship count, say) are not.

    With ``leaves`` (the leaf header under each column), blocks under one
    group line repeat the same leaf pattern, so every block must start on a
    column whose leaf matches the first block's first column. Group labels
    that are not quite centred can't then pull a block off its pattern.
    """
    n, k = len(cols), len(groups)
    if k == 0 or k > n:
        return None
    xs = [c.xc for c in cols]
    spacing = (xs[-1] - xs[0]) / max(n - 1, 1)
    best: tuple[float, int, list[tuple[int, int]]] | None = None
    for start in range(n):
        allowed = [
            c
            for c in range(start + 1, n)
            if leaves is None or not leaves[start] or leaves[c] == leaves[start]
        ]
        for end in range(start + k - 1, n):
            if leaves is not None and end + 1 < n and end + 1 not in allowed:
                continue
            for cuts in itertools.combinations([c for c in allowed if c <= end], k - 1):
                edges = [start, *cuts, end + 1]
                blocks = [(edges[i], edges[i + 1] - 1) for i in range(k)]
                cost = sum(
                    (g.xc - (xs[a] + xs[b]) / 2) ** 2
                    for g, (a, b) in zip(groups, blocks, strict=True)
                )
                cost += (n - 1 - end) * (spacing / 2) ** 2
                covered = end - start + 1
                if best is None or (cost, -covered) < (best[0], -best[1]):
                    best = (cost, covered, blocks)
    return best[2] if best else None


def _midpoint_blocks(
    groups: list[_Word], cols: list[_Column]
) -> list[tuple[int, int]] | None:
    """Split columns between group headers at the midpoints of their centres.

    The first group reaches as far left of its centre as it reaches right; the
    last runs to the table edge. Works when groups are centred over equal-width
    blocks (the per-judgeship and median-time tables).
    """
    if not groups:
        return None
    xs = [c.xc for c in cols]
    centres = [g.xc for g in groups]
    blocks: list[tuple[int, int]] = []
    for gi, g in enumerate(groups):
        if len(groups) == 1:
            spacing = (xs[-1] - xs[0]) / max(len(xs) - 1, 1)
            left, right = g.x0 - spacing / 2, g.x1 + spacing / 2
        else:
            right = (
                (centres[gi] + centres[gi + 1]) / 2
                if gi + 1 < len(groups)
                else float("inf")
            )
            if gi > 0:
                left = (centres[gi - 1] + centres[gi]) / 2
            else:
                left = centres[0] - ((centres[0] + centres[1]) / 2 - centres[0])
        inside = [i for i, x in enumerate(xs) if left <= x < right]
        if not inside:
            return None
        blocks.append((inside[0], inside[-1]))
    return blocks


def _pdf_headers(
    header_lines: list[list[_Word]],
    cols: list[_Column],
    group_res: list[re.Pattern[str]],
    group_fit: str = "midpoint",
) -> list[str]:
    """Header path per column from the header lines above the data.

    Group headers span blocks of columns (see ``group_fit``). Other phrases
    attach to the column zone their centre sits in; a phrase much wider than a
    zone that straddles several (two headers packed so tightly they read as
    one phrase) is split into words, each placed on its own.
    """
    zones = _zones(cols)
    placed: list[list[tuple[int, float, str]]] = [[] for _ in cols]

    def zone_of(x0: float, x1: float) -> int | None:
        xc = (x0 + x1) / 2
        for ci, (z0, z1) in enumerate(zones):
            if z0 <= xc < z1:
                return ci
        # Left of the first value column: a header that reaches into the first
        # zone (a right-aligned "Judgeships") belongs to it; otherwise it's the
        # row-label header ("District", "Fiscal Year").
        if xc < zones[0][0] and x1 > zones[0][0]:
            return 0
        return None

    def is_group(p: _Word) -> bool:
        return any(g.search(p.text) for g in group_res)

    # Pass 1: everything that isn't a group header, by zone.
    for li, line in enumerate(header_lines):
        for p in _phrases(line):
            if is_group(p):
                continue
            spans = {
                ci
                for w in line
                if p.x0 <= w.x0 and w.x1 <= p.x1
                for ci in [zone_of(w.x0, w.x1)]
                if ci is not None
            }
            widest = max(z1 - z0 for z0, z1 in zones)
            if len(spans) <= 1 or (p.x1 - p.x0) < 1.5 * widest:
                ci = zone_of(p.x0, p.x1)
                if ci is not None:
                    placed[ci].append((li, p.x0, p.text))
                continue
            for w in line:
                if p.x0 <= w.x0 and w.x1 <= p.x1:
                    ci = zone_of(w.x0, w.x1)
                    if ci is not None:
                        placed[ci].append((li, w.x0, w.text))
    leaves = [normalize_header(" ".join(t for _, _, t in sorted(p))) for p in placed]

    # Pass 2: group headers span blocks of columns.
    for li, line in enumerate(header_lines):
        groups = [p for p in _phrases(line) if is_group(p)]
        if group_fit == "centered":
            blocks = _group_blocks(groups, cols, leaves)
        else:
            blocks = _midpoint_blocks(groups, cols)
        if not blocks:
            # Unplaceable group labels still attach to the zone they sit in.
            for g in groups:
                ci = zone_of(g.x0, g.x1)
                if ci is not None:
                    placed[ci].append((li, g.x0, g.text))
            continue
        for g, (a, b) in zip(groups, blocks, strict=True):
            for ci in range(a, b + 1):
                placed[ci].append((li, g.x0, g.text))
    return [" ".join(t for _, _, t in sorted(p)) for p in placed]


def _pdf_row(line: list[_Word], cols: list[_Column], page: int, lineno: int) -> Row:
    label_words, values = _label_and_values(line)
    label, label_markers = split_markers(" ".join(w.text for w in label_words))
    cells: list[Cell | None] = [None] * len(cols)
    last_ci: int | None = None
    for w in values:
        body, markers = split_markers(w.text)
        if not body:  # a lone footnote marker belongs to the value before it
            if last_ci is not None and (old := cells[last_ci]) is not None:
                cells[last_ci] = Cell(
                    old.text, old.value, old.decimals, old.markers + markers, old.ref
                )
            continue
        ci = next(
            (i for i, c in enumerate(cols) if abs(c.x1 - w.x1) <= 6),
            _nearest(cols, (w.x0 + w.x1) / 2),
        )
        value, dec, _ = parse_number(body)
        cells[ci] = Cell(
            w.text, value, dec, markers, f"p{page}:line{lineno + 1}:col{ci + 1}"
        )
        last_ci = ci
    return Row(label, label_markers, f"p{page}:line{lineno + 1}", cells)


def _pdf_notes(lines: list[list[_Word]]) -> list[str]:
    """Group trailing lines into paragraphs; a new one starts at Note/Source/marker."""
    paras: list[str] = []
    for line in lines:
        t = _text(line)
        if re.match(r"^page \d+ of \d+$", t, re.I):
            continue
        starts = re.match(rf"^(note|source|[{re.escape(MARKERS)}])", t, re.I)
        if starts or not paras:
            paras.append(t)
        else:
            paras[-1] += " " + t
    return paras
