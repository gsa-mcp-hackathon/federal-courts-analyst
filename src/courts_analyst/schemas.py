"""Export the core's result models as JSON Schema for the frontend (P8).

``make schemas`` writes one file per result type to ``web/src/api/schemas/``;
``tests/test_schemas_export.py`` fails when a committed file is stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from courts_analyst.agent.events import EVENT_ADAPTER
from courts_analyst.core.cohorts import CohortAnalysis, CohortSpec, CohortSummary
from courts_analyst.core.dockets import DocketSample
from courts_analyst.core.explain import ChangeExplanation
from courts_analyst.core.glossary import TermLookup
from courts_analyst.core.judgeships import JudgeshipContext
from courts_analyst.core.official import (
    CourtComparison,
    EditionVintages,
    OfficialFigure,
    OfficialSeries,
)
from courts_analyst.core.reconcile import Reconciliation
from courts_analyst.core.results import Result

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "src" / "api" / "schemas"

MODELS: dict[str, type[BaseModel]] = {
    "official-figure": Result[OfficialFigure],
    "official-series": Result[OfficialSeries],
    "edition-vintages": Result[EditionVintages],
    "court-comparison": Result[CourtComparison],
    "change-explanation": Result[ChangeExplanation],
    "cohort-spec": CohortSpec,
    "cohort-summary": Result[CohortSummary],
    "cohort-analysis": Result[CohortAnalysis],
    "reconciliation": Result[Reconciliation],
    "judgeship-context": Result[JudgeshipContext],
    "term-lookup": Result[TermLookup],
    "docket-sample": Result[DocketSample],
}
ADAPTERS: dict[str, TypeAdapter] = {  # type: ignore[type-arg]
    # The agent's SSE events (Phase 7), one discriminated union.
    "agent-event": EVENT_ADAPTER,
}


def render() -> dict[str, str]:
    schemas = {name: model.model_json_schema() for name, model in MODELS.items()}
    schemas |= {name: a.json_schema() for name, a in ADAPTERS.items()}
    return {
        f"{name}.schema.json": json.dumps(schema, indent=2) + "\n"
        for name, schema in schemas.items()
    }


def main(out: Path = OUT) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for name, text in render().items():
        (out / name).write_text(text)
    print(f"wrote {len(MODELS) + len(ADAPTERS)} schemas to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
