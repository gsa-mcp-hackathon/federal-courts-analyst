"""Guardrail settings and policy texts, from ``core/data/guardrails.yaml``."""

from __future__ import annotations

from functools import cache
from importlib import resources
from typing import Any, Final

import yaml

from courts_analyst.core.errors import DeclinedError
from courts_analyst.core.results import Decline, DeclineReason


@cache
def config() -> dict[str, Any]:
    text = resources.files("courts_analyst.core").joinpath("data/guardrails.yaml")
    data: dict[str, Any] = yaml.safe_load(text.read_text())
    return data


SMALL_CELL_WARN: Final[int] = int(config()["small_cells"]["warn"])
SMALL_CELL_SUPPRESS: Final[int] = int(config()["small_cells"]["suppress"])
MAX_RESULT_BYTES: Final[int] = int(config()["output"]["max_result_bytes"])

_REASON: dict[str, DeclineReason] = {
    "judge_level": "judge_level",
    "pii": "pii",
    "pii_scanner": "pii",
    "small_cell": "small_cell",
    "advocacy": "advocacy",
}


def policy_decline(key: str, message: str | None = None) -> Decline:
    """The :class:`Decline` for policy ``key`` (a key under ``policies``)."""
    p = config()["policies"][key]
    return Decline(
        reason=_REASON.get(key, "policy"),
        message=" ".join((message or p["message"]).split()),
        policy=" ".join(p["policy"].split()) + f" Source: {p['source']}",
        alternative=" ".join(p["alternative"].split()),
    )


def declined_error(key: str, message: str | None = None) -> DeclinedError:
    """A :class:`DeclinedError` carrying policy ``key``'s decline."""
    d = policy_decline(key, message)
    return DeclinedError(d.message, d.reason, decline=d)
