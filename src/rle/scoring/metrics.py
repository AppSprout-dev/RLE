"""Individual scoring metric functions for RLE benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field

from rle.orchestration.game_loop import TickResult
from rle.rimapi.schemas import GameState, ThreatData


@dataclass
class MetricContext:
    """Cumulative state passed to all metric functions."""

    initial_population: int = 3
    tick_results: list[TickResult] = field(default_factory=list)
    state_history: list[GameState] = field(default_factory=list)
    threats_seen: list[ThreatData] = field(default_factory=list)
    first_draft_tick: dict[str, int] = field(default_factory=dict)
    initial_wealth: float = 0.0


def survival(state: GameState, ctx: MetricContext) -> float:
    """Fraction of initial colonists still alive. 0.0–1.0."""
    if ctx.initial_population <= 0:
        return 1.0
    return min(1.0, state.colony.population / ctx.initial_population)


def threat_response(state: GameState, ctx: MetricContext) -> float:
    """Average speed of drafting response to threats. 1.0 = instant or no threats."""
    if not ctx.threats_seen:
        return 1.0
    if not ctx.first_draft_tick:
        return 0.0
    # Lower response ticks = better. Normalize: 1 tick = 1.0, 10+ ticks = 0.0
    max_response_ticks = 10
    total = 0.0
    count = 0
    for threat_id, draft_tick in ctx.first_draft_tick.items():
        total += min(draft_tick, max_response_ticks)
        count += 1
    if count == 0:
        return 0.5
    avg_ticks = total / count
    return max(0.0, 1.0 - avg_ticks / max_response_ticks)


def mood(state: GameState, ctx: MetricContext) -> float:
    """Average colonist mood. Already 0.0–1.0."""
    return max(0.0, min(1.0, state.colony.mood_average))


def food_security(state: GameState, ctx: MetricContext) -> float:
    """Food days normalized: 10+ days = 1.0, 0 days = 0.0."""
    return max(0.0, min(1.0, state.colony.food_days / 10.0))


def wealth(state: GameState, ctx: MetricContext) -> float:
    """Wealth growth ratio clamped to 0.0–1.0."""
    initial = max(ctx.initial_wealth, 1.0)
    return max(0.0, min(1.0, state.colony.wealth / initial))


def research(state: GameState, ctx: MetricContext) -> float:
    """Fraction of research tree completed."""
    completed = len(state.research.completed)
    total = completed + len(state.research.available)
    if total == 0:
        return 1.0
    return completed / total


def self_sufficiency(state: GameState, ctx: MetricContext) -> float:
    """Composite: power stable, food secure, population maintained."""
    checks = [
        1.0 if state.resources.power_net > 0 else 0.0,
        1.0 if state.colony.food_days > 5 else 0.0,
        1.0 if state.colony.population >= ctx.initial_population else 0.0,
    ]
    return sum(checks) / len(checks)


def efficiency(state: GameState, ctx: MetricContext) -> float:
    """Average action execution rate across all ticks."""
    if not ctx.tick_results:
        return 1.0
    rates = []
    for tr in ctx.tick_results:
        total = tr.execution.total
        if total > 0:
            rates.append(tr.execution.executed / total)
        else:
            rates.append(1.0)
    return sum(rates) / len(rates)


ALL_METRICS = {
    "survival": survival,
    "threat_response": threat_response,
    "mood": mood,
    "food_security": food_security,
    "wealth": wealth,
    "research": research,
    "self_sufficiency": self_sufficiency,
    "efficiency": efficiency,
}
