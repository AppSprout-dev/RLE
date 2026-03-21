"""Tests for individual scoring metrics."""

from __future__ import annotations

import pytest

# Using the ActionPlan import for TickResult construction
from rle.agents.actions import ActionPlan
from rle.orchestration.action_executor import ExecutionResult
from rle.orchestration.game_loop import TickResult
from rle.rimapi.schemas import (
    ColonistData,
    ColonyData,
    GameState,
    MapData,
    ResearchData,
    ResourceData,
    ThreatData,
    WeatherData,
)
from rle.scoring.metrics import (
    MetricContext,
    efficiency,
    food_security,
    mood,
    research,
    self_sufficiency,
    survival,
    threat_response,
    wealth,
)


def _state(
    population: int = 3,
    mood_avg: float = 0.7,
    food_days: float = 10.0,
    colony_wealth: float = 5000.0,
    power_net: float = 100.0,
    completed_research: list[str] | None = None,
    available_research: list[str] | None = None,
    day: int = 10,
) -> GameState:
    return GameState(
        colony=ColonyData(
            name="Test", wealth=colony_wealth, day=day, tick=day * 60000,
            population=population, mood_average=mood_avg, food_days=food_days,
        ),
        colonists=[
            ColonistData(
                colonist_id=f"col_{i}", name=f"C{i}", health=0.9, mood=mood_avg,
                skills={}, traits=[], current_job=None, is_drafted=False,
                needs={}, injuries=[], position=(0, 0),
            )
            for i in range(population)
        ],
        resources=ResourceData(
            food=100.0, medicine=5, steel=200, wood=300,
            components=10, silver=500, power_net=power_net,
        ),
        map=MapData(
            size=(250, 250), biome="temperate_forest", season="summer",
            temperature=22.0, structures=[],
        ),
        research=ResearchData(
            current_project=None, progress=0.0,
            completed=completed_research if completed_research is not None else [],
            available=(
                available_research
                if available_research is not None
                else ["electricity", "battery"]
            ),
        ),
        threats=[],
        weather=WeatherData(condition="clear", temperature=22.0, outdoor_severity=0.0),
        timestamp=0.0,
    )


def _ctx(
    initial_pop: int = 3,
    initial_wealth: float = 5000.0,
    tick_results: list[TickResult] | None = None,
    threats_seen: list[ThreatData] | None = None,
    first_draft_tick: dict[str, int] | None = None,
) -> MetricContext:
    return MetricContext(
        initial_population=initial_pop,
        initial_wealth=initial_wealth,
        tick_results=tick_results or [],
        threats_seen=threats_seen or [],
        first_draft_tick=first_draft_tick or {},
    )


def _tick_result(executed: int, total: int) -> TickResult:
    return TickResult(
        tick=1, day=1, macro_time=0.1,
        plan=ActionPlan(role="test", tick=1, actions=[]),
        execution=ExecutionResult(executed=executed, failed=total - executed, total=total),
    )


class TestSurvival:
    def test_all_alive(self) -> None:
        assert survival(_state(population=3), _ctx(initial_pop=3)) == pytest.approx(1.0)

    def test_partial(self) -> None:
        assert survival(_state(population=2), _ctx(initial_pop=3)) == pytest.approx(2 / 3)

    def test_none_alive(self) -> None:
        assert survival(_state(population=0), _ctx(initial_pop=3)) == pytest.approx(0.0)

    def test_zero_initial(self) -> None:
        assert survival(_state(population=0), _ctx(initial_pop=0)) == pytest.approx(1.0)


class TestThreatResponse:
    def test_no_threats(self) -> None:
        assert threat_response(_state(), _ctx()) == pytest.approx(1.0)

    def test_instant_response(self) -> None:
        threats = [ThreatData(
            threat_id="t1", threat_type="raid", faction=None, enemy_count=5, threat_level=0.5,
        )]
        ctx = _ctx(threats_seen=threats, first_draft_tick={"t1": 0})
        assert threat_response(_state(), ctx) == pytest.approx(1.0)

    def test_slow_response(self) -> None:
        threats = [ThreatData(
            threat_id="t1", threat_type="raid", faction=None, enemy_count=5, threat_level=0.5,
        )]
        ctx = _ctx(threats_seen=threats, first_draft_tick={"t1": 10})
        assert threat_response(_state(), ctx) == pytest.approx(0.0)

    def test_threats_but_no_draft(self) -> None:
        threats = [ThreatData(
            threat_id="t1", threat_type="raid", faction=None, enemy_count=5, threat_level=0.5,
        )]
        ctx = _ctx(threats_seen=threats, first_draft_tick={})
        assert threat_response(_state(), ctx) == pytest.approx(0.0)


