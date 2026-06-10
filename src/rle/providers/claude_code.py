"""Claude subscription provider: routes completions through ``claude -p``.

Bills the user's Claude subscription (Pro/Max/Team) instead of an API key
by shelling out to the Claude Code CLI in headless print mode. Tools, MCP
servers, and project settings are all disabled so a call is as close to a
raw completion as the CLI allows.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from typing import Any

from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.providers.errors import ProviderError
from felix_agent_sdk.providers.types import (
    ChatMessage,
    CompletionResult,
    MessageRole,
    ProviderConfig,
    StreamChunk,
)

logger = logging.getLogger(__name__)

# Env vars that would either crash the subprocess (nested-session guard) or
# silently flip billing from the subscription login to an API account.
_STRIPPED_ENV_VARS = ("CLAUDECODE", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class ClaudeCodeProvider(BaseProvider):
    """Provider that completes via the Claude Code CLI (``claude -p``).

    Uses the machine's existing Claude Code subscription login, so usage
    bills the Claude plan rather than the API. ``temperature``,
    ``max_tokens``, and ``stop_sequences`` are accepted but ignored — the
    CLI does not expose sampling controls (Fable-class models reject them
    anyway).
    """

    def __init__(
        self,
        model: str = "claude-fable-5",
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        config = ProviderConfig(model=model, api_key=None, base_url=base_url, **kwargs)
        super().__init__(config)
        self._cli_path: str | None = None
        # Neutral cwd so the CLI never picks up a project's CLAUDE.md.
        self._workdir = tempfile.mkdtemp(prefix="rle-claude-p-")

    def _resolve_cli(self) -> str:
        if self._cli_path is None:
            cli = shutil.which("claude")
            if cli is None:
                raise ProviderError(
                    "Claude Code CLI not found on PATH. Install it and log in "
                    "with a Claude subscription to use --provider claude-code.",
                    provider=self.provider_name,
                )
            self._cli_path = cli
        return self._cli_path

    def _split_messages(self, messages: Sequence[ChatMessage]) -> tuple[str, str]:
        """Flatten messages into (system_prompt, user_prompt) for the CLI."""
        system_parts: list[str] = []
        user_parts: list[str] = []
        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                system_parts.append(msg.content)
            elif msg.role == MessageRole.USER:
                user_parts.append(msg.content)
            else:
                logger.debug(
                    "ClaudeCodeProvider ignoring %s message (prefills unsupported)",
                    msg.role.value,
                )
        return "\n\n".join(system_parts), "\n\n".join(user_parts)

    def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> CompletionResult:
        cli = self._resolve_cli()
        system_prompt, user_prompt = self._split_messages(messages)

        cmd = [
            cli,
            "-p",
            "--model", self.config.model,
            "--output-format", "json",
            "--tools", "",
            "--setting-sources", "",
            "--strict-mcp-config",
        ]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

        env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV_VARS}

        try:
            proc = subprocess.run(
                cmd,
                input=user_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.config.timeout,
                cwd=self._workdir,
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(
                f"claude -p timed out after {self.config.timeout}s",
                provider=self.provider_name,
            ) from e

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
            raise ProviderError(
                f"claude -p exited with code {proc.returncode}: {detail}",
                provider=self.provider_name,
            )

        try:
            data: dict[str, Any] = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise ProviderError(
                f"claude -p returned non-JSON output: {proc.stdout[:500]!r}",
                provider=self.provider_name,
            ) from e

        if data.get("is_error"):
            detail = str(data.get("result", ""))[:2000]
            raise ProviderError(
                f"claude -p reported an error: {detail}",
                provider=self.provider_name,
            )

        usage_raw = data.get("usage", {})
        prompt_tokens = int(usage_raw.get("input_tokens", 0))
        completion_tokens = int(usage_raw.get("output_tokens", 0))
        model_usage = data.get("modelUsage", {})
        served_model = next(iter(model_usage), self.config.model)

        return CompletionResult(
            content=str(data.get("result", "")),
            model=served_model,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            finish_reason=str(data.get("stop_reason") or "stop"),
            raw_response=data,
        )

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """Pseudo-stream: one chunk with the full completion, then a final chunk."""
        result = self.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stop_sequences=stop_sequences,
            **kwargs,
        )
        yield StreamChunk(text=result.content)
        yield StreamChunk(text="", is_final=True, usage=result.usage)

    def count_tokens(self, messages: Sequence[ChatMessage]) -> int:
        """Character-based approximation (1 token ~ 4 characters)."""
        return sum(len(m.content) for m in messages) // 4


__all__ = ["ClaudeCodeProvider"]
