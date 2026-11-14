"""``courts-eval``: validate the bank, run a suite, show a past summary.

Examples::

    courts-eval validate
    courts-eval run --answerer gold
    courts-eval run --suite e2e --split dev --answerer null
    courts-eval stats
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from courts_analyst.evaluation.answerers import ANSWERERS, PAID
from courts_analyst.evaluation.bank import (
    DEFAULT_BANK,
    BankError,
    load_bank,
    select,
    within_tools,
)
from courts_analyst.evaluation.runner import DEFAULT_RESULTS, run
from courts_analyst.evaluation.schema import HELD_OUT_PERCENT, SUITES
from courts_analyst.evaluation.scoring.summary import SubsetInfo, summary_markdown


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="courts-eval", description=__doc__)
    p.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="Load and validate every question file")
    sub.add_parser("stats", help="Counts by suite, split and tag")
    r = sub.add_parser("run", help="Answer and score a slice of the bank")
    r.add_argument("--answerer", required=True, help=f"one of {sorted(ANSWERERS)}")
    r.add_argument("--suite", choices=SUITES)
    r.add_argument("--split", choices=["dev", "test", "test2"])
    r.add_argument("--tag", action="append", dest="tags")
    r.add_argument("--id", action="append", dest="ids")
    r.add_argument("--limit", type=int)
    r.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    r.add_argument("--run-id")
    r.add_argument("--quiet", action="store_true")
    r.add_argument("--workers", type=int, default=1, help="answer N items at once")
    r.add_argument(
        "--repeats",
        type=int,
        default=1,
        metavar="K",
        help="answer each item K times and report pass@K / pass^K",
    )
    r.add_argument(
        "--budget-usd",
        type=float,
        default=1.00,
        help="paid answerers: stop sending requests once the run has spent this",
    )
    r.add_argument(
        "--allow-full-bank",
        action="store_true",
        help="paid answerers: allow runs beyond the smoke set",
    )
    r.add_argument(
        "--agent-tools",
        metavar="VALUE",
        help=(
            "only score items answerable by the agent: 'wxo' (WXO_AGENT_TOOLS preset) "
            "or a comma-separated list of tool names"
        ),
    )
    r.add_argument(
        "--expect-accuracy",
        type=float,
        help="exit 1 unless accuracy equals this (harness self-checks: 1 or 0)",
    )
    rs = sub.add_parser("rescore", help="Score a past run's records again")
    rs.add_argument("records", type=Path, help="<run_id>.jsonl")
    rs.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    rs.add_argument("--run-id")
    s = sub.add_parser("show", help="Print a past run's summary as Markdown")
    s.add_argument("summary", type=Path, help="<run_id>.summary.json")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "show":
        from courts_analyst.evaluation.scoring.summary import RunSummary

        data = json.loads(args.summary.read_text())
        summary = RunSummary.model_validate(data["summary"])
        print(summary_markdown(summary, f"{data['answerer']} · {data['label']}"))
        return 0
    try:
        items = load_bank(args.bank)
    except BankError as exc:
        print(f"invalid question bank: {exc}", file=sys.stderr)
        return 1
    if args.cmd == "rescore":
        from courts_analyst.evaluation.runner import rescore

        result = rescore(args.records, items, args.results_dir, args.run_id)
        print(result.paths["markdown"].read_text())
        return 0
    if args.cmd == "validate":
        held = sum(i.resolved_split == "test" for i in items)
        t2 = sum(i.resolved_split == "test2" for i in items)
        base = len(items) - t2
        print(
            f"{len(items)} questions valid; {held} held out "
            f"({100 * held / base:.0f}% of dev+test, target {HELD_OUT_PERCENT}%); "
            f"{t2} test2"
        )
        return 0
    if args.cmd == "stats":
        by = Counter((i.suite, i.resolved_split) for i in items)
        print(
            "| Suite | dev | test | test2 | total |\n"
            "| --- | ---: | ---: | ---: | ---: |"
        )
        for suite in SUITES:
            d, t, t2 = (
                by[(suite, "dev")],
                by[(suite, "test")],
                by[(suite, "test2")],
            )
            print(f"| {suite} | {d} | {t} | {t2} | {d + t + t2} |")
        tags = Counter(t for i in items for t in i.tags)
        print("\nTags: " + ", ".join(f"{t} ({n})" for t, n in tags.most_common()))
        return 0

    if args.answerer not in ANSWERERS:
        print(f"unknown answerer {args.answerer!r}; pick from {sorted(ANSWERERS)}")
        return 2
    if (
        args.answerer in PAID
        and not args.allow_full_bank
        and (args.tags != ["smoke"] and not args.ids)
    ):
        print(
            f"{args.answerer} costs money per question: run it with --tag smoke "
            "(20 questions), a few --id values, or pass --allow-full-bank.",
            file=sys.stderr,
        )
        return 2
    chosen = select(items, args.suite, args.split, args.tags, args.ids)

    # --agent-tools subset filter (applied after select, before --limit)
    subset_info: SubsetInfo | None = None
    if args.agent_tools:
        raw = args.agent_tools
        if raw == "wxo":
            from courts_analyst.evaluation.wxo_agent import WXO_AGENT_TOOLS

            tools: frozenset[str] = WXO_AGENT_TOOLS
            preset_name: str = "wxo"
        else:
            tools = frozenset(t.strip() for t in raw.split(",") if t.strip())
            preset_name = raw
        n_slice = len(chosen)
        chosen = within_tools(chosen, tools)
        n_subset = len(chosen)
        print(
            f"subset: {n_subset} of {n_slice} items have all expected tools"
            " on the agent"
        )
        subset_info = SubsetInfo(
            tools=sorted(tools),
            n_slice=n_slice,
            n_subset=n_subset,
            preset=preset_name,
        )

    if args.limit:
        chosen = chosen[: args.limit]
    if not chosen:
        print("no questions match those filters", file=sys.stderr)
        return 1
    label = "-".join(x for x in [args.suite or "all", args.split or "both"] if x)
    if args.agent_tools:
        label = f"{label}-subset"

    def progress(item, score):  # type: ignore[no-untyped-def]
        if not args.quiet:
            mark = "✓" if score.correct else "✗"
            extra = "" if score.correct else f"  [{score.error_category}]"
            print(f"{mark} {item.id}{extra}", flush=True)

    answerer = ANSWERERS[args.answerer]()
    if args.answerer in PAID:
        from courts_analyst.evaluation.budget import Budget

        answerer.budget = Budget(args.budget_usd)  # type: ignore[attr-defined]
        print(f"budget: ${args.budget_usd:.2f} for {len(chosen)} questions")
    result = run(
        answerer,
        chosen,
        label=label,
        results_dir=args.results_dir,
        run_id=args.run_id,
        progress=progress,
        workers=args.workers,
        repeats=args.repeats,
        subset_info=subset_info,
    )
    print()
    print(result.paths["markdown"].read_text())
    print(f"results: {result.paths['jsonl']}")
    if args.expect_accuracy is not None and result.summary.accuracy != (
        args.expect_accuracy
    ):
        print(
            f"expected accuracy {args.expect_accuracy}, got {result.summary.accuracy}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
