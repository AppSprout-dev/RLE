"""Cost tracking for RLE benchmarks with real-time OpenRouter pricing."""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_GENERATION_URL = "https://openrouter.ai/api/v1/generation"

# Gateway prefixes that wrap an OpenRouter slug (``openrouter/x-ai/…``).
# Vendor slugs themselves (``openai/``, ``x-ai/``, ``anthropic/``) are left intact.
_PRICING_GATEWAY_PREFIXES = (
    "openrouter/",
    "openrouter.ai/",
)


class CostSource(str, Enum):
    """Where the authoritative USD figure on a snapshot came from.

    ``billed`` — OpenRouter generation API (or extras marked billed).
    ``estimated`` — token-count × catalog/override price.
    ``console`` — provider-reported extras.cost_usd (ACP / coding-agent consoles).
    ``unknown`` — no trustworthy figure (failed lookup, localhost-only, $0 default).
    Unknown $0 must never be plotted as a Pareto point.
    """

    BILLED = "billed"
    ESTIMATED = "estimated"
    CONSOLE = "console"
    UNKNOWN = "unknown"


PARETO_COST_SOURCES: frozenset[CostSource] = frozenset(
    {CostSource.BILLED, CostSource.ESTIMATED, CostSource.CONSOLE},
)


def normalize_pricing_slug(model: str) -> str:
    """Strip gateway prefixes before OpenRouter ``/models`` lookup.

    Harnesses may report ``openrouter/x-ai/grok-4.6``; the catalog id is
    ``x-ai/grok-4.6``. Vendor prefixes that *are* the slug (``openai/``,
    ``x-ai/``) are not stripped.
    """
    slug = model.strip()
    lowered = slug.lower()
    for prefix in _PRICING_GATEWAY_PREFIXES:
        if lowered.startswith(prefix):
            return slug[len(prefix):]
    return slug


def is_pareto_cost_source(source: CostSource | str | None) -> bool:
    """True when ``source`` is trustworthy enough to plot on a cost Pareto."""
    if source is None:
        return False
    if isinstance(source, CostSource):
        return source in PARETO_COST_SOURCES
    try:
        return CostSource(source) in PARETO_COST_SOURCES
    except ValueError:
        return False


def infer_cost_source(
    snapshot: dict[str, Any],
    billed: dict[str, Any] | None = None,
) -> CostSource:
    """Resolve ``cost_source`` from a snapshot plus optional billed_cost block.

    Older summaries lack ``cost_source``: billed_cost → billed; a known
    pricing_source or a positive estimate → estimated; else unknown.
    """
    raw = snapshot.get("cost_source")
    if raw in {s.value for s in CostSource}:
        return CostSource(str(raw))
    if billed or snapshot.get("billed_cost_usd") is not None:
        return CostSource.BILLED
    if snapshot.get("console_cost_usd") is not None:
        return CostSource.CONSOLE
    if snapshot.get("pricing_source") in ("openrouter_api", "override"):
        return CostSource.ESTIMATED
    if float(snapshot.get("estimated_cost_usd") or 0) > 0:
        return CostSource.ESTIMATED
    return CostSource.UNKNOWN


