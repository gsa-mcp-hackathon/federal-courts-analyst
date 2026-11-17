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
        "--provenance",
        type=Path,
        metavar="PATH",
        help="JSON object file; written into the summary under meta['provenance']",
    )
    r.add_argument(
        "--agent-tools",
        metavar="VALUE",
        help=(
            "only score items answerable by the agent: 'wxo' (WXO_AGENT_TOOLS preset), "
            "'wxo-idb' (plus the case-level tools) or a comma-separated list of "
            "tool names"
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
    jd = sub.add_parser(
        "judge",
        help=(
            "Grade saved replies with an LLM judge (claude -p) and compare it "
            "with the deterministic scorer; never changes a score"
        ),
    )
    jd.add_argument("records", nargs="+", type=Path, help="<run_id>.jsonl files")
    jd.add_argument("--out", type=Path, required=True, help="output stem (.jsonl, .md)")
    jd.add_argument("--model", default="sonnet", help="judge model (claude --model)")
    jd.add_argument("--variant", action="append", choices=["generic", "informed"])
    jd.add_argument("--repeats", type=int, default=1, help="grade each reply N times")
    jd.add_argument("--workers", type=int, default=8)
    jd.add_argument("--no-mutants", action="store_true")
    jd.add_argument("--limit", type=int, help="first N replies per file (trial runs)")
    df = sub.add_parser(
        "desk-flows",
        help=(
            "Scripted request-desk conversations with Claude on the full server: "
            "step-by-step write tools vs keep_answer"
        ),
    )
    df.add_argument("--out", type=Path, required=True, help="output stem (.jsonl, .md)")
    df.add_argument("--model", default="sonnet")
    df.add_argument("--repeats", type=int, default=3)
    df.add_argument("--workers", type=int, default=4)
    df.add_argument("--scenario", action="append", help="scenario id (default: all)")
    df.add_argument("--arm", action="append", choices=["step", "keep"])
    s = sub.add_parser("show", help="Print a past run's summary as Markdown")
    s.add_argument("summary", type=Path, help="<run_id>.summary.json")
    pc = sub.add_parser(
        "preview-check",
        help=(
            "Check the preview rule: every confirmed keep_answer must be preceded "
            "by 'Shall I go ahead?' and a user yes. "
            "PATH may be a .jsonl run-records file or a Layer-1 output directory."
        ),
    )
    pc.add_argument(
        "paths",
        nargs="+",
        type=Path,
        metavar="PATH",
        help=".jsonl run-records file or Layer-1 output directory",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "preview-check":
        from courts_analyst.evaluation.preview_check import check_path

        total_confirms = 0
        total_violations = 0
        any_error = False
        for path in args.paths:
            pc_result = check_path(path)
            total_confirms += pc_result.confirm_calls
            total_violations += len(pc_result.violations)
            n_v = len(pc_result.violations)
            status = "OK" if not pc_result.violations else f"{n_v} violation(s)"
            print(
                f"{path}: {pc_result.confirm_calls} confirmed keep_answer"
                f" call(s), {status}"
            )
            for v in pc_result.violations:
                print(f"  VIOLATION: {v}")
            if pc_result.violations:
                any_error = True
        print(
            f"\nTotal: {total_confirms} confirmed keep_answer call(s), "
            f"{total_violations} violation(s)"
        )
        return 1 if any_error else 0
    if args.cmd == "desk-flows":
        from courts_analyst.evaluation import desk_flows

        flows = [
            sc
            for sc in desk_flows.SCENARIOS
            if not args.scenario or sc.id in args.scenario
        ]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        flow_results = desk_flows.run_all(
            args.out,
            flows,
            args.arm or desk_flows.ARMS,
            args.repeats,
            args.workers,
            args.model,
            progress=lambda line: print(f"  {line}", file=sys.stderr, flush=True),
        )
        md = desk_flows.report_markdown(flow_results, args.model)
        args.out.with_suffix(".md").write_text(md)
        print(md)
        return 0
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
    if args.cmd == "judge":
        from courts_analyst.evaluation import llm_judge

        by_id = {i.id: i for i in items}
        cases = llm_judge.load_cases(args.records, by_id, not args.no_mutants)
        if args.limit:
            keep = {(c.source, c.line) for c in cases if c.line < args.limit}
            cases = [c for c in cases if (c.source, c.line) in keep]
        jsonl = args.out.with_suffix(".jsonl")
        jsonl.parent.mkdir(parents=True, exist_ok=True)

        def tick(done: int, total: int) -> None:
            if done % 25 == 0 or done == total:
                print(f"  judged {done}/{total}", file=sys.stderr, flush=True)

        graded = llm_judge.run_judge(
            cases,
            by_id,
            llm_judge.ClaudeJudge(args.model),
            variants=args.variant or llm_judge.VARIANTS,
            repeats=args.repeats,
            workers=args.workers,
            out=jsonl,
            progress=tick,
        )
        md = llm_judge.report_markdown(
            graded, args.model, [r.name for r in args.records]
        )
        args.out.with_suffix(".md").write_text(md)
        print(md)
        missing = sum(g.verdict.label is None for g in graded)
        if missing:
            print(f"{missing} verdict(s) failed; run again to retry", file=sys.stderr)
        return 1 if missing else 0
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
        from courts_analyst.evaluation.wxo_agent import WXO_PRESETS

        if raw in WXO_PRESETS:
            tools: frozenset[str] = WXO_PRESETS[raw]
            preset_name: str = raw
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
    provenance: dict[str, object] | None = None
    if getattr(args, "provenance", None) is not None:
        provenance = json.loads(args.provenance.read_text())

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
        provenance=provenance,
        split=args.split,
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
