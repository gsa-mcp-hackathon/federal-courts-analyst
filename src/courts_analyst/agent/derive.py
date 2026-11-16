"""Events derived from tool results, deterministically (no model involved).

- **Citations.** Every official figure a tool returned becomes a
  :class:`CitationRef`; if its value appears in the answer, the citation
  carries the span. A *revised* figure whose answer doesn't also give the
  other published value gets the server's ``citation`` line appended to
  the answer (issue #27: the model drops the revision from "just one
  number" answers even when told to quote it).
- **Charts** for comparisons, change explanations and figures with more
  than one edition, in the spec the MCP App (P9) also renders.
- **Docket cards** from ``sample_dockets`` and the CourtListener tools,
  every string HTML-escaped.
- **Warnings** from the result envelopes.
"""

from __future__ import annotations

import re
from typing import Any

from courts_analyst.agent.events import (
    ChartPoint,
    ChartSeries,
    ChartSpec,
    CitationRef,
    DocketCard,
)
from courts_analyst.agent.mcp_clients import clean_text
from courts_analyst.core.numbers import fmt

MAX_BARS = 15
TOOL_WARNING_CODES = frozenset(
    {
        "small_cell",
        "suppressed",
        "data_break",
        "period_mismatch",
        "inferred_not_official",
        "mixed_editions",
        "partial_year",
        "inexact_match",
        "truncated",
    }
)
"""Envelope warnings forwarded as ``warning`` events. ``revised_figure`` is
left to the citation, which already says it."""


