"""Composite scoring — weighted aggregation of individual metrics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from rle.rimapi.schemas import GameState
from rle.scoring.metrics import ALL_METRICS, MetricContext

DEFAULT_WEIGHTS: dict[str, float] = {
    "survival": 0.25,
    "threat_response": 0.15,
    "mood": 0.15,
    "food_security": 0.10,
    "wealth": 0.10,
    "research": 0.10,
    "self_sufficiency": 0.10,
    "efficiency": 0.05,
}


class ScoreSnapshot(BaseModel):
    """Per-tick metric values and weighted composite."""

    model_config = ConfigDict(frozen=True)

    tick: int
    day: int
    metrics: dict[str, float]
    composite: float


class CompositeScorer:
    """Computes weighted composite score from individual metrics."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or dict(DEFAULT_WEIGHTS)

    @property
    def weights(self) -> dict[str, float]:
        return dict(self._weights)

    def score(self, state: GameState, context: MetricContext) -> ScoreSnapshot:
        """Compute all metrics and weighted composite for current state."""
        metrics: dict[str, float] = {}
        for name, func in ALL_METRICS.items():
            metrics[name] = func(state, context)

        composite = sum(
            self._weights.get(name, 0.0) * value
            for name, value in metrics.items()
        )

        return ScoreSnapshot(
            tick=state.colony.tick,
            day=state.colony.day,
            metrics=metrics,
            composite=round(composite, 4),
        )

    def final_score(self, snapshots: list[ScoreSnapshot]) -> ScoreSnapshot:
        """Average all snapshots into a final score."""
        if not snapshots:
            return ScoreSnapshot(tick=0, day=0, metrics={}, composite=0.0)

        last = snapshots[-1]
        avg_metrics: dict[str, float] = {}
        for name in ALL_METRICS:
            values = [s.metrics.get(name, 0.0) for s in snapshots]
            avg_metrics[name] = sum(values) / len(values)

        composite = sum(
            self._weights.get(name, 0.0) * value
            for name, value in avg_metrics.items()
        )

        return ScoreSnapshot(
            tick=last.tick,
            day=last.day,
            metrics=avg_metrics,
            composite=round(composite, 4),
        )