class TestMood:
    def test_high_mood(self) -> None:
        assert mood(_state(mood_avg=0.8), _ctx()) == pytest.approx(0.8)

    def test_clamped(self) -> None:
        assert mood(_state(mood_avg=1.5), _ctx()) == pytest.approx(1.0)


class TestFoodSecurity:
    def test_plenty(self) -> None:
        assert food_security(_state(food_days=15.0), _ctx()) == pytest.approx(1.0)

    def test_half(self) -> None:
        assert food_security(_state(food_days=5.0), _ctx()) == pytest.approx(0.5)

    def test_zero(self) -> None:
        assert food_security(_state(food_days=0.0), _ctx()) == pytest.approx(0.0)


class TestWealth:
    def test_doubled(self) -> None:
        s = _state(colony_wealth=10000.0)
        assert wealth(s, _ctx(initial_wealth=5000.0)) == pytest.approx(1.0)

    def test_halved(self) -> None:
        s = _state(colony_wealth=2500.0)
        assert wealth(s, _ctx(initial_wealth=5000.0)) == pytest.approx(0.5)

    def test_zero_initial(self) -> None:
        # initial clamped to 1.0 minimum
        assert wealth(_state(colony_wealth=1.0), _ctx(initial_wealth=0.0)) == pytest.approx(1.0)


class TestResearch:
    def test_none_completed(self) -> None:
        s = _state(completed_research=[], available_research=["a", "b", "c"])
        assert research(s, _ctx()) == pytest.approx(0.0)

    def test_all_completed(self) -> None:
        s = _state(completed_research=["a", "b"], available_research=[])
        assert research(s, _ctx()) == pytest.approx(1.0)

    def test_partial(self) -> None:
        s = _state(completed_research=["a"], available_research=["b", "c"])
        assert research(s, _ctx()) == pytest.approx(1 / 3)

    def test_empty_tree(self) -> None:
        s = _state(completed_research=[], available_research=[])
        assert research(s, _ctx()) == pytest.approx(1.0)


class TestSelfSufficiency:
    def test_all_good(self) -> None:
        s = _state(power_net=100.0, food_days=10.0, population=3)
        assert self_sufficiency(s, _ctx(initial_pop=3)) == pytest.approx(1.0)

    def test_no_power(self) -> None:
        s = _state(power_net=-50.0, food_days=10.0, population=3)
        assert self_sufficiency(s, _ctx(initial_pop=3)) == pytest.approx(2 / 3)

    def test_all_bad(self) -> None:
        s = _state(power_net=-10.0, food_days=2.0, population=1)
        assert self_sufficiency(s, _ctx(initial_pop=3)) == pytest.approx(0.0)


class TestEfficiency:
    def test_all_executed(self) -> None:
        ctx = _ctx(tick_results=[_tick_result(5, 5), _tick_result(3, 3)])
        assert efficiency(_state(), ctx) == pytest.approx(1.0)

    def test_none_executed(self) -> None:
        ctx = _ctx(tick_results=[_tick_result(0, 5)])
        assert efficiency(_state(), ctx) == pytest.approx(0.0)

    def test_mixed(self) -> None:
        ctx = _ctx(tick_results=[_tick_result(3, 6), _tick_result(4, 4)])
        # (0.5 + 1.0) / 2 = 0.75
        assert efficiency(_state(), ctx) == pytest.approx(0.75)

    def test_no_ticks(self) -> None:
        assert efficiency(_state(), _ctx()) == pytest.approx(1.0)

    def test_empty_plan(self) -> None:
        ctx = _ctx(tick_results=[_tick_result(0, 0)])
        assert efficiency(_state(), ctx) == pytest.approx(1.0)
