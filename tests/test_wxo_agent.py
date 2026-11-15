"""Tests for WxOAnswerer (tests/test_wxo_agent.py).

All HTTP is intercepted with httpx.MockTransport — no real instance URL,
no real tenant IDs, no real API key ever touches the wire.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from courts_analyst.evaluation.schema import QuestionItem
from courts_analyst.evaluation.wxo_agent import WxOAnswerer

# ---------------------------------------------------------------------------
# Fixtures directory
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "wxo"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Fake IAM response
# ---------------------------------------------------------------------------

_IAM_TOKEN_BODY = {
    "access_token": "fake-access-token-abc123",
    "token_type": "Bearer",
    "expires_in": 3600,
    "expiration": int(time.time()) + 3600,
    "scope": "ibm openid",
}

# ---------------------------------------------------------------------------
# QuestionItem factory
# ---------------------------------------------------------------------------


def _item(
    question: str = "What were filings in FY2020?", qid: str = "q-test-001"
) -> QuestionItem:
    from courts_analyst.evaluation.bank import load_bank

    return load_bank()[0].model_copy(update={"id": qid, "question": question})


# ---------------------------------------------------------------------------
# MockTransport helpers
# ---------------------------------------------------------------------------


class _Response:
    """Builder for mock HTTP responses."""

    def __init__(self, body: Any, status: int = 200) -> None:
        self._body = body
        self._status = status

    def build(self) -> httpx.Response:
        return httpx.Response(
            self._status,
            json=self._body,
            request=httpx.Request("GET", "http://fake"),
        )


def _make_transport(*handlers: tuple[str, Any]) -> httpx.MockTransport:
    """Return a MockTransport that serves responses in order per URL pattern.

    handlers: list of (url_substring, body_or_callable)
    If body is callable it receives the request and returns a body dict.
    """
    queue: list[tuple[str, Any]] = list(handlers)
    index = 0

    def _handle(request: httpx.Request) -> httpx.Response:
        nonlocal index
        url = str(request.url)
        for i, (pattern, body) in enumerate(queue[index:], start=index):
            if pattern in url:
                index = i + 1
                actual = body(request) if callable(body) else body
                if isinstance(actual, httpx.Response):
                    return actual
                return httpx.Response(200, json=actual, request=request)
        raise AssertionError(
            f"No handler matched URL: {url}  (handlers exhausted at index {index})"
        )

    return httpx.MockTransport(_handle)


def _make_answerer(*handlers: tuple[str, Any]) -> WxOAnswerer:
    transport = _make_transport(*handlers)
    client = httpx.Client(transport=transport)
    return WxOAnswerer(http_client=client, timeout_s=10)


def _iam_handler(request: httpx.Request) -> dict[str, Any]:
    assert "apikey" in request.content.decode()
    # key must not be inspected outside IAM endpoint — just return token
    return _IAM_TOKEN_BODY


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Two tool calls, outputs parsed from JSON, correct tokens and final text."""

    def test_final_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        record = answerer.answer(_item())

        assert record.error is None
        assert (
            record.final_text
            == "The filings in FY2020 were 554 (first published) and 322 (revised)."
        )

    def test_tool_calls_count_and_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        record = answerer.answer(_item())

        assert len(record.tool_calls) == 2
        assert record.tool_calls[0].name == "get_official_figure"
        assert record.tool_calls[1].name == "get_official_figure"

    def test_tool_call_arguments(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        record = answerer.answer(_item())

        assert record.tool_calls[0].arguments == {
            "court": "US",
            "measure": "civil_filings",
            "fiscal_year": 2020,
        }
        assert record.tool_calls[1].arguments == {
            "court": "US",
            "measure": "weighted_civil_filings_per_judgeship",
            "fiscal_year": 2020,
        }

    def test_tool_call_outputs_parsed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        record = answerer.answer(_item())

        assert record.tool_calls[0].output == {
            "status": "ok",
            "data": {
                "value": 554,
                "measure": "civil_filings",
                "court": "US",
                "fiscal_year": 2020,
            },
        }
        assert record.tool_calls[1].output == {
            "status": "ok",
            "data": {
                "value": 322,
                "measure": "weighted_civil_filings_per_judgeship",
                "court": "US",
                "fiscal_year": 2020,
            },
        }

    def test_tokens_and_model_requests(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        record = answerer.answer(_item())

        assert record.input_tokens == 400
        assert record.output_tokens == 100
        # 1 tool_calls step + 1 final = 2
        assert record.model_requests == 2
        assert record.latency_s is not None and record.latency_s >= 0

    def test_api_key_never_in_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "super-secret-key-xyz")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        record = answerer.answer(_item())

        record_json = record.model_dump_json()
        assert "super-secret-key-xyz" not in record_json

    def test_two_text_parts_joined(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Last assistant message with two text parts → joined with newline."""
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_text_parts.json")

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        record = answerer.answer(_item())

        assert record.error is None
        assert (
            record.final_text
            == "First paragraph of the answer.\nSecond paragraph with more detail."
        )


class TestPolling:
    """running → completed: polls until status flips."""

    def test_running_then_completed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")

        # Patch sleep so test doesn't wait 1 s per poll
        monkeypatch.setattr("courts_analyst.evaluation.wxo_agent._POLL_INTERVAL_S", 0)

        run_create = _load("run_create.json")
        run_running = _load("run_status_running.json")
        run_completed = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        poll_count = 0

        def poll_handler(request: httpx.Request) -> dict[str, Any]:
            nonlocal poll_count
            poll_count += 1
            return run_running if poll_count < 3 else run_completed

        transport = _make_transport(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", poll_handler),
            ("/v1/orchestrate/runs/run-0001", poll_handler),
            ("/v1/orchestrate/runs/run-0001", poll_handler),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        client = httpx.Client(transport=transport)
        answerer = WxOAnswerer(http_client=client, timeout_s=30)

        record = answerer.answer(_item())

        assert record.error is None
        assert record.final_text != ""
        assert poll_count == 3


class TestTimeout:
    """run never completes → record has error, no raise."""

    def test_timeout_returns_error_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")
        monkeypatch.setattr("courts_analyst.evaluation.wxo_agent._POLL_INTERVAL_S", 0)

        run_create = _load("run_create.json")
        run_running = _load("run_status_running.json")

        # Use an effectively zero timeout so first poll triggers it
        transport = _make_transport(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            *[("/v1/orchestrate/runs/run-0001", run_running)] * 5,
        )
        client = httpx.Client(transport=transport)
        answerer = WxOAnswerer(http_client=client, timeout_s=0)

        record = answerer.answer(_item())

        assert record.error is not None
        assert "timed out" in record.error
        assert record.final_text == ""

    def test_timeout_key_not_in_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "my-secret-timeout-key")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")
        monkeypatch.setattr("courts_analyst.evaluation.wxo_agent._POLL_INTERVAL_S", 0)

        run_create = _load("run_create.json")
        run_running = _load("run_status_running.json")

        transport = _make_transport(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            *[("/v1/orchestrate/runs/run-0001", run_running)] * 5,
        )
        client = httpx.Client(transport=transport)
        answerer = WxOAnswerer(http_client=client, timeout_s=0)

        record = answerer.answer(_item())

        assert "my-secret-timeout-key" not in (record.error or "")


class TestFailedStatus:
    """Run returns status=failed → AnswerRecord.error is set."""

    def test_failed_run_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")
        monkeypatch.setattr("courts_analyst.evaluation.wxo_agent._POLL_INTERVAL_S", 0)

        run_create = _load("run_create.json")
        run_failed = _load("run_status_failed.json")

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_failed),
        )
        record = answerer.answer(_item())

        assert record.error is not None
        assert "failed" in record.error
        assert "internal server error" in record.error

    def test_cancelled_run_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")
        monkeypatch.setattr("courts_analyst.evaluation.wxo_agent._POLL_INTERVAL_S", 0)

        run_create = _load("run_create.json")
        cancelled = {
            **_load("run_status_failed.json"),
            "status": "cancelled",
            "last_error": None,
        }

        answerer = _make_answerer(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", cancelled),
        )
        record = answerer.answer(_item())

        assert record.error is not None
        assert "cancelled" in record.error


class TestMissingEnv:
    """Missing env vars → AnswerRecord.error is set, no raise."""

    def test_all_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WXO_INSTANCE_URL", raising=False)
        monkeypatch.delenv("WXO_API_KEY", raising=False)
        monkeypatch.delenv("WXO_AGENT_ID", raising=False)

        answerer = WxOAnswerer()
        record = answerer.answer(_item())

        assert record.error is not None
        assert "WXO_INSTANCE_URL" in record.error

    def test_partial_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.delenv("WXO_API_KEY", raising=False)
        monkeypatch.delenv("WXO_AGENT_ID", raising=False)

        answerer = WxOAnswerer()
        record = answerer.answer(_item())

        assert record.error is not None
        assert "WXO_API_KEY" in record.error

    def test_error_record_has_question_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WXO_INSTANCE_URL", raising=False)
        monkeypatch.delenv("WXO_API_KEY", raising=False)
        monkeypatch.delenv("WXO_AGENT_ID", raising=False)

        answerer = WxOAnswerer()
        record = answerer.answer(_item(qid="q-missing-env"))

        assert record.question_id == "q-missing-env"
        assert record.answerer == "wxo"


class TestIAMTokenCaching:
    """IAM token is fetched once and reused across two answer() calls."""

    def test_token_fetched_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "fake-key-do-not-log")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")
        monkeypatch.setattr("courts_analyst.evaluation.wxo_agent._POLL_INTERVAL_S", 0)

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        iam_calls = 0

        def counting_iam(request: httpx.Request) -> dict[str, Any]:
            nonlocal iam_calls
            iam_calls += 1
            return _IAM_TOKEN_BODY

        # Two full answer() round-trips, one IAM token
        transport = _make_transport(
            ("iam.cloud.ibm.com", counting_iam),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        client = httpx.Client(transport=transport)
        answerer = WxOAnswerer(http_client=client, timeout_s=30)

        r1 = answerer.answer(_item(qid="q-001"))
        r2 = answerer.answer(_item(qid="q-002"))

        assert r1.error is None
        assert r2.error is None
        assert iam_calls == 1, f"Expected 1 IAM call, got {iam_calls}"

    def test_api_key_not_in_either_record(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WXO_INSTANCE_URL", "https://fake.wxo.example.com")
        monkeypatch.setenv("WXO_API_KEY", "ultra-secret-api-key-9999")
        monkeypatch.setenv("WXO_AGENT_ID", "agent-test")
        monkeypatch.setattr("courts_analyst.evaluation.wxo_agent._POLL_INTERVAL_S", 0)

        run_create = _load("run_create.json")
        run_status = _load("run_status_completed.json")
        messages = _load("messages_two_tools.json")

        transport = _make_transport(
            ("iam.cloud.ibm.com", _iam_handler),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
            ("/v1/orchestrate/runs", run_create),
            ("/v1/orchestrate/runs/run-0001", run_status),
            ("/v1/orchestrate/threads/thread-0001/messages", messages),
        )
        client = httpx.Client(transport=transport)
        answerer = WxOAnswerer(http_client=client, timeout_s=30)

        r1 = answerer.answer(_item(qid="q-001"))
        r2 = answerer.answer(_item(qid="q-002"))

        for rec in (r1, r2):
            assert "ultra-secret-api-key-9999" not in rec.model_dump_json()


class TestAnswerersRegistry:
    """'wxo' is registered in ANSWERERS but not in PAID."""

    def test_wxo_in_answerers(self) -> None:
        from courts_analyst.evaluation.answerers import ANSWERERS

        assert "wxo" in ANSWERERS

    def test_wxo_not_in_paid(self) -> None:
        from courts_analyst.evaluation.answerers import ANSWERERS, PAID

        assert "wxo" not in PAID
        assert "wxo" in ANSWERERS


# ---------------------------------------------------------------------------
# Infra error detection
# ---------------------------------------------------------------------------


class TestInfraErrorExtraction:
    """_extract_tool_calls sets error='infra: wxO tool runtime error' on matching responses."""

    def _step_history(self, content: str) -> list[dict]:  # type: ignore[type-arg]
        """Build a minimal step_history with one tool call and one response."""
        return [
            {
                "role": "assistant",
                "step_details": [
                    {
                        "type": "tool_calls",
                        "tool_calls": [
                            {
                                "id": "tc-001",
                                "name": "get_official_figure",
                                "args": {"fiscal_year": 2020},
                            },
                        ],
                    }
                ],
            },
            {
                "role": "assistant",
                "step_details": [
                    {
                        "type": "tool_response",
                        "name": "get_official_figure",
                        "tool_call_id": "tc-001",
                        "content": content,
                    }
                ],
            },
        ]

    def test_failed_to_execute_function_sets_infra_error(self) -> None:
        from courts_analyst.evaluation.wxo_agent import _extract_tool_calls

        step_history = self._step_history("Failed to execute function: timeout")
        calls = _extract_tool_calls(step_history)
        assert len(calls) == 1
        assert calls[0].error == "infra: wxO tool runtime error"

    def test_connection_refused_sets_infra_error(self) -> None:
        from courts_analyst.evaluation.wxo_agent import _extract_tool_calls

        step_history = self._step_history("Error: Connection refused by host")
        calls = _extract_tool_calls(step_history)
        assert len(calls) == 1
        assert calls[0].error == "infra: wxO tool runtime error"

    def test_case_insensitive_matching(self) -> None:
        from courts_analyst.evaluation.wxo_agent import _extract_tool_calls

        step_history = self._step_history("FAILED TO EXECUTE FUNCTION foo")
        calls = _extract_tool_calls(step_history)
        assert calls[0].error == "infra: wxO tool runtime error"

    def test_normal_response_has_no_error(self) -> None:
        from courts_analyst.evaluation.wxo_agent import _extract_tool_calls

        step_history = self._step_history('{"status": "ok", "data": {"value": 322}}')
        calls = _extract_tool_calls(step_history)
        assert calls[0].error is None

    def test_empty_response_has_no_error(self) -> None:
        from courts_analyst.evaluation.wxo_agent import _extract_tool_calls

        step_history = self._step_history("")
        calls = _extract_tool_calls(step_history)
        assert calls[0].error is None
