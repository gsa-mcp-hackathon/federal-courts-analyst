"""Export the core's result models as JSON Schema for the frontend (P8).

``make schemas`` writes one file per result type to ``web/src/api/schemas/``;
``tests/test_schemas_export.py`` fails when a committed file is stale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from courts_analyst.core.cohorts import CohortAnalysis, CohortSpec, CohortSummary
from courts_analyst.core.explain import ChangeExplanation
from courts_analyst.core.glossary import TermLookup
from courts_analyst.core.judgeships import JudgeshipContext
from courts_analyst.core.official import CourtComparison, OfficialFigure
from courts_analyst.core.reconcile import Reconciliation
from courts_analyst.core.results import Result

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web" / "src" / "api" / "schemas"

MODELS: dict[str, type[BaseModel]] = {
    "official-figure": Result[OfficialFigure],
    "court-comparison": Result[CourtComparison],
    "change-explanation": Result[ChangeExplanation],
    "cohort-spec": CohortSpec,
    "cohort-summary": Result[CohortSummary],
    "cohort-analysis": Result[CohortAnalysis],
    "reconciliation": Result[Reconciliation],
    "judgeship-context": Result[JudgeshipContext],
    "term-lookup": Result[TermLookup],
}


def render() -> dict[str, str]:
    return {
        f"{name}.schema.json": json.dumps(model.model_json_schema(), indent=2) + "\n"
        for name, model in MODELS.items()
    }


def main(out: Path = OUT) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for name, text in render().items():
        (out / name).write_text(text)
    print(f"wrote {len(MODELS)} schemas to {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
