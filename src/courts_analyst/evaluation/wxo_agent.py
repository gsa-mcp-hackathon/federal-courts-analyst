"""``wxo`` answerer: calls a watsonx Orchestrate agent via the Runs API.

Config (from the environment):
    WXO_INSTANCE_URL  – base URL of the wxO instance, no trailing slash
    WXO_API_KEY       – IBM Cloud API key (never logged or put in records)
    WXO_AGENT_ID      – UUID of the agent to call

The IAM token is fetched once and refreshed lazily when it is about to
expire.  The refresh is protected by a threading.Lock so parallel eval
workers share a single token.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

from courts_analyst.evaluation.records import AnswerRecord, ToolCall
from courts_analyst.evaluation.schema import QuestionItem

_IAM_URL = "https://iam.cloud.ibm.com/identity/token"
_EXPIRE_BUFFER_S = 60  # refresh token this many seconds before it expires
_POLL_INTERVAL_S = 1.0
_DEFAULT_TIMEOUT_S = 180


class WxOAnswerer:
    """Calls a watsonx Orchestrate agent and maps the run to an AnswerRecord."""

    name = "wxo"

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._http = http_client  # None → created lazily from env
        self._timeout_s = timeout_s

        # IAM token cache, shared and thread-safe
        self._token_lock = threading.Lock()
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0  # epoch seconds

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        """Return the httpx.Client, creating it from env on first call."""
        if self._http is None:
            self._http = httpx.Client(timeout=30)
        return self._http

    def _env(self) -> tuple[str, str, str]:
        """Return (instance_url, api_key, agent_id) from env, or raise."""
        import os

        url = os.environ.get("WXO_INSTANCE_URL", "").rstrip("/")
        key = os.environ.get("WXO_API_KEY", "")
        agent = os.environ.get("WXO_AGENT_ID", "")
        pairs = [
            ("WXO_INSTANCE_URL", url),
            ("WXO_API_KEY", key),
            ("WXO_AGENT_ID", agent),
        ]
        missing = [n for n, v in pairs if not v]
        if missing:
            raise OSError(f"Missing env vars: {', '.join(missing)}")
        return url, key, agent

    def _bearer_token(self, api_key: str) -> str:
        """Return a cached IAM access token, refreshing when near expiry."""
        with self._token_lock:
            if self._access_token and time.time() < self._token_expires_at:
                return self._access_token

            resp = self._client().post(
                _IAM_URL,
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": api_key,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()
            self._access_token = body["access_token"]
            # prefer absolute `expiration` field if present, else relative
            if "expiration" in body:
                self._token_expires_at = float(body["expiration"]) - _EXPIRE_BUFFER_S
            else:
                self._token_expires_at = (
                    time.time() + float(body.get("expires_in", 3600)) - _EXPIRE_BUFFER_S
                )
            return self._access_token

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def answer(self, item: QuestionItem) -> AnswerRecord:
        """Send *item.question* to the wxO agent and return an AnswerRecord."""
        try:
            return self._answer(item)
        except OSError as exc:
            return AnswerRecord(
                question_id=item.id,
                answerer=self.name,
                error=str(exc),
            )
        except Exception as exc:
            # Scrub any accidental key leakage (belt-and-suspenders)
            msg = _scrub(str(exc))
            return AnswerRecord(
                question_id=item.id,
                answerer=self.name,
                error=msg,
            )

    def _answer(self, item: QuestionItem) -> AnswerRecord:
        instance_url, api_key, agent_id = self._env()
        token = self._bearer_token(api_key)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        client = self._client()

        # ---- POST /v1/orchestrate/runs -----------------------------------
        t_start = time.perf_counter()
        create_resp = client.post(
            f"{instance_url}/v1/orchestrate/runs",
            json={
                "agent_id": agent_id,
                "message": {"role": "user", "content": item.question},
            },
            headers=headers,
        )
        create_resp.raise_for_status()
        create_body = create_resp.json()
        run_id: str = create_body["run_id"]
        thread_id: str = create_body["thread_id"]

        # ---- Poll GET /v1/orchestrate/runs/{run_id} ----------------------
        deadline = time.perf_counter() + self._timeout_s
        status_body: dict[str, Any] = {}
        while True:
            if time.perf_counter() > deadline:
                return AnswerRecord(
                    question_id=item.id,
                    answerer=self.name,
                    latency_s=time.perf_counter() - t_start,
                    error=(
                        f"timed out after {self._timeout_s}s waiting for run {run_id}"
                    ),
                )
            time.sleep(_POLL_INTERVAL_S)
            poll_resp = client.get(
                f"{instance_url}/v1/orchestrate/runs/{run_id}",
                headers=headers,
            )
            poll_resp.raise_for_status()
            status_body = poll_resp.json()
            status: str = status_body.get("status", "")
            if status == "completed":
                break
            if status in ("failed", "cancelled"):
                last_error = status_body.get("last_error") or status
                return AnswerRecord(
                    question_id=item.id,
                    answerer=self.name,
                    latency_s=time.perf_counter() - t_start,
                    error=f"run {status}: {last_error}",
                )
            # still running / queued – keep polling

        latency_s = time.perf_counter() - t_start

        # ---- GET /v1/orchestrate/threads/{thread_id}/messages -----------
        msg_resp = client.get(
            f"{instance_url}/v1/orchestrate/threads/{thread_id}/messages",
            headers=headers,
        )
        msg_resp.raise_for_status()
        messages: list[dict[str, Any]] = msg_resp.json()

        # ---- Extract final text -----------------------------------------
        # Take ALL text parts of the last assistant message, joined by newline.
        final_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                parts = [
                    part.get("text", "")
                    for part in msg.get("content", [])
                    if part.get("response_type") == "text"
                ]
                final_text = "\n".join(p for p in parts if p)
                break

        # ---- Extract tool calls from the last assistant message ----------
        tool_calls: list[ToolCall] = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            step_history: list[dict[str, Any]] = msg.get("step_history") or []
            tool_calls.extend(_extract_tool_calls(step_history))

        # ---- Usage -------------------------------------------------------
        usage = status_body.get("usage") or {}
        token_usage = usage.get("token_usage") or {}
        input_tokens: int | None = token_usage.get("prompt_tokens")
        output_tokens: int | None = token_usage.get("completion_tokens")

        # model_requests = number of tool_call steps + 1 (final answer)
        tool_call_steps = sum(
            1
            for msg in messages
            if msg.get("role") == "assistant"
            for step in (msg.get("step_history") or [])
            for detail in step.get("step_details", [])
            if detail.get("type") == "tool_calls"
        )
        model_requests = tool_call_steps + 1

        return AnswerRecord(
            question_id=item.id,
            answerer=self.name,
            final_text=final_text,
            tool_calls=tool_calls,
            latency_s=latency_s,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_requests=model_requests,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_tool_calls(step_history: list[dict[str, Any]]) -> list[ToolCall]:
    """Parse step_history into ToolCall objects.

    strategy:
    - collect all tool_calls entries (type="tool_calls")
    - collect all tool_response entries (type="tool_response")
    - match responses to calls by tool_call_id when present, else by name order
    """
    calls_info: list[dict[str, Any]] = []  # {id, name, args}
    responses: list[dict[str, Any]] = []  # {tool_call_id, name, content}

    for step in step_history:
        for detail in step.get("step_details", []):
            dtype = detail.get("type")
            if dtype == "tool_calls":
                for tc in detail.get("tool_calls", []):
                    calls_info.append(
                        {
                            "id": tc.get("id"),
                            "name": tc.get("name", ""),
                            "args": tc.get("args") or {},
                        }
                    )
            elif dtype == "tool_response":
                responses.append(
                    {
                        "tool_call_id": detail.get("tool_call_id"),
                        "name": detail.get("name", ""),
                        "content": detail.get("content", ""),
                    }
                )

    result: list[ToolCall] = []
    used_response_indices: set[int] = set()

    for call in calls_info:
        matched_output: dict[str, Any] | None = None
        # Try to match by tool_call_id first
        if call["id"]:
            for i, resp in enumerate(responses):
                call_id_matches = resp["tool_call_id"] == call["id"]
                if i not in used_response_indices and call_id_matches:
                    matched_output = _parse_tool_output(resp["content"])
                    used_response_indices.add(i)
                    break
        # Fallback: match by name order
        if matched_output is None:
            for i, resp in enumerate(responses):
                if i not in used_response_indices and resp["name"] == call["name"]:
                    matched_output = _parse_tool_output(resp["content"])
                    used_response_indices.add(i)
                    break

        result.append(
            ToolCall(
                name=call["name"],
                arguments=call["args"],
                output=matched_output,
            )
        )

    return result


def _parse_tool_output(content: str) -> dict[str, Any] | None:
    """Parse a tool response content string into a dict."""
    if not content:
        return None
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
        return {"text": content}
    except (json.JSONDecodeError, TypeError):
        return {"text": str(content)}


def _scrub(msg: str) -> str:
    """Remove the API key from an error message (belt-and-suspenders)."""
    import os

    key = os.environ.get("WXO_API_KEY", "")
    if key and key in msg:
        msg = msg.replace(key, "***")
    return msg
