"""Tests for ClaudeCodeProvider — all CLI calls are mocked."""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from felix_agent_sdk.providers.errors import ProviderError
from felix_agent_sdk.providers.types import ChatMessage, MessageRole

from rle.providers.claude_code import ClaudeCodeProvider

MESSAGES = [
    ChatMessage(role=MessageRole.SYSTEM, content="You are a test agent."),
    ChatMessage(role=MessageRole.USER, content="Do the thing."),
]


def _cli_envelope(
    result: str = '{"actions": []}',
    input_tokens: int = 100,
    output_tokens: int = 20,
    is_error: bool = False,
) -> str:
    return json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "result": result,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        "modelUsage": {"claude-fable-5": {"inputTokens": input_tokens}},
        "stop_reason": None,
    })


def _mock_proc(stdout: str, returncode: int = 0, stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def _run_complete(
    provider: ClaudeCodeProvider,
    proc: MagicMock | None = None,
    side_effect: Any = None,
) -> tuple[Any, MagicMock]:
    """Call provider.complete with mocked CLI resolution + subprocess."""
    with patch(
        "rle.providers.claude_code.shutil.which", return_value="claude",
    ), patch("rle.providers.claude_code.subprocess.run") as mock_run:
        if side_effect is not None:
            mock_run.side_effect = side_effect
        else:
            mock_run.return_value = proc or _mock_proc(_cli_envelope())
        result = provider.complete(MESSAGES)
    return result, mock_run


class TestComplete:
    def test_parses_result_and_usage(self) -> None:
        provider = ClaudeCodeProvider()
        result, _ = _run_complete(
            provider, _mock_proc(_cli_envelope(result="hello", input_tokens=50, output_tokens=7)),
        )
        assert result.content == "hello"
        assert result.model == "claude-fable-5"
        assert result.usage["prompt_tokens"] == 50
        assert result.usage["completion_tokens"] == 7
        assert result.usage["total_tokens"] == 57
        assert result.finish_reason == "stop"

    def test_cli_invocation_shape(self) -> None:
        provider = ClaudeCodeProvider(model="claude-fable-5")
        _, mock_run = _run_complete(provider)

        cmd = mock_run.call_args[0][0]
        kwargs = mock_run.call_args[1]
        assert "--model" in cmd and "claude-fable-5" in cmd
        assert "--output-format" in cmd and "json" in cmd
        assert "--tools" in cmd
        assert "--strict-mcp-config" in cmd
        assert "--system-prompt" in cmd
        assert cmd[cmd.index("--system-prompt") + 1] == "You are a test agent."
        assert kwargs["input"] == "Do the thing."

    def test_env_strips_session_and_billing_vars(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
        monkeypatch.setenv("UNRELATED_VAR", "keep-me")

        provider = ClaudeCodeProvider()
        _, mock_run = _run_complete(provider)

        env = mock_run.call_args[1]["env"]
        assert "CLAUDECODE" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_AUTH_TOKEN" not in env
        assert env["UNRELATED_VAR"] == "keep-me"

    def test_nonzero_exit_raises(self) -> None:
        provider = ClaudeCodeProvider()
        with pytest.raises(ProviderError, match="exited with code 1"):
            _run_complete(provider, _mock_proc("", returncode=1, stderr="boom"))

    def test_is_error_raises(self) -> None:
        provider = ClaudeCodeProvider()
        with pytest.raises(ProviderError, match="reported an error"):
            _run_complete(provider, _mock_proc(_cli_envelope(is_error=True)))

    def test_non_json_output_raises(self) -> None:
        provider = ClaudeCodeProvider()
        with pytest.raises(ProviderError, match="non-JSON"):
            _run_complete(provider, _mock_proc("not json at all"))

    def test_timeout_raises(self) -> None:
        provider = ClaudeCodeProvider()
        with pytest.raises(ProviderError, match="timed out"):
            _run_complete(
                provider,
                side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120),
            )

    def test_missing_cli_raises(self) -> None:
        provider = ClaudeCodeProvider()
        with patch("rle.providers.claude_code.shutil.which", return_value=None):
            with pytest.raises(ProviderError, match="not found on PATH"):
                provider.complete(MESSAGES)

    def test_assistant_messages_ignored(self) -> None:
        provider = ClaudeCodeProvider()
        messages = [
            *MESSAGES,
            ChatMessage(role=MessageRole.ASSISTANT, content="</think>"),
        ]
        with patch(
            "rle.providers.claude_code.shutil.which", return_value="claude",
        ), patch("rle.providers.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = _mock_proc(_cli_envelope())
            provider.complete(messages)
        assert mock_run.call_args[1]["input"] == "Do the thing."


class TestStreamAndTokens:
    def test_stream_yields_content_then_final(self) -> None:
        provider = ClaudeCodeProvider()
        with patch(
            "rle.providers.claude_code.shutil.which", return_value="claude",
        ), patch("rle.providers.claude_code.subprocess.run") as mock_run:
            mock_run.return_value = _mock_proc(_cli_envelope(result="streamed"))
            chunks = list(provider.stream(MESSAGES))
        assert chunks[0].text == "streamed"
        assert chunks[-1].is_final is True
        assert chunks[-1].usage is not None

    def test_count_tokens_heuristic(self) -> None:
        provider = ClaudeCodeProvider()
        messages = [ChatMessage(role=MessageRole.USER, content="a" * 400)]
        assert provider.count_tokens(messages) == 100

    def test_provider_name(self) -> None:
        assert ClaudeCodeProvider().provider_name == "claudecode"
