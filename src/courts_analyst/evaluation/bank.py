"""Load and validate the question bank.

``eval/questions/<suite>.yaml`` holds a list of items for one suite; each item
may omit ``suite`` (the file name supplies it). Loading fails on a schema
error, a duplicate id, or an item filed under the wrong suite.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from courts_analyst.evaluation.schema import SUITES, QuestionItem, Split, Suite

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BANK = ROOT / "eval" / "questions"


class BankError(ValueError):
    """The question bank is malformed."""


def _load_file(path: Path) -> list[QuestionItem]:
    suite = path.stem
    if suite not in SUITES:
        raise BankError(f"{path.name}: file name must be one of {SUITES}")
    raw: Any = yaml.safe_load(path.read_text()) or []
    if not isinstance(raw, list):
        raise BankError(f"{path.name}: expected a list of items")
    items = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise BankError(f"{path.name}[{i}]: expected a mapping")
        entry.setdefault("suite", suite)
        if entry["suite"] != suite:
            raise BankError(f"{path.name}[{i}]: suite {entry['suite']!r} in {suite}")
        try:
            items.append(QuestionItem.model_validate(entry))
        except ValidationError as exc:
            ident = entry.get("id", f"#{i}")
            raise BankError(f"{path.name}: {ident}: {exc}") from exc
    return items


def load_bank(directory: Path = DEFAULT_BANK) -> list[QuestionItem]:
    """Every item in the bank, in file then list order."""
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise BankError(f"no question files in {directory}")
    items = [item for f in files for item in _load_file(f)]
    dupes = [i for i, n in Counter(it.id for it in items).items() if n > 1]
    if dupes:
        raise BankError(f"duplicate ids: {sorted(dupes)}")
    return items


def within_tools(
    items: list[QuestionItem],
    tools: frozenset[str],
) -> list[QuestionItem]:
    """Keep items whose expected_tools are all in *tools*.

    Items with no expected_tools are always kept.
    """
    return [i for i in items if not i.expected_tools or set(i.expected_tools) <= tools]


def select(
    items: list[QuestionItem],
    suite: Suite | None = None,
    split: Split | None = None,
    tags: list[str] | None = None,
    ids: list[str] | None = None,
) -> list[QuestionItem]:
    """Filter items. ``tags`` keeps items carrying any of them."""
    out = items
    if suite:
        out = [i for i in out if i.suite == suite]
    if split:
        out = [i for i in out if i.resolved_split == split]
    if tags:
        out = [i for i in out if set(tags) & set(i.tags)]
    if ids:
        wanted = set(ids)
        out = [i for i in out if i.id in wanted]
    return out
