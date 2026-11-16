"""``courts-eval judge``: grade saved replies with an LLM judge and compare it
with the deterministic scorer.

The judge never sets a reported score. It answers one question: would an
LLM-as-judge, the default in most MCP evaluation kits (including the GSA
template's Phoenix ``match_expected_response``), reach the same verdicts as
our exact checks? It reads the saved replies of a past run, so it costs no
agent runs.

Two judge prompts:

- ``generic``: the template's correctness judge. It compares the reply with a
  reference answer and tolerates formatting differences.
- ``informed``: the same, plus this domain's rules (the edition label is part
  of the figure; revised figures need both editions; decline and clarify
  count as answers).

**Mutants** are known-wrong variants of replies the scorer passed, made by
editing the text only:

- ``swap``: the current and first-published values trade places, so each is
  attributed to the other's edition ("554 (JFF-2025)");
- ``no_edition``: every edition mention is removed;
- ``nudge``: an expected value is moved by 2 in its last printed digit.

Each mutant is scored by the deterministic scorer too, so the catch rates of
both graders are measured, not assumed.

The judge runs through headless Claude Code (``claude -p``) with no tools and
no MCP servers, so it needs a logged-in ``claude`` CLI, not an API key.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil

# Runs the claude CLI with an argument list.
import subprocess  # nosec B404
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from courts_analyst.core.courts import COURTS
from courts_analyst.core.figures_text import find_editions
from courts_analyst.evaluation.records import AnswerRecord
from courts_analyst.evaluation.schema import ExpectedFigure, QuestionItem
from courts_analyst.evaluation.scoring.numeric import printed_decimals
from courts_analyst.evaluation.scoring.score import score_item

Variant = Literal["generic", "informed"]
VARIANTS: tuple[Variant, ...] = ("generic", "informed")
MUTANTS = ("swap", "no_edition", "nudge")
TIMEOUT_S = 180

SYSTEM = "You grade answers. Reply only in the requested JSON format."

_GENERIC = """\
You are comparing an AI assistant's response with a reference answer to a \
question about federal district court statistics.

[Question]
{question}

[Reference answer]
{reference}

[Response]
{response}

Decide whether the response is correct with respect to the reference answer. \
Be tolerant of reasonable formatting differences (number formatting, units, \
surrounding prose, extra context): a correct answer must not be marked wrong \
for cosmetic reasons. Label it "correct" or "incorrect", with a one-sentence \
reason."""

_INFORMED_RULES = """\
Grading rules for this domain:
- The judiciary revises figures between editions of its tables. A figure \
counts only with the edition that prints it: the right number attributed to \
a wrong edition, or with no edition at all, is incorrect.
- When the reference lists a current and a first-published figure, the \
response must report both, each with its own edition.
- When the reference says the assistant should decline or ask a clarifying \
question, a response that answers instead is incorrect; a response that \
declines or asks when it should answer is also incorrect.
- Extra correct context is fine. Any stated number that contradicts the \
reference is incorrect."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["correct", "incorrect"]},
        "reason": {"type": "string"},
    },
    "required": ["label", "reason"],
}


# --------------------------------------------------------------------------
# The reference answer the judge sees
# --------------------------------------------------------------------------


def _fmt_value(value: float) -> str:
    dec = printed_decimals(value)
    return f"{value:,.{dec}f}"


def _figure_line(f: ExpectedFigure) -> str:
    s = _fmt_value(f.value)
    eds = f.editions
    if eds:
        s += f" ({eds[0]}"
        if len(eds) > 1:
            s += f"; the same value is printed in {', '.join(eds[1:])}"
        s += ")"
    else:
        s += " (any edition)"
    if f.tolerance_pct:
        s += f", within ±{f.tolerance_pct:g}%"
    elif f.tolerance:
        s += f", within ±{f.tolerance:g}"
    if f.label:
        s += f": {f.label}"
    return s


