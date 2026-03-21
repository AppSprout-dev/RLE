"""Integration tests for the full RLE game loop."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import httpx
import pytest
from felix_agent_sdk.core import HelixConfig
from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.providers.types import CompletionResult
from rle.agents.construction_planner import ConstructionPlanner
from rle.agents.defense_commander import DefenseCommander
from rle.agents.medical_officer import MedicalOfficer
from rle.agents.research_director import ResearchDirector
from rle.agents.resource_manager import ResourceManager
from rle.agents.social_overseer import SocialOverseer
from rle.config import RLEConfig
from rle.orchestration.game_loop import RLEGameLoop, TickResult
from rle.rimapi.client import RimAPIClient
from rle.scenarios.evaluator import ScenarioEvaluator
from rle.scenarios.schema import FailureCondition, ScenarioConfig
from rle.scoring.composite import CompositeScorer
from rle.scoring.recorder import TimeSeriesRecorder

# ------------------------------------------------------------------
# Test data
# ------------------------------------------------------------------

ACTION_PLAN_JSON = json.dumps({
    "actions": [
        {
            "action_type": "set_work_priority",
            "target_colonist_id": "col_01",
            "parameters": {"skill": "growing", "priority": 1},
            "priority": 2,
            "reason": "Low food",
        },
    ],
    "summary": "Focus on food.",
    "confidence": 0.7,
})

COLONIST = {
    "colonist_id": "col_01",
    "name": "Tynan",
    "health": 0.95,
    "mood": 0.72,
    "skills": {"shooting": 8, "construction": 5, "cooking": 3, "mining": 6},
    "traits": ["industrious"],
    "current_job": "mining",
    "is_drafted": False,
    "needs": {"food": 0.6},
    "injuries": [],
    "position": [42, 18],
}

RESOURCES = {
    "food": 120.5, "medicine": 8, "steel": 300, "wood": 450,
    "components": 12, "silver": 1500, "power_net": 200.0, "items": {},
}

MAP_DATA = {
    "size": [250, 250], "biome": "temperate_forest", "season": "summer",
    "temperature": 22.0, "structures": [],
}

RESEARCH = {
    "current_project": "electricity", "progress": 0.45,
    "completed": ["stonecutting"], "available": ["electricity"],
}

WEATHER = {"condition": "clear", "temperature": 22.0, "outdoor_severity": 0.0}


def _colony_dict(day: int = 12, tick: int = 720000) -> dict:
    return {
        "name": "New Hope", "wealth": 15000.0, "day": day, "tick": tick,
        "population": 3, "mood_average": 0.68, "food_days": 8.5,
    }


def _make_transport(day: int = 12, tick: int = 720000) -> httpx.MockTransport:
    """Mock transport returning consistent game state."""
    colony = _colony_dict(day, tick)
    routes: dict[str, dict | list] = {
        "/api/colonists": [COLONIST],
        "/api/resources": RESOURCES,
        "/api/map": MAP_DATA,
        "/api/research": RESEARCH,
        "/api/threats": [],
        "/api/colony": colony,
        "/api/weather": WEATHER,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        if path in routes:
            return httpx.Response(
                200, content=json.dumps(routes[path]).encode(),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, content=b"Not found")

    return httpx.MockTransport(handler)


def _make_mock_provider() -> MagicMock:
    provider = MagicMock(spec=BaseProvider)
    provider.complete.return_value = CompletionResult(
        content=ACTION_PLAN_JSON,
        model="mock",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )
    return provider


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestSingleTick:
    async def test_run_tick_returns_tick_result(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent])
            result = await loop.run_tick()

        assert isinstance(result, TickResult)
        assert result.day == 12
        assert result.tick == 720000
        assert result.plan.role == "orchestrator"
        assert len(result.plan.actions) == 1

    async def test_execution_handles_not_implemented(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent])
            result = await loop.run_tick()

        # set_work_priority action triggers client.set_work_priorities
        # which raises NotImplementedError
        assert result.execution.failed == 1
        assert result.execution.total == 1


class TestMultipleTicks:
    async def test_run_10_ticks(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent])
            results = await loop.run(max_ticks=10)

        assert len(results) == 10
        assert all(isinstance(r, TickResult) for r in results)

    async def test_agent_called_each_tick(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent])
            await loop.run(max_ticks=5)

        assert provider.complete.call_count == 5


class TestMacroTime:
    async def test_macro_time_in_result(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(day=30), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent], expected_duration_days=60)
            result = await loop.run_tick()

        assert result.macro_time == pytest.approx(0.5)


class TestStop:
    async def test_stop_exits_loop(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.01)  # Small delay so stop() can fire

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent])

            async def stop_after_delay() -> None:
                await asyncio.sleep(0.03)
                loop.stop()

            stop_task = asyncio.create_task(stop_after_delay())
            results = await loop.run(max_ticks=100)
            await stop_task

        # Should have stopped well before 100 ticks
        assert len(results) < 100
        assert len(results) >= 1


# ------------------------------------------------------------------
# Multi-agent tests (Phase 4)
# ------------------------------------------------------------------


def _make_all_agents(provider: MagicMock) -> list:
    helix = HelixConfig.default().to_geometry()
    return [
        ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0),
        DefenseCommander("dc-01", provider, helix, spawn_time=0.0, velocity=1.0),
        ResearchDirector("rd-01", provider, helix, spawn_time=0.0, velocity=1.0),
        SocialOverseer("so-01", provider, helix, spawn_time=0.0, velocity=1.0),
        ConstructionPlanner("cp-01", provider, helix, spawn_time=0.0, velocity=1.0),
        MedicalOfficer("mo-01", provider, helix, spawn_time=0.0, velocity=1.0),
    ]


class TestMultiAgent:
    async def test_all_agents_deliberate(self) -> None:
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, agents)
            result = await loop.run_tick()

        # Provider called once per agent
        assert provider.complete.call_count == 6
        # Result is merged plan from orchestrator
        assert result.plan.role == "orchestrator"

    async def test_multi_agent_10_ticks(self) -> None:
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, agents)
            results = await loop.run(max_ticks=3)

        assert len(results) == 3
        # 6 agents * 3 ticks = 18 provider calls
        assert provider.complete.call_count == 18


# ------------------------------------------------------------------
# Scored game loop tests (Phase 6)
# ------------------------------------------------------------------


class TestScoredLoop:
    async def test_tick_result_has_score(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)
        scorer = CompositeScorer()
        recorder = TimeSeriesRecorder()

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(
                config, client, [agent],
                scorer=scorer, recorder=recorder,
                initial_population=3, initial_wealth=15000.0,
            )
            result = await loop.run_tick()

        assert result.score is not None
        assert 0.0 <= result.score.composite <= 1.0
        assert "survival" in result.score.metrics
        assert len(recorder.snapshots) == 1

    async def test_scored_5_ticks(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)
        scorer = CompositeScorer()
        recorder = TimeSeriesRecorder()

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(
                config, client, [agent],
                scorer=scorer, recorder=recorder,
                initial_population=3,
            )
            await loop.run(max_ticks=5)

        assert len(recorder.snapshots) == 5
        final = scorer.final_score(recorder.snapshots)
        assert 0.0 <= final.composite <= 1.0

    async def test_evaluator_stops_loop(self) -> None:
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        scenario = ScenarioConfig(
            name="Quick Test",
            description="Fail immediately",
            difficulty="easy",
            expected_duration_days=30,
            initial_population=10,
            victory_conditions=[],
            failure_conditions=[
                FailureCondition(metric="survival_rate", operator="<", value=0.5),
            ],
        )
        evaluator = ScenarioEvaluator(scenario)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(
                config, client, [agent],
                evaluator=evaluator,
                initial_population=scenario.initial_population,
            )
            results = await loop.run(max_ticks=100)

        # population=3, initial=10 → survival=0.3 < 0.5 → defeat on first tick
        assert len(results) == 1
        assert loop.evaluation_result is not None
        assert loop.evaluation_result.outcome == "defeat"

    async def test_no_scorer_still_works(self) -> None:
        """Game loop without scorer/evaluator works as before."""
        provider = _make_mock_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent])
            result = await loop.run_tick()

        assert result.score is None
        assert loop.evaluation_result is None