def authoritative_cost_usd(
    snapshot: dict[str, Any],
    billed: dict[str, Any] | None = None,
) -> float | None:
    """USD to plot / export, or ``None`` when the source is unknown.

    Billed and console amounts are preferred over the token-count estimate.
    Estimated is returned only when that is the declared source. Never
    substitutes unknown $0.
    """
    source = infer_cost_source(snapshot, billed)
    if source == CostSource.BILLED:
        if billed and billed.get("billed_cost_usd") is not None:
            return float(billed["billed_cost_usd"])
        if snapshot.get("billed_cost_usd") is not None:
            return float(snapshot["billed_cost_usd"])
        return None
    if source == CostSource.CONSOLE:
        if snapshot.get("console_cost_usd") is not None:
            return float(snapshot["console_cost_usd"])
        return None
    if source == CostSource.ESTIMATED:
        return float(snapshot.get("estimated_cost_usd") or 0.0)
    return None


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
    """Cumulative cost at a point in time.

    ``estimated_cost_usd`` is always the token-count × price figure.
    ``billed_cost_usd`` / ``console_cost_usd`` persist provider-truth
    separately and are never overwritten by a later estimate.
    ``cost_source`` says which figure analyze/export may plot.
    """

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
    cost_source: CostSource = CostSource.UNKNOWN
    billed_cost_usd: float | None = None
    console_cost_usd: float | None = None


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
        # Provider-truth totals. Never overwritten by the token-count estimate.
        self._billed_cost_usd: float | None = None
        self._console_cost_usd: float | None = None

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

    def estimate_call_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        reasoning_tokens: int = 0,
    ) -> float:
        """Token-count × price for one call (0.0 when prices are unknown)."""
        return round(
            prompt_tokens * self._prompt_price
            + (completion_tokens + reasoning_tokens) * self._completion_price,
            6,
        )

    def record_provider_cost(
        self,
        cost_usd: float,
        *,
        source: CostSource = CostSource.CONSOLE,
        count_call: bool = False,
    ) -> None:
        """Accumulate a provider-reported USD charge (extras.cost_usd).

        Billed and console totals are stored separately from the token-count
        estimate and are never replaced by it. ``count_call`` increments
        ``num_calls`` for cost-only turns that recorded no tokens.
        """
        amount = float(cost_usd)
        if source == CostSource.BILLED:
            self._billed_cost_usd = (self._billed_cost_usd or 0.0) + amount
        else:
            self._console_cost_usd = (self._console_cost_usd or 0.0) + amount
        if count_call:
            self._num_calls += 1

    def apply_billed(self, billed_usd: float) -> None:
        """Attach OpenRouter billed spend without touching the estimate."""
        self._billed_cost_usd = float(billed_usd)

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
        billed = (
            round(self._billed_cost_usd, 6) if self._billed_cost_usd is not None else None
        )
        console = (
            round(self._console_cost_usd, 6) if self._console_cost_usd is not None else None
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
            cost_source=self._resolve_cost_source(round(cost, 6)),
            billed_cost_usd=billed,
            console_cost_usd=console,
        )

    def _resolve_cost_source(self, estimated: float) -> CostSource:
        """Billed wins, then console, then a trustworthy estimate, else unknown."""
        if self._billed_cost_usd is not None:
            return CostSource.BILLED
        if self._console_cost_usd is not None:
            return CostSource.CONSOLE
        if self._pricing_source in ("openrouter_api", "override") and (
            self._prompt_price > 0 or self._completion_price > 0 or estimated > 0
        ):
            return CostSource.ESTIMATED
        return CostSource.UNKNOWN


async def fetch_pricing(model: str, timeout: float = 10.0) -> tuple[float, float]:
    """Fetch per-token pricing from OpenRouter's public API.

    GET https://openrouter.ai/api/v1/models (no auth required)
    Returns (prompt_price_per_token, completion_price_per_token).
    Falls back to (0.0, 0.0) if model not found or API unreachable.

    The API returns pricing like:
    {"pricing": {"prompt": "0.000005", "completion": "0.000025"}}
    These are USD per token (strings).

    ``model`` is normalized (``openrouter/`` gateway prefix stripped) before
    matching catalog ids.
    """
    wanted = {model, normalize_pricing_slug(model)}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(OPENROUTER_MODELS_URL)
            resp.raise_for_status()
            data = resp.json()
            for m in data.get("data", []):
                catalog_id = m.get("id")
                if catalog_id in wanted or normalize_pricing_slug(str(catalog_id or "")) in wanted:
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
    slug = normalize_pricing_slug(model)
    if prompt_price_override is not None and completion_price_override is not None:
        prompt_price = prompt_price_override
        completion_price = completion_price_override
        source = "override"
    else:
        prompt_price, completion_price = await fetch_pricing(slug)
        source = (
            "openrouter_api"
            if (prompt_price > 0 or completion_price > 0)
            else "unknown"
        )
        if source == "unknown":
            logger.warning(
                "Cost tracker for %r (slug %r) resolved to $0/token — "
                "estimated_cost will be $0. Pass --prompt-price-per-mtok / "
                "--completion-price-per-mtok to override.",
                model,
                slug,
            )
        else:
            logger.info(
                "Cost tracker for %r (slug %r): prompt=$%.2f/MTok "
                "completion=$%.2f/MTok (source=%s)",
                model,
                slug,
                prompt_price * 1_000_000,
                completion_price * 1_000_000,
                source,
            )
    return CostTracker(slug, prompt_price, completion_price, pricing_source=source)


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
