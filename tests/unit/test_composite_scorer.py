"""Tests for CompositeScorer."""

from __future__ import annotations

import pytest
from rle.rimapi.schemas import (
    ColonyData,
    GameState,
    MapData,
    ResearchData,
    ResourceData,
    WeatherData,
)
from rle.scoring.composite import DEFAULT_WEIGHTS, CompositeScorer, ScoreSnapshot
from rle.scoring.metrics import MetricContext


def _state() -> GameState:
    return GameState(
        colony=ColonyData(
            name="Test", wealth=5000.0, day=10, tick=600000,
            population=3, mood_average=0.7, food_days=10.0,
        ),
        colonists=[],
        resources=ResourceData(
            food=100.0, medicine=5, steel=200, wood=300,
            components=10, silver=500, power_net=100.0,
        ),
        map=MapData(
            size=(250, 250), biome="temperate_forest", season="summer",
            temperature=22.0, structures=[],
        ),
        research=ResearchData(
            current_project=None, progress=0.0, completed=["a"], available=["b"],
        ),
        threats=[],
        weather=WeatherData(condition="clear", temperature=22.0, outdoor_severity=0.0),
        timestamp=0.0,
    )


def _ctx() -> MetricContext:
    return MetricContext(initial_population=3, initial_wealth=5000.0)


class TestDefaultWeights:
    def test_sum_to_one(self) -> None:
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_eight_metrics(self) -> None:
        assert len(DEFAULT_WEIGHTS) == 8


class TestCompositeScorer:
    def test_score_returns_snapshot(self) -> None:
        scorer = CompositeScorer()
        snap = scorer.score(_state(), _ctx())
        assert isinstance(snap, ScoreSnapshot)
        assert snap.tick == 600000
        assert snap.day == 10
        assert len(snap.metrics) == 8
        assert 0.0 <= snap.composite <= 1.0

    def test_custom_weights(self) -> None:
        # All weight on survival
        weights = {k: 0.0 for k in DEFAULT_WEIGHTS}
        weights["survival"] = 1.0
        scorer = CompositeScorer(weights)
        snap = scorer.score(_state(), _ctx())
        # survival = 3/3 = 1.0
        assert snap.composite == pytest.approx(1.0)

    def test_weights_property(self) -> None:
        scorer = CompositeScorer()
        w = scorer.weights
        assert w == DEFAULT_WEIGHTS
        # Mutation doesn't affect scorer
        w["survival"] = 0.0
        assert scorer.weights["survival"] == 0.25


class TestFinalScore:
    def test_averages_snapshots(self) -> None:
        scorer = CompositeScorer()
        snaps = [
            ScoreSnapshot(
                tick=1, day=1,
                metrics={"survival": 1.0, "mood": 0.8, "food_security": 0.6,
                         "wealth": 0.5, "research": 0.0, "threat_response": 1.0,
                         "self_sufficiency": 0.5, "efficiency": 1.0},
                composite=0.7,
            ),
            ScoreSnapshot(
                tick=2, day=2,
                metrics={"survival": 0.5, "mood": 0.6, "food_security": 0.4,
                         "wealth": 0.3, "research": 0.5, "threat_response": 0.5,
                         "self_sufficiency": 0.5, "efficiency": 0.5},
                composite=0.5,
            ),
        ]
        final = scorer.final_score(snaps)
        assert final.tick == 2
        assert final.day == 2
        assert final.metrics["survival"] == pytest.approx(0.75)
        assert final.metrics["mood"] == pytest.approx(0.7)

    def test_empty_snapshots(self) -> None:
        scorer = CompositeScorer()
        final = scorer.final_score([])
        assert final.composite == 0.0
