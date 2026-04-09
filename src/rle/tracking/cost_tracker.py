"""Cost tracking for RLE benchmarks with real-time OpenRouter pricing."""

from __future__ import annotations

import logging
import time

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


class TokenUsage(BaseModel):
    """Token usage from a single LLM call."""

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class CostSnapshot(BaseModel):
    """Cumulative cost at a point in time."""

    model_config = ConfigDict(frozen=True)

    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    wall_time_s: float
    num_calls: int


class CostTracker:
    """Accumulates token usage and estimates cost across a benchmark run."""

    def __init__(
        self,
        model: str,
        prompt_price: float = 0.0,
        completion_price: float = 0.0,
    ) -> None:
        self._prompt_price = prompt_price
        self._completion_price = completion_price
        self._total_prompt = 0
        self._total_completion = 0
        self._num_calls = 0
        self._start_time = time.monotonic()

    def record(self, usage: TokenUsage) -> None:
        """Record token usage from one LLM call."""
        self._total_prompt += usage.prompt_tokens
        self._total_completion += usage.completion_tokens
        self._num_calls += 1

    def record_raw(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record from raw token counts (convenience for dict-based usage)."""
        self.record(TokenUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens))

    def snapshot(self) -> CostSnapshot:
        """Current cumulative cost."""
        total = self._total_prompt + self._total_completion
        cost = (
            self._total_prompt * self._prompt_price
            + self._total_completion * self._completion_price
        )
        return CostSnapshot(
            total_prompt_tokens=self._total_prompt,
            total_completion_tokens=self._total_completion,
            total_tokens=total,
            estimated_cost_usd=round(cost, 6),
            wall_time_s=round(time.monotonic() - self._start_time, 2),
            num_calls=self._num_calls,
        )


async def fetch_pricing(model: str, timeout: float = 10.0) -> tuple[float, float]:
    """Fetch per-token pricing from OpenRouter's public API.

    GET https://openrouter.ai/api/v1/models (no auth required)
    Returns (prompt_price_per_token, completion_price_per_token).
    Falls back to (0.0, 0.0) if model not found or API unreachable.

    The API returns pricing like:
    {"pricing": {"prompt": "0.000005", "completion": "0.000025"}}
    These are USD per token (strings).
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(OPENROUTER_MODELS_URL)
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("data", []):
                if m.get("id") == model:
                    pricing = m.get("pricing", {})
                    prompt = float(pricing.get("prompt", "0"))
                    completion = float(pricing.get("completion", "0"))
                    return (prompt, completion)
        logger.warning("Model %r not found in OpenRouter pricing, using $0.00", model)
        return (0.0, 0.0)
    except Exception:
        logger.warning("Could not fetch OpenRouter pricing, using $0.00", exc_info=True)
        return (0.0, 0.0)


async def create_cost_tracker(model: str) -> CostTracker:
    """Create a CostTracker with pricing fetched from OpenRouter."""
    prompt_price, completion_price = await fetch_pricing(model)
    return CostTracker(model, prompt_price, completion_price)
