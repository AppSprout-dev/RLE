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
    # Pricing inputs surfaced in the summary so consumers can recompute or
    # spot-check that estimates aren't using a stale or zero price.
    prompt_price_per_token: float
    completion_price_per_token: float
    pricing_source: str
    """One of: "openrouter_api", "override", "unknown". "unknown" indicates
    the live fetch failed or the model wasn't in /models — in that case the
    estimated_cost_usd will be $0 and should be ignored."""


class CostTracker:
    """Accumulates token usage and estimates cost across a benchmark run."""

    def __init__(
        self,
        model: str,
        prompt_price: float = 0.0,
        completion_price: float = 0.0,
        pricing_source: str = "unknown",
    ) -> None:
        self._model = model
        self._prompt_price = prompt_price
        self._completion_price = completion_price
        self._pricing_source = pricing_source
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
            prompt_price_per_token=self._prompt_price,
            completion_price_per_token=self._completion_price,
            pricing_source=self._pricing_source,
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


async def create_cost_tracker(
    model: str,
    *,
    prompt_price_override: float | None = None,
    completion_price_override: float | None = None,
) -> CostTracker:
    """Create a CostTracker with pricing fetched from OpenRouter (or overridden).

    Both overrides accept per-TOKEN prices (USD). Use the CLI flags
    ``--prompt-price-per-mtok`` / ``--completion-price-per-mtok`` for the more
    human-readable per-million-tokens unit; conversion happens in the scripts.

    The actual prices used (and their source) are logged at INFO level so
    operators can spot stale or zero pricing without parsing the run summary.
    """
    if prompt_price_override is not None and completion_price_override is not None:
        prompt_price = prompt_price_override
        completion_price = completion_price_override
        source = "override"
    else:
        prompt_price, completion_price = await fetch_pricing(model)
        source = (
            "openrouter_api"
            if (prompt_price > 0 or completion_price > 0)
            else "unknown"
        )
        if source == "unknown":
            logger.warning(
                "Cost tracker for %r resolved to $0/token — estimated_cost "
                "will be $0. Pass --prompt-price-per-mtok / "
                "--completion-price-per-mtok to override.",
                model,
            )
        else:
            logger.info(
                "Cost tracker for %r: prompt=$%.2f/MTok completion=$%.2f/MTok "
                "(source=%s)",
                model,
                prompt_price * 1_000_000,
                completion_price * 1_000_000,
                source,
            )
    return CostTracker(model, prompt_price, completion_price, pricing_source=source)
