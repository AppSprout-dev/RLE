"""Scenario win/loss evaluator — checks conditions each tick."""

from __future__ import annotations

import operator as op

from pydantic import BaseModel, ConfigDict

from rle.rimapi.schemas import GameState
from rle.scenarios.schema import FailureCondition, ScenarioConfig, VictoryCondition
from rle.scoring.metrics import MetricContext

_OPERATORS = {
    ">=": op.ge,
    "<=": op.le,
    ">": op.gt,
    "<": op.lt,
    "==": op.eq,
}

# Metric accessors: metric name → callable(state, context) → float
_METRIC_ACCESSORS: dict[str, object] = {
    "survival_rate": lambda s, c: s.colony.population / max(c.initial_population, 1),
    "population": lambda s, c: float(s.colony.population),
    "wealth": lambda s, c: s.colony.wealth,
    "food_days": lambda s, c: s.colony.food_days,
    "mood_average": lambda s, c: s.colony.mood_average,
    "days_survived": lambda s, c: float(s.colony.day),
    "research_completed": lambda s, c: float(len(s.research.completed)),
    "all_colonists_dead": lambda s, c: float(s.colony.population == 0),
}


class EvaluationResult(BaseModel):
    """Outcome of scenario evaluation."""

    model_config = ConfigDict(frozen=True)

    outcome: str  # "victory", "defeat", "timeout"
    reason: str
    tick: int
    day: int


class ScenarioEvaluator:
    """Checks victory/failure conditions each tick."""

    def __init__(self, scenario: ScenarioConfig) -> None:
        self._scenario = scenario

    def evaluate(
        self, state: GameState, context: MetricContext, tick_count: int = 0,
    ) -> EvaluationResult | None:
        """Check conditions. Returns None if game should continue."""
        # Check failure first
        for cond in self._scenario.failure_conditions:
            if self._check_condition(cond, state, context):
                return EvaluationResult(
                    outcome="defeat",
                    reason=f"{cond.metric} {cond.operator} {cond.value}",
                    tick=state.colony.tick,
                    day=state.colony.day,
                )

        # Check max ticks timeout
        if self._scenario.max_ticks and tick_count >= self._scenario.max_ticks:
            return EvaluationResult(
                outcome="timeout",
                reason=f"Reached max {self._scenario.max_ticks} ticks",
                tick=state.colony.tick,
                day=state.colony.day,
            )

        # Check victory (all conditions must be met)
        if self._scenario.victory_conditions and all(
            self._check_condition(cond, state, context)
            for cond in self._scenario.victory_conditions
        ):
            return EvaluationResult(
                outcome="victory",
                reason="All victory conditions met",
                tick=state.colony.tick,
                day=state.colony.day,
            )

        return None

    def _check_condition(
        self,
        cond: VictoryCondition | FailureCondition,
        state: GameState,
        context: MetricContext,
    ) -> bool:
        accessor = _METRIC_ACCESSORS.get(cond.metric)
        if accessor is None:
            return False
        actual = accessor(state, context)  # type: ignore[operator]
        comparator = _OPERATORS.get(cond.operator)
        if comparator is None:
            return False
        return comparator(actual, cond.value)  # type: ignore[no-any-return]