def reference_answer(item: QuestionItem) -> str:
    """The item's expected answer as text a judge can compare against."""
    exp = item.expected
    lines: list[str] = []
    if exp.behavior == "answer":
        lines.append("Expected behaviour: answer the question.")
    elif exp.behavior == "decline":
        lines.append(
            "Expected behaviour: decline, because the request is out of scope, "
            "ideally offering an in-scope alternative."
        )
    else:
        lines.append(
            "Expected behaviour: ask the user a clarifying question instead of "
            "guessing what they mean."
        )
    if exp.figures:
        many = len(exp.figures) > 1
        if exp.figures_mode == "all" or not many:
            head = "It must report these figures:" if many else "It must report:"
        else:
            head = "It must report at least one of these figures:"
        lines.append(head)
        lines.extend(f"- {_figure_line(f)}" for f in exp.figures)
    if exp.must_mention_revision:
        lines.append("It must say that the figure was revised between editions.")
    if exp.ranking:
        names = [COURTS[c].citation or COURTS[c].name for c in exp.ranking]
        lines.append("It must rank, in this order: " + "; ".join(names) + ".")
    for c in item.claims:
        if c.kind == "mentions":
            if c.all:
                lines.append("It must mention: " + "; ".join(c.all) + ".")
            if c.any:
                lines.append(
                    "It must mention at least one of: " + "; ".join(c.any) + "."
                )
        elif c.kind == "not_mentions":
            words = [*(c.all or []), *(c.any or [])]
            lines.append("It must not mention: " + "; ".join(words) + ".")
        elif c.description:
            lines.append(f"It must satisfy: {c.description}")
    return "\n".join(lines)


def judge_prompt(item: QuestionItem, response: str, variant: Variant) -> str:
    text = _GENERIC.format(
        question=item.question,
        reference=reference_answer(item),
        response=response.strip() or "(no response)",
    )
    if variant == "informed":
        text += "\n\n" + _INFORMED_RULES
    return text


# --------------------------------------------------------------------------
# Mutants: known-wrong edits of replies the scorer passed
# --------------------------------------------------------------------------

_SEP = "[,\u202f\u2009\u00a0 ]"


def _value_pattern(value: float) -> re.Pattern[str] | None:
    """Matches ``value`` as printed, with any thousands separator."""
    if not float(value).is_integer():
        dec = printed_decimals(value)
        body = re.escape(f"{value:.{dec}f}")
    else:
        digits = f"{int(value):,}"
        body = f"{_SEP}?".join(re.escape(g) for g in digits.split(","))
    return re.compile(rf"(?<![\d.,]){body}(?![\d]|[.,]\d)")


def mutate_swap(item: QuestionItem, text: str) -> str | None:
    """Trade the places of two expected values printed in different editions."""
    figs = item.expected.figures
    values = {f.value for f in figs}
    if len(figs) != 2 or len(values) != 2:
        return None
    a, b = figs
    if set(a.editions) & set(b.editions):
        return None
    pa, pb = _value_pattern(a.value), _value_pattern(b.value)
    if not pa or not pb or not pa.search(text) or not pb.search(text):
        return None
    marker = "\x00"
    out = pa.sub(marker, text)
    out = pb.sub(_fmt_value(a.value), out)
    return out.replace(marker, _fmt_value(b.value))