def _data(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result or result.get("status") != "ok":
        return None
    data = result.get("data")
    return data if isinstance(data, dict) else None


# ── citations ────────────────────────────────────────────────────────────────


def figure_refs(tool: str, result: dict[str, Any] | None) -> list[CitationRef]:
    data = _data(result)
    if data is None:
        return []
    if tool == "get_official_figure":
        first = data.get("first_published") or {}
        revised = data.get("revision_status") == "revised"
        return [
            CitationRef(
                citation=data["citation"],
                value=data["value"],
                measure=data["measure"],
                court=data["court"],
                fiscal_year=data["fiscal_year"],
                edition=data["edition"],
                table_code=data["table_code"],
                url=(data.get("latest") or {}).get("url"),
                revised=revised,
                first_published_value=first.get("value") if revised else None,
                first_published_edition=first.get("edition") if revised else None,
            )
        ]
    if tool == "explain_change":
        refs = []
        for key, fy in (("official_from", "period_from"), ("official_to", "period_to")):
            f = data.get(key)
            if not f:
                continue
            refs.append(
                CitationRef(
                    citation=(
                        f"{fmt(f['value'])} ({f['edition']}, Table {f['table_code']})"
                    ),
                    value=f["value"],
                    measure=data["measure"],
                    court=data["court"],
                    fiscal_year=data[fy],
                    edition=f["edition"],
                    table_code=f["table_code"],
                    url=f.get("url"),
                    revised=False,
                )
            )
        return refs
    return []


def _number_pattern(value: float) -> re.Pattern[str]:
    forms = {fmt(value), fmt(value).replace(",", "")}
    alts = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    return re.compile(r"(?<![\d.,])(?:" + alts + r")(?![\d]|[.,]\d)")


def find_span(text: str, value: float) -> tuple[int, int] | None:
    m = _number_pattern(value).search(text)
    return (m.start(), m.end()) if m else None


def revision_footer(text: str, refs: list[CitationRef]) -> str:
    """Citation lines for revised figures the answer states without the
    other published value (issue #27). Empty when nothing is missing."""
    lines: list[str] = []
    for ref in refs:
        if not ref.revised or ref.first_published_value is None:
            continue
        if find_span(text, ref.value) is None:
            continue
        other = (
            ref.first_published_value
            if ref.first_published_value != ref.value
            else None
        )
        if other is not None and find_span(text, other) is not None:
            continue
        line = f"Source: {ref.citation}."
        if line not in lines and ref.citation not in text:
            lines.append(line)
    return ("\n\n" + "\n".join(lines)) if lines else ""


# ── charts ───────────────────────────────────────────────────────────────────


def chart_for(
    tool: str, result: dict[str, Any] | None, call_id: str
) -> ChartSpec | None:
    data = _data(result)
    if data is None:
        return None
    if tool == "compare_courts" and data.get("rows"):
        rows = data["rows"][:MAX_BARS]
        return ChartSpec(
            kind="bar",
            title=f"{data['measure_label']}, FY{data['fiscal_year']}",
            x_label="Court",
            y_label=data["measure_label"],
            unit=data["unit"],
            series=[
                ChartSeries(
                    name=data["edition"],
                    points=[
                        ChartPoint(
                            x=r.get("citation") or r["court"],
                            y=r["value"],
                            label=fmt(r["value"]),
                        )
                        for r in rows
                    ],
                )
            ],
            source=f"{data['edition']}, Table {data['table_code']}",
            call_id=call_id,
        )
    if tool == "get_official_figure" and len(data.get("editions") or []) > 1:
        eds = data["editions"]
        return ChartSpec(
            kind="editions",
            title=f"{data['measure_label']}, {data['court_name']}, "
            f"FY{data['fiscal_year']}: every edition",
            x_label="Edition",
            y_label=data["measure_label"],
            unit=data["unit"],
            series=[
                ChartSeries(
                    name="Published value",
                    points=[
                        ChartPoint(x=e["edition"], y=e["value"], label=fmt(e["value"]))
                        for e in eds
                    ],
                )
            ],
            source=", ".join(f"{e['edition']} Table {e['table_code']}" for e in eds),
            call_id=call_id,
        )
    if tool == "explain_change":
        rows = data.get("by_case_type") or data.get("by_district") or []
        if not rows:
            return None
        points = [
            ChartPoint(x=r["label"], y=r["change"], label=f"{r['change']:+,g}")
            for r in rows[:MAX_BARS]
        ]
        return ChartSpec(
            kind="waterfall",
            title=data["headline"],
            x_label="Contributor",
            y_label=f"Change in {data['measure_label']}",
            unit=data["unit"],
            series=[ChartSeries(name=data["decomposition_series"], points=points)],
            source=data["decomposition_series"],
            call_id=call_id,
        )
    return None


# ── dockets ──────────────────────────────────────────────────────────────────


def docket_cards(tool: str, result: dict[str, Any] | None) -> list[DocketCard]:
    if tool == "sample_dockets":
        data = _data(result)
        if data is None:
            return []
        return [
            DocketCard(
                origin="idb_sample",
                court=clean_text(d.get("court_name")) or d["court"],
                docket_number=clean_text(d.get("docket_number")),
                filing_date=d.get("filing_date"),
                nature_of_suit=clean_text(d.get("nature_of_suit")),
                url=d.get("courtlistener_search"),
                note=clean_text(d.get("match_note")) or "match may be inexact",
            )
            for d in data.get("dockets", [])
        ]
    if tool.startswith("courtlistener_") and result and result.get("untrusted"):
        origin = result.get("origin", "courtlistener_fixture")
        return [
            DocketCard(
                origin=origin,
                # Already cleaned by the tool host; cleaning again is harmless
                # only for text without entities, so pass through as is.
                court=d.get("court_id") or "?",
                docket_number=d.get("docket_number"),
                filing_date=d.get("date_filed"),
                nature_of_suit=d.get("nature_of_suit"),
                cause=d.get("cause"),
                url=d.get("url"),
                note=result.get("note", ""),
            )
            for d in result.get("dockets", [])
        ]
    return []


def warnings_from(result: dict[str, Any] | None) -> list[dict[str, str]]:
    if not result:
        return []
    out = []
    if result.get("status") == "declined" and result.get("declined"):
        d = result["declined"]
        out.append({"code": d["reason"], "message": d["message"], "severity": "block"})
    for w in result.get("warnings") or []:
        if w.get("code") in TOOL_WARNING_CODES:
            out.append(
                {
                    "code": w["code"],
                    "message": w["message"],
                    "severity": w.get("severity", "caution"),
                }
            )
    return out
