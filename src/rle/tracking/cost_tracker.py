"""Cost tracking for RLE benchmarks with real-time OpenRouter pricing."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_GENERATION_URL = "https://openrouter.ai/api/v1/generation"


class TokenUsage(BaseModel):
    """Token usage from a single LLM call.

    ``reasoning_tokens`` are the hidden chain-of-thought tokens that thinking
    models (Nemotron, DeepSeek-R1, Gemini-thinking, etc.) emit. OpenRouter
    reports them in ``usage.completion_tokens_details.reasoning_tokens`` and —
    critically — does NOT fold them into ``completion_tokens``, yet bills them
    at the completion rate. Tracking them separately is what closed the gap
    between our estimates and the OpenRouter dashboard actuals (see issue #33:
    deepseekv4 was undercounted +187%, gemini35 +35%).
    """

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens + self.reasoning_tokens

    @property
    def billable_completion_tokens(self) -> int:
        """Output tokens billed at the completion rate (visible + reasoning)."""
        return self.completion_tokens + self.reasoning_tokens


class CostSnapshot(BaseModel):
    """Cumulative cost at a point in time."""

    model_config = ConfigDict(frozen=True)

    total_prompt_tokens: int
    total_completion_tokens: int
    total_reasoning_tokens: int
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


class BilledCostReport(BaseModel):
    """Ground-truth billed cost reconciled from OpenRouter's generation API.

    Token-count × price estimates diverge from the OpenRouter dashboard by up
    to 4x in both directions (reasoning-token shapes vary per provider;
    prompt-caching discounts aren't modeled). The ``/api/v1/generation``
    endpoint returns the exact billed cost per call, so summing it over a
    run's generation IDs gives the real spend — see the v0.3.0 spread
    reconciliation in results/spread/real_costs_openrouter.json.
    """

    model_config = ConfigDict(frozen=True)

    billed_cost_usd: float
    billed_generations: int
    missing_generations: int
    source: str = "openrouter_generation_api"


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
        self._total_reasoning = 0
        self._num_calls = 0
        self._start_time = time.monotonic()
        self._generation_ids: list[str] = []

    def record_generation_id(self, generation_id: str | None) -> None:
        """Remember a provider generation ID for billed-cost reconciliation.

        IDs accumulate for EVERY provider call — including parse retries and
        deliberations that later failed to parse — because those bill tokens
        too. No-op on None/empty (non-OpenRouter providers may not set one).
        """
        if generation_id:
            self._generation_ids.append(generation_id)

    @property
    def generation_ids(self) -> list[str]:
        return list(self._generation_ids)

    def record(self, usage: TokenUsage) -> None:
        """Record token usage from one LLM call."""
        self._total_prompt += usage.prompt_tokens
        self._total_completion += usage.completion_tokens
        self._total_reasoning += usage.reasoning_tokens
        self._num_calls += 1

    def record_raw(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        reasoning_tokens: int = 0,
    ) -> None:
        """Record from raw token counts (convenience for dict-based usage)."""
        self.record(
            TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reasoning_tokens=reasoning_tokens,
            )
        )

    def snapshot(self) -> CostSnapshot:
        """Current cumulative cost.

        Reasoning tokens are billed at the completion rate — providers that
        emit hidden chain-of-thought (OpenRouter, OpenAI o-series) charge them
        as output but report them outside ``completion_tokens``.
        """
        total = self._total_prompt + self._total_completion + self._total_reasoning
        cost = (
            self._total_prompt * self._prompt_price
            + (self._total_completion + self._total_reasoning) * self._completion_price
        )
        return CostSnapshot(
            total_prompt_tokens=self._total_prompt,
            total_completion_tokens=self._total_completion,
            total_reasoning_tokens=self._total_reasoning,
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


async def fetch_billed_costs(
    generation_ids: list[str],
    api_key: str,
    *,
    url: str = OPENROUTER_GENERATION_URL,
    concurrency: int = 8,
    timeout: float = 15.0,
    retry_delay_s: float = 2.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BilledCostReport | None:
    """Sum the exact billed cost for a run from OpenRouter's generation API.

    GET https://openrouter.ai/api/v1/generation?id=<gen_id> (authenticated)
    returns ``data.total_cost`` — the ground-truth USD charge for that call.
    Generation stats lag the completion by a moment, so a miss is retried
    once after ``retry_delay_s``. Returns None when there is nothing to
    reconcile (no IDs, or every lookup failed — e.g. wrong key), never a
    misleading $0 report. ``transport`` is injectable for tests.
    """
    if not generation_ids:
        return None
    semaphore = asyncio.Semaphore(concurrency)

    async def _fetch_one(client: httpx.AsyncClient, gen_id: str) -> float | None:
        for attempt in range(2):
            try:
                resp = await client.get(url, params={"id": gen_id})
                if resp.status_code == 200:
                    cost = resp.json().get("data", {}).get("total_cost")
                    return float(cost) if cost is not None else 0.0
            except Exception:
                logger.debug("Generation lookup failed for %s", gen_id, exc_info=True)
            if attempt == 0:
                await asyncio.sleep(retry_delay_s)
        return None

    async def _bounded(client: httpx.AsyncClient, gen_id: str) -> float | None:
        async with semaphore:
            return await _fetch_one(client, gen_id)

    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}"},
        transport=transport,
    ) as client:
        results = await asyncio.gather(
            *(_bounded(client, g) for g in generation_ids),
        )

    costs = [r for r in results if r is not None]
    missing = len(results) - len(costs)
    if not costs:
        logger.warning(
            "Billed-cost reconciliation found none of %d generations — "
            "check the API key / provider. Falling back to estimates.",
            len(generation_ids),
        )
        return None
    if missing:
        logger.warning(
            "Billed-cost reconciliation missing %d/%d generations — "
            "billed_cost_usd is a LOWER BOUND for this run.",
            missing, len(generation_ids),
        )
    return BilledCostReport(
        billed_cost_usd=round(sum(costs), 6),
        billed_generations=len(costs),
        missing_generations=missing,
    )