def mutate_no_edition(item: QuestionItem, text: str) -> str | None:
    """Remove every edition mention (only where every figure needs one)."""
    figs = item.expected.figures
    if not figs or not all(f.editions for f in figs):
        return None
    mentions = find_editions(text)
    if not mentions:
        return None
    out = text
    for m in reversed(mentions):
        out = out[: m.start] + out[m.end :]
    out = re.sub(r"\(\s*[,;]?\s*\)", "", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out


def mutate_nudge(item: QuestionItem, text: str) -> str | None:
    """Move the first expected value that appears by 2 in its last digit."""
    for f in item.expected.figures:
        if f.tolerance or f.tolerance_pct:
            continue
        pat = _value_pattern(f.value)
        if pat and pat.search(text):
            step = 2 * 10.0 ** -printed_decimals(f.value)
            return pat.sub(_fmt_value(f.value + step), text)
    return None


MUTATORS: dict[str, Callable[[QuestionItem, str], str | None]] = {
    "swap": mutate_swap,
    "no_edition": mutate_no_edition,
    "nudge": mutate_nudge,
}


# --------------------------------------------------------------------------
# The judge
# --------------------------------------------------------------------------


@dataclass
class Verdict:
    label: str | None
    reason: str = ""
    cost_usd: float | None = None
    error: str | None = None


Judge = Callable[[str], Verdict]


class ClaudeJudge:
    """An LLM judge through ``claude -p``: no tools, no MCP servers."""

    def __init__(self, model: str = "sonnet") -> None:
        self.model = model
        self.exe = shutil.which("claude")

    def __call__(self, prompt: str) -> Verdict:
        if self.exe is None:
            return Verdict(None, error="the claude CLI isn't installed")
        with tempfile.TemporaryDirectory(prefix="courts-judge-") as tmp:
            cfg = Path(tmp) / "mcp.json"
            cfg.write_text('{"mcpServers": {}}')
            cmd = [
                self.exe, "-p", prompt,
                "--system-prompt", SYSTEM,
                "--tools", "",
                "--mcp-config", str(cfg), "--strict-mcp-config",
                "--no-session-persistence",
                "--model", self.model,
                "--output-format", "json",
                "--json-schema", json.dumps(JUDGE_SCHEMA),
            ]  # fmt: skip
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            try:
                # Fixed argv, no shell.
                proc = subprocess.run(  # nosec B603
                    cmd,
                    cwd=tmp,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_S,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return Verdict(None, error=f"timed out after {TIMEOUT_S}s")
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return Verdict(None, error=(proc.stderr or proc.stdout)[-300:])
        so = out.get("structured_output") or {}
        label = so.get("label")
        if label not in {"correct", "incorrect"}:
            return Verdict(None, error=str(out.get("result"))[-300:])
        return Verdict(label, so.get("reason", ""), out.get("total_cost_usd"))


# --------------------------------------------------------------------------
# Running and summarising
# --------------------------------------------------------------------------


@dataclass
class Case:
    """One reply to grade: an original, or a mutant of one."""

    key: str
    source: str
    line: int
    question_id: str
    suite: str
    split: str
    kind: str  # "original" or a mutant name
    text: str
    scorer_correct: bool
    infra_error: bool = False


@dataclass
class Graded:
    case: Case
    variant: str
    repeat: int
    verdict: Verdict


def load_cases(
    sources: Iterable[Path], items: dict[str, QuestionItem], mutants: bool
) -> list[Case]:
    cases: list[Case] = []
    for src in sources:
        for n, line in enumerate(src.read_text().splitlines()):
            obj = json.loads(line)
            rec = AnswerRecord.model_validate(obj["record"])
            item = items.get(rec.question_id)
            if item is None:
                continue
            score = obj["score"]
            base = Case(
                key=f"{src.name}:{n}:original",
                source=src.name,
                line=n,
                question_id=rec.question_id,
                suite=score["suite"],
                split=score["split"],
                kind="original",
                text=rec.final_text,
                scorer_correct=bool(score["correct"]),
                infra_error=bool(score.get("infra_error")),
            )
            cases.append(base)
            if not mutants or not base.scorer_correct or rec.cited_figures:
                continue
            for name, mutate in MUTATORS.items():
                text = mutate(item, rec.final_text)
                if text is None or text == rec.final_text:
                    continue
                mutated = rec.model_copy(update={"final_text": text})
                cases.append(
                    Case(
                        key=f"{src.name}:{n}:{name}",
                        source=src.name,
                        line=n,
                        question_id=rec.question_id,
                        suite=base.suite,
                        split=base.split,
                        kind=name,
                        text=text,
                        scorer_correct=score_item(item, mutated).correct,
                    )
                )
    return cases


def run_judge(
    cases: list[Case],
    items: dict[str, QuestionItem],
    judge: Judge,
    variants: Iterable[str] = VARIANTS,
    repeats: int = 1,
    workers: int = 8,
    out: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[Graded]:
    """Grade every case with every variant. With ``out``, verdicts are
    appended as JSONL and ones already there are reused, so a run resumes."""
    done: dict[tuple[str, str, int], Verdict] = {}
    if out and out.exists():
        for line in out.read_text().splitlines():
            o = json.loads(line)
            if o["verdict"]["label"] is not None:
                done[(o["key"], o["variant"], o["repeat"])] = Verdict(**o["verdict"])
    by_key = {c.key: c for c in cases}
    jobs = [
        (c.key, v, r)
        for c in cases
        for v in variants
        for r in range(repeats)
        if (c.key, v, r) not in done
    ]
    lock = Lock()
    count = 0

    def work(job: tuple[str, str, int]) -> None:
        nonlocal count
        key, variant, rep = job
        case = by_key[key]
        verdict = judge(judge_prompt(items[case.question_id], case.text, variant))  # type: ignore[arg-type]
        with lock:
            done[job] = verdict
            count += 1
            if out and verdict.label is not None:
                with out.open("a") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "key": key,
                                "variant": variant,
                                "repeat": rep,
                                "verdict": asdict(verdict),
                            }
                        )
                        + "\n"
                    )
            if progress:
                progress(count, len(jobs))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(work, jobs))
    return [
        Graded(by_key[k], v, r, verdict)
        for (k, v, r), verdict in done.items()
        if k in by_key
    ]


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa = sum(a for a, _ in pairs) / n
    pb = sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if math.isclose(pe, 1.0) else (po - pe) / (1 - pe)


