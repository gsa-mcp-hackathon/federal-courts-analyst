"""Request desk housekeeping (ADR 0013).

``python -m courts_analyst.desk_cli check``  compare saved citations with the
    catalog; flag stale library answers and notify watchers (also run at
    HTTP startup).
``python -m courts_analyst.desk_cli reset``  empty the sandbox desk store.
``python -m courts_analyst.desk_cli seed``   the demo's opening state: a
    journalist has already asked the statistics office about FY2020, so the
    next asker sees "1 other request is waiting".

All three use the store at ``DESK_STORE_PATH`` (in memory if unset, which
makes them no-ops worth nothing outside tests).
"""

from __future__ import annotations

import argparse
import json
import sys

from courts_analyst.config import settings
from courts_analyst.core.desk.models import Actor, CitationIn, InquiryTarget
from courts_analyst.core.desk.service import check_staleness, submit_option
from courts_analyst.tools._common import get_db, get_desk

W = "weighted_civil_filings_per_judgeship"
SEED_ACTOR = Actor(account_id="sam", name="Sam Ortega", role="journalist")
SEED_QUESTION = (
    "Why was FY2020 national weighted civil filings per judgeship revised from "
    "554 to 322?"
)
SEED_ANSWER = (
    "FY2020 national weighted civil filings per judgeship are 322 in Judicial "
    "Facts and Figures (JFF-2024); the figure was first published as 554 in "
    "Judicial Business (JB-2020). The tables' notes don't explain the revision."
)
SEED_CITATIONS = [
    CitationIn(measure=W, fiscal_year=2020, edition="JFF-2024", value=322),
    CitationIn(measure=W, fiscal_year=2020, edition="JB-2020", value=554),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="desk", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["check", "reset", "seed"])
    args = parser.parse_args(argv)
    if settings.desk_store_path is None:
        print("DESK_STORE_PATH is not set: the desk lives in memory.", file=sys.stderr)
        return 2
    store = get_desk()
    if args.command == "reset":
        store.reset()
        print(f"Emptied {settings.desk_store_path}.")
        return 0
    if args.command == "check":
        report = check_staleness(get_db(), store)
        print(json.dumps(report.data.model_dump() if report.data else {}, indent=2))
        return 0
    result = submit_option(
        get_db(),
        store,
        SEED_ACTOR,
        "ask_office",
        SEED_QUESTION,
        SEED_ANSWER,
        SEED_CITATIONS,
        InquiryTarget(measure=W, fiscal_year=2020),
        idempotency_key="demo-seed",
    )
    print(result.data.message if result.data else result.status)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
