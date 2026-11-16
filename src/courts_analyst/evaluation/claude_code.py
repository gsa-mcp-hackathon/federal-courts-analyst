"""``claude-code`` answerers: Claude, via headless Claude Code, with only this
server's MCP tools.

Each question runs ``claude -p`` in a scratch directory with every built-in
tool disabled (``--tools ""``), only this server connected
(``--strict-mcp-config``) and no session saved. The stream-json transcript
gives the tool calls, their structured results and the final answer. This
needs a logged-in Claude Code CLI, not an API key; the API-based agent
arrives in Phase 7.
"""

from __future__ import annotations

import json
import os
import shutil

# Runs the claude CLI with an argument list.
import subprocess  # nosec B404
import tempfile
import time
from pathlib import Path
from typing import Any

from courts_analyst.evaluation.bank import ROOT
from courts_analyst.evaluation.records import AnswerRecord, ToolCall
from courts_analyst.evaluation.schema import QuestionItem

SERVER = "courts-analyst"
PREFIX = f"mcp__{SERVER}__"
SYSTEM = (
    "You answer questions about federal court statistics using only the "
    "courts-analyst tools. Next to every figure you report, name the edition it "
    "comes from using its id (for example 322 (JFF-2025) or 554 (JB-2020)). You "
    "can't ask the user follow-up questions mid-answer: if the question is too "
    "ambiguous to answer, end with one clarifying question instead of guessing."
)
TIMEOUT_S = 240


def _mcp_config(data_dir: Path) -> dict[str, Any]:
    exe = ROOT / ".venv" / "bin" / "courts-analyst"
    return {
        "mcpServers": {
            SERVER: {
                "command": str(exe),
                "args": [],
                "env": {"DATA_DIR": str(data_dir), "LOG_LEVEL": "WARNING"},
            }
        }
    }


def _parse_content(content: Any) -> tuple[dict[str, Any] | None, str | None]:
    """A tool_result's content → (structured JSON, error text)."""
    text = content
    if isinstance(content, list):
        text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    if not isinstance(text, str):
        return None, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, text
    return (data, None) if isinstance(data, dict) else (None, text)


def parse_transcript(lines: list[str], question_id: str, name: str) -> AnswerRecord:
    """Turn a stream-json transcript into an :class:`AnswerRecord`."""
    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    final = ""
    usage: dict[str, Any] = {}
    duration = None
    error = None
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "assistant":
            for block in event["message"].get("content", []):
                if block.get("type") == "tool_use":
                    tool = str(block["name"]).removeprefix(PREFIX)
                    calls[block["id"]] = ToolCall(
                        name=tool, arguments=block.get("input") or {}
                    )
                    order.append(block["id"])
                elif block.get("type") == "text":
                    final = block["text"]
        elif kind == "user":
            for block in event["message"].get("content", []):
                if (
                    block.get("type") == "tool_result"
                    and block.get("tool_use_id") in calls
                ):
                    out, err = _parse_content(block.get("content"))
                    call = calls[block["tool_use_id"]]
                    call.output = out
                    if block.get("is_error") or (err and out is None):
                        call.error = err or "tool error"
        elif kind == "result":
            usage = event.get("usage") or {}
            duration = (event.get("duration_ms") or 0) / 1000
            if event.get("is_error"):
                error = str(event.get("result") or "claude reported an error")
            elif isinstance(event.get("result"), str) and event["result"]:
                final = event["result"]
    return AnswerRecord(
        question_id=question_id,
        answerer=name,
        final_text=final,
        tool_calls=[calls[i] for i in order],
        latency_s=duration,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        error=error,
    )


class ClaudeCodeAnswerer:
    """Claude with only this MCP server, through ``claude -p``."""

    def __init__(self, model: str = "sonnet", data_dir: Path | None = None) -> None:
        self.model = model
        self.name = f"claude-code-{model}"
        self.data_dir = data_dir or (ROOT / "data")
        self.exe = shutil.which("claude")

    def answer(self, item: QuestionItem) -> AnswerRecord:
        if self.exe is None:
            return AnswerRecord(
                question_id=item.id,
                answerer=self.name,
                error="the claude CLI isn't installed (https://claude.com/claude-code)",
            )
        with tempfile.TemporaryDirectory(prefix="courts-eval-") as tmp:
            cfg = Path(tmp) / "mcp.json"
            cfg.write_text(json.dumps(_mcp_config(self.data_dir)))
            cmd = [
                self.exe, "-p", item.question,
                "--output-format", "stream-json", "--verbose",
                "--tools", "",
                "--mcp-config", str(cfg), "--strict-mcp-config",
                "--allowedTools", f"mcp__{SERVER}",
                "--no-session-persistence",
                "--model", self.model,
                "--append-system-prompt", SYSTEM,
            ]  # fmt: skip
            start = time.perf_counter()
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
                return AnswerRecord(
                    question_id=item.id,
                    answerer=self.name,
                    error=f"timed out after {TIMEOUT_S}s",
                )
        record = parse_transcript(proc.stdout.splitlines(), item.id, self.name)
        if record.latency_s is None:
            record.latency_s = time.perf_counter() - start
        if not proc.stdout.strip():
            record.error = (proc.stderr.strip() or f"exit {proc.returncode}")[-500:]
        return record