@dataclass
class Agreement:
    n: int = 0
    both_pass: int = 0
    both_fail: int = 0
    scorer_only: int = 0
    judge_only: int = 0
    kappa: float | None = None
    pairs: list[tuple[bool, bool]] = field(default_factory=list, repr=False)

    def add(self, scorer: bool, judge: bool) -> None:
        self.n += 1
        self.pairs.append((scorer, judge))
        if scorer and judge:
            self.both_pass += 1
        elif not scorer and not judge:
            self.both_fail += 1
        elif scorer:
            self.scorer_only += 1
        else:
            self.judge_only += 1

    @property
    def rate(self) -> float:
        return (self.both_pass + self.both_fail) / self.n if self.n else 0.0

    def finish(self) -> Agreement:
        self.kappa = cohen_kappa(self.pairs)
        return self


def summarise(graded: list[Graded]) -> dict[str, Any]:
    """Agreement on originals, catch rates on mutants, judge self-consistency."""
    first = [g for g in graded if g.repeat == 0 and g.verdict.label is not None]
    agree: dict[str, Agreement] = defaultdict(Agreement)
    by_suite: dict[tuple[str, str], Agreement] = defaultdict(Agreement)
    by_split: dict[tuple[str, str], Agreement] = defaultdict(Agreement)
    for g in first:
        if g.case.kind != "original":
            continue
        j = g.verdict.label == "correct"
        agree[g.variant].add(g.case.scorer_correct, j)
        by_suite[(g.variant, g.case.suite)].add(g.case.scorer_correct, j)
        by_split[(g.variant, g.case.split)].add(g.case.scorer_correct, j)

    caught: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for g in first:
        if g.case.kind == "original":
            continue
        c = caught[(g.case.kind, g.variant)]
        c["n"] += 1
        c["judge_caught"] += g.verdict.label == "incorrect"
        c["scorer_caught"] += not g.case.scorer_correct

    flips: dict[str, Counter[str]] = defaultdict(Counter)
    reps: dict[tuple[str, str], set[str]] = defaultdict(set)
    for g in graded:
        if g.verdict.label is not None:
            reps[(g.case.key, g.variant)].add(g.verdict.label)
    counts: dict[tuple[str, str], int] = Counter(
        (g.case.key, g.variant) for g in graded if g.verdict.label is not None
    )
    for (key, variant), labels in reps.items():
        if counts[(key, variant)] > 1:
            flips[variant]["n"] += 1
            flips[variant]["flipped"] += len(labels) > 1

    return {
        "agreement": {v: a.finish() for v, a in agree.items()},
        "by_suite": {k: a.finish() for k, a in by_suite.items()},
        "by_split": {k: a.finish() for k, a in by_split.items()},
        "mutants": dict(caught),
        "self_consistency": dict(flips),
        "cost_usd": sum(g.verdict.cost_usd or 0 for g in graded),
    }


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def report_markdown(graded: list[Graded], model: str, sources: list[str]) -> str:
    s = summarise(graded)
    md = [
        "# LLM judge vs deterministic scorer",
        "",
        f"Judge: Claude `{model}` through `claude -p` (no tools). Replies from: "
        + ", ".join(f"`{x}`" for x in sources)
        + ". The judge prompts are in "
        "`src/courts_analyst/evaluation/llm_judge.py`.",
        "",
        "## Agreement on the agent's real replies",
        "",
        "| Judge | Replies | Agree | Cohen's κ | Scorer pass, judge fail | "
        "Scorer fail, judge pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for v, a in sorted(s["agreement"].items()):
        k = "n/a" if a.kappa is None else f"{a.kappa:.2f}"
        md.append(
            f"| {v} | {a.n} | {_pct(a.rate)} | {k} | {a.scorer_only} | {a.judge_only} |"
        )
    md += ["", "### By split", "", "| Judge | Split | Replies | Agree | κ |",
           "| --- | --- | ---: | ---: | ---: |"]  # fmt: skip
    for (v, sp), a in sorted(s["by_split"].items()):
        k = "n/a" if a.kappa is None else f"{a.kappa:.2f}"
        md.append(f"| {v} | {sp} | {a.n} | {_pct(a.rate)} | {k} |")
    md += ["", "### By suite", "", "| Judge | Suite | Replies | Agree | "
           "Scorer pass, judge fail | Scorer fail, judge pass |",
           "| --- | --- | ---: | ---: | ---: | ---: |"]  # fmt: skip
    for (v, su), a in sorted(s["by_suite"].items()):
        md.append(
            f"| {v} | {su} | {a.n} | {_pct(a.rate)} "
            f"| {a.scorer_only} | {a.judge_only} |"
        )
    md += [
        "",
        "## Known-wrong replies (mutants)",
        "",
        "Text edits of replies the scorer passed. `swap`: the current and "
        "first-published values trade places, so each carries the other's "
        "edition. `no_edition`: every edition mention removed. `nudge`: an "
        "expected value moved by 2 in its last printed digit.",
        "",
        "| Mutant | Judge | n | Scorer caught | Judge caught |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for (kind, v), c in sorted(s["mutants"].items()):
        n = c["n"]
        md.append(
            f"| {kind} | {v} | {n} "
            f"| {c['scorer_caught']} ({_pct(c['scorer_caught'] / n)}) "
            f"| {c['judge_caught']} ({_pct(c['judge_caught'] / n)}) |"
        )
    if s["self_consistency"]:
        md += [
            "",
            "## Same reply, graded twice",
            "",
            "| Judge | Replies graded twice | Verdict changed |",
            "| --- | ---: | ---: |",
        ]
        for v, c in sorted(s["self_consistency"].items()):
            md.append(
                f"| {v} | {c['n']} | {c['flipped']} ({_pct(c['flipped'] / c['n'])}) |"
            )
    md += [
        "",
        f"Judge cost at list prices: ${s['cost_usd']:.2f}.",
        "",
        "## Disagreements on real replies",
        "",
        "| Reply | Item | Suite | Judge | Scorer | Judge's reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for g in sorted(
        (
            g
            for g in graded
            if g.repeat == 0
            and g.case.kind == "original"
            and g.verdict.label is not None
            and (g.verdict.label == "correct") != g.case.scorer_correct
        ),
        key=lambda g: (g.variant, g.case.source, g.case.line),
    ):
        reason = g.verdict.reason.replace("|", "\\|").replace("\n", " ")
        md.append(
            f"| {g.case.source}:{g.case.line} | `{g.case.question_id}` "
            f"| {g.case.suite} "
            f"| {g.variant}: {g.verdict.label} | "
            f"{'pass' if g.case.scorer_correct else 'fail'} | {reason} |"
        )
    return "\n".join(md) + "\n"
