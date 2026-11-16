"""OpenTelemetry spans for the agent, with OpenInference attributes (Phoenix).

One ``AGENT`` span per turn, an ``LLM`` span per model request and a
``TOOL`` span per tool call. Spans go through the OpenTelemetry API, so
they cost nothing until a tracer provider is installed:
:func:`configure_tracing` installs one when ``OTEL_EXPORTER_OTLP_ENDPOINT``
is set and the ``otel`` dependency group is installed.

Like the request logs, spans carry no user text or tool arguments unless
``AGENT_TRACE_CONTENT=true`` (local debugging only): question, answer and
arguments are recorded as a hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace

logger = logging.getLogger("courts_analyst.agent")

TRACER_NAME = "courts_analyst.agent"
KIND = "openinference.span.kind"


def _capture() -> bool:
    from courts_analyst.config import settings

    return settings.agent_trace_content


def content(value: Any) -> str:
    """The value, or its hash when content capture is off."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if _capture():
        return text
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:16]


def tracer() -> trace.Tracer:
    return trace.get_tracer(TRACER_NAME)


@contextmanager
def span(name: str, kind: str, **attributes: Any) -> Iterator[trace.Span]:
    with tracer().start_as_current_span(name) as s:
        s.set_attribute(KIND, kind)
        for k, v in attributes.items():
            if v is not None:
                s.set_attribute(k, v)
        yield s


def configure_tracing() -> bool:
    """Export spans over OTLP/HTTP when an endpoint is configured."""
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found,unused-ignore]
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but the otel group isn't installed "
            "(uv sync --group otel); tracing is off"
        )
        return False
    provider = TracerProvider(
        resource=Resource.create({"service.name": "federal-courts-analyst"})
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return True
