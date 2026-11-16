"""Methodology and glossary: the same Markdown and definitions the MCP
resources serve (``courts://methodology/{topic}``, ``courts://glossary``)."""

from __future__ import annotations

from importlib import resources

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from courts_analyst.api.common import cached_json
from courts_analyst.core.glossary import glossary
from courts_analyst.resources import METHODOLOGY_TOPICS

router = APIRouter(tags=["methodology"])


def _topic_text(topic: str) -> str:
    return (
        resources.files("courts_analyst.resources")
        .joinpath(f"methodology/{topic}.md")
        .read_text()
    )


@router.get("/methodology", summary="Methodology notes, one per topic (Markdown)")
async def topics(request: Request) -> Response:
    notes = []
    for topic in METHODOLOGY_TOPICS:
        text = _topic_text(topic)
        first = text.lstrip().splitlines()[0] if text.strip() else topic
        notes.append({"topic": topic, "title": first.lstrip("# ").strip()})
    return cached_json(request, {"topics": notes})


@router.get("/methodology/{topic}", summary="One methodology note (Markdown)")
async def topic(request: Request, topic: str) -> Response:
    if topic not in METHODOLOGY_TOPICS:
        return JSONResponse(
            {
                "error": "not_found",
                "message": f"Unknown topic {topic!r}.",
                "suggested_next": [f"one of: {', '.join(METHODOLOGY_TOPICS)}"],
            },
            status_code=404,
        )
    return cached_json(request, {"topic": topic, "markdown": _topic_text(topic)})


@router.get("/glossary", summary="Definitions of the terms the tables use")
async def terms(request: Request) -> Response:
    return cached_json(request, {"terms": glossary()})
