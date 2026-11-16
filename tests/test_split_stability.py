"""The held-out split is a pure function of the item id."""

from __future__ import annotations

import json
import subprocess
import sys

from hypothesis import given
from hypothesis import strategies as st

from courts_analyst.evaluation.bank import load_bank
from courts_analyst.evaluation.schema import assign_split

# Computed once from SHA-256 and hard-coded: if one changes, the held-out set
# has drifted (for example someone swapped the hash or the salt).
PINNED = {
    "fy2020-weighted-civil-national": "dev",
    "why-fy2020-civil-filings-jump": "dev",
    "adv-rank-judges-sdny": "dev",
    "engine-us-filed-fy2020": "test",
    "ts-cohort-count": "dev",
    "fy2024-top5-weighted-total": "dev",
}


def test_known_ids_keep_their_split() -> None:
    assert {k: assign_split(k) for k in PINNED} == PINNED
    items = {i.id: i.resolved_split for i in load_bank()}
    assert {k: items[k] for k in PINNED} == PINNED


def test_same_split_in_a_fresh_interpreter() -> None:
    """Python's hash() is salted per process; ours must not be."""
    ids = [i.id for i in load_bank()]
    code = (
        "import sys, json; from courts_analyst.evaluation.schema import assign_split;"
        "print(json.dumps([assign_split(i) for i in json.loads(sys.stdin.read())]))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(ids),
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": "12345", "PATH": ""},
    ).stdout
    assert json.loads(out) == [assign_split(i) for i in ids]


@given(st.text(min_size=1, max_size=40))
def test_split_is_deterministic(item_id: str) -> None:
    assert assign_split(item_id) == assign_split(item_id)
    assert assign_split(item_id) in {"dev", "test"}


def test_split_proportion_on_many_ids() -> None:
    ids = [f"q-{n}" for n in range(5000)]
    share = sum(assign_split(i) == "test" for i in ids) / len(ids)
    assert 0.28 <= share <= 0.32
