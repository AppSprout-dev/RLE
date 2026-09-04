"""Deterministic stand-in provider for ``--smoke-test`` runs (no LLM calls)."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.providers.types import (
    ChatMessage,
    CompletionResult,
    ProviderConfig,
    StreamChunk,
)

SMOKE_ACTION_PLAN = json.dumps({
    "actions": [
        {"action_type": "no_action", "reason": "Smoke test — no real LLM call"},
    ],
    "summary": "Smoke deliberation.",
    "confidence": 0.6,
})


class SmokeProvider(BaseProvider):
    """Returns a fixed, always-parseable action plan."""

    def __init__(self, content: str = SMOKE_ACTION_PLAN, model: str = "smoke") -> None:
        super().__init__(ProviderConfig(model=model, api_key=None))
        self._content = content
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "smoke"

    def _result(self) -> CompletionResult:
        self.calls += 1
        return CompletionResult(
            content=self._content,
            model=self.config.model,
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )

    def complete(
        self, messages: Sequence[ChatMessage], *, temperature: float | None = None,
        max_tokens: int | None = None, stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> CompletionResult:
        return self._result()

    async def acomplete(
        self, messages: Sequence[ChatMessage], *, temperature: float | None = None,
        max_tokens: int | None = None, stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> CompletionResult:
        return self._result()

    def stream(
        self, messages: Sequence[ChatMessage], *, temperature: float | None = None,
        max_tokens: int | None = None, stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        result = self._result()
        yield StreamChunk(text=result.content)
        yield StreamChunk(text="", is_final=True, usage=result.usage)

    def count_tokens(self, messages: Sequence[ChatMessage]) -> int:
        return sum(len(m.content) // 4 for m in messages)
