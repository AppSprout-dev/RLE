"""Tests for ScenarioEvaluator."""

from __future__ import annotations

from rle.rimapi.schemas import (
    ColonyData,
    GameState,
    MapData,
    ResearchData,
    ResourceData,
    WeatherData,
)
from rle.scenarios.evaluator import ScenarioEvaluator
from rle.scenarios.schema import FailureCondition, ScenarioConfig, VictoryCondition
from rle.scoring.metrics import MetricContext


def _scenario(
    victory: list[VictoryCondition] | None = None,
    failure: list[FailureCondition] | None = None,
    max_ticks: int | None = None,
) -> ScenarioConfig:
    return ScenarioConfig(
        name="Test",
        description="Test scenario",
        difficulty="easy",
        expected_duration_days=30,
        initial_population=3,
        victory_conditions=victory or [],
        failure_conditions=failure or [],
        max_ticks=max_ticks,
    )


def _state(population: int = 3, day: int = 10, wealth: float = 5000.0) -> GameState:
    return GameState(
        colony=ColonyData(
            name="Test", wealth=wealth, day=day, tick=day * 60000,
            population=population, mood_average=0.7, food_days=10.0,
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
            current_project=None, progress=0.0, completed=["a", "b"],
            available=["c"],
        ),
        threats=[],
        weather=WeatherData(condition="clear", temperature=22.0, outdoor_severity=0.0),
        timestamp=0.0,
    )


def _ctx(initial_pop: int = 3) -> MetricContext:
    return MetricContext(initial_population=initial_pop)


class TestVictory:
    def test_all_conditions_met(self) -> None:
        sc = _scenario(victory=[
            VictoryCondition(metric="days_survived", operator=">=", value=10),
            VictoryCondition(metric="survival_rate", operator=">=", value=0.5),
        ])
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(population=3, day=15), _ctx())
        assert result is not None
        assert result.outcome == "victory"

    def test_partial_conditions_not_met(self) -> None:
        sc = _scenario(victory=[
            VictoryCondition(metric="days_survived", operator=">=", value=30),
        ])
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(day=10), _ctx())
        assert result is None  # Game continues

    def test_no_victory_conditions(self) -> None:
        sc = _scenario(victory=[])
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(), _ctx())
        assert result is None


class TestFailure:
    def test_all_dead(self) -> None:
        sc = _scenario(failure=[
            FailureCondition(metric="all_colonists_dead", operator="==", value=1),
        ])
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(population=0), _ctx())
        assert result is not None
        assert result.outcome == "defeat"

    def test_wealth_below_threshold(self) -> None:
        sc = _scenario(failure=[
            FailureCondition(metric="wealth", operator="<", value=100),
        ])
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(wealth=50.0), _ctx())
        assert result is not None
        assert result.outcome == "defeat"

    def test_failure_checked_before_victory(self) -> None:
        sc = _scenario(
            victory=[VictoryCondition(metric="days_survived", operator=">=", value=5)],
            failure=[FailureCondition(metric="all_colonists_dead", operator="==", value=1)],
        )
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(population=0, day=10), _ctx())
        assert result is not None
        assert result.outcome == "defeat"


class TestTimeout:
    def test_max_ticks_exceeded(self) -> None:
        sc = _scenario(max_ticks=100)
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(), _ctx(), tick_count=100)
        assert result is not None
        assert result.outcome == "timeout"

    def test_under_max_ticks(self) -> None:
        sc = _scenario(max_ticks=100)
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(), _ctx(), tick_count=50)
        assert result is None


class TestContinue:
    def test_no_conditions_triggered(self) -> None:
        sc = _scenario(
            victory=[VictoryCondition(metric="days_survived", operator=">=", value=30)],
            failure=[FailureCondition(metric="all_colonists_dead", operator="==", value=1)],
        )
        ev = ScenarioEvaluator(sc)
        result = ev.evaluate(_state(population=3, day=10), _ctx())
        assert result is None
