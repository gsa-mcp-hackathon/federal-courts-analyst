"""County → district crosswalk for the web app's district map (Phase 8).

Federal judicial districts are unions of whole counties (28 U.S.C. §§ 81–131),
but no machine-readable crosswalk ships with the data we use. We derive one
from the civil IDB: every record has the filing ``DISTRICT`` and the
``COUNTY`` (FIPS) of residence of the first listed party. For each county we
take the district most of its cases were filed in, **among the districts of
the county's own state** (out-of-state filings are a party living elsewhere,
not a boundary). Single-district states need no vote.

The output records, per county, the share of its in-state cases that went to
the chosen district, so weak assignments are visible; the build script
(``web/scripts/build-districts.mjs``) fills counties with no IDB cases from
their neighbours. ``python -m courts_analyst.pipeline.geo`` writes
``web/src/geo/county-districts.json``.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

from courts_analyst.config import settings
from courts_analyst.core.courts import COURTS, CourtLevel

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "web" / "src" / "geo" / "county-districts.json"

STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP",
    "72": "PR", "78": "VI",
}  # fmt: skip

COUNTS_SQL = """
SELECT r.county, d.court, count(*) AS n
FROM idb.idb_civil_raw r JOIN idb.code_district d ON d.code = r.district
WHERE r.county IS NOT NULL AND length(r.county) = 5 AND d.court IS NOT NULL
GROUP BY ALL
"""


def districts_by_state() -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for code, c in COURTS.items():
        if c.level is CourtLevel.DISTRICT and c.state:
            out[c.state].append(code)
    return dict(out)


def crosswalk(rows: list[tuple[str, str, int]]) -> dict[str, Any]:
    """Assign each county to one district of its own state."""
    by_state = districts_by_state()
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    for county, court, n in rows:
        counts[county][court] = counts[county].get(court, 0) + n
    counties: dict[str, dict[str, Any]] = {}
    for county, per_court in sorted(counts.items()):
        state = STATE_FIPS.get(county[:2])
        if state is None or state not in by_state:
            continue
        own = {c: n for c, n in per_court.items() if c in by_state[state]}
        if not own:
            continue
        court, n = max(own.items(), key=lambda kv: (kv[1], kv[0]))
        total = sum(own.values())
        counties[county] = {
            "district": court,
            "cases": total,
            "share": round(n / total, 3),
        }
    single = {s: ds[0] for s, ds in by_state.items() if len(ds) == 1}
    return {
        "method": "Majority of IDB civil filings by county of residence, "
        "within the county's own state (see courts_analyst/pipeline/geo.py).",
        "single_district_states": single,
        "state_fips": STATE_FIPS,
        "counties": counties,
    }


def main(out: Path = OUT) -> int:
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{settings.resolved_idb_path}' AS idb (READ_ONLY)")
    result = crosswalk(con.execute(COUNTS_SQL).fetchall())
    release = con.execute("SELECT * FROM idb.idb_release LIMIT 1").fetchone()
    result["idb_release"] = str(release[0]) if release else None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    weak = sum(1 for c in result["counties"].values() if c["share"] < 0.6)
    print(
        f"wrote {len(result['counties'])} counties to {out} "
        f"({weak} with a majority under 60%)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
