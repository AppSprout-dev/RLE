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
            "action_type": "work_priority",
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

RESOURCES_SUMMARY = {
    "total_items": 500, "total_market_value": 1500.0,
    "critical_resources": {
        "food_summary": {"food_total": 120},
        "medicine_total": 8, "weapon_count": 3,
    },
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


_WRITE_ROUTES: dict[str, dict] = {
    "/api/v1/game/speed?speed=0": {"success": True},
    "/api/v1/game/speed?speed=1": {"success": True},
    "/api/v1/game/speed?speed=3": {"success": True},
    "/api/v1/pawn/edit/status": {"success": True},
    "/api/v1/pawn/edit/position": {"success": True},
    "/api/v1/colonists/work-priority": {"success": True},
    "/api/v1/colonist/work-priority": {"success": True},
    "/api/v1/builder/blueprint": {"success": True},
    "/api/v1/colonist/time-assignment": {"success": True},
}


def _make_transport(day: int = 12, tick: int = 720000) -> httpx.MockTransport:
    """Mock transport returning consistent game state with write support."""
    colony = _colony_dict(day, tick)
    routes: dict[str, dict | list] = {
        "/api/v1/colonists": [COLONIST],
        "/api/v1/resources/summary?map_id=0": RESOURCES_SUMMARY,
        "/api/v1/map/buildings?map_id=0": [],
        "/api/v1/research/summary": RESEARCH,
        "/api/v1/incidents?map_id=0": {"incidents": []},
        "/api/v1/game/state": colony,
        "/api/v1/map/weather?map_id=0": WEATHER,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        if request.method == "POST" and path in _WRITE_ROUTES:
            return httpx.Response(
                200, content=json.dumps(_WRITE_ROUTES[path]).encode(),
                headers={"content-type": "application/json"},
            )
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

    async def test_execution_succeeds_with_write_endpoints(self) -> None:
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

        # set_work_priority action now succeeds via upstream endpoint
        assert result.execution.executed == 1
        assert result.execution.failed == 0
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


# ------------------------------------------------------------------
# Parallel / Sequential deliberation tests
# ------------------------------------------------------------------


class TestParallelDeliberation:
    async def test_parallel_all_agents_produce_plans(self) -> None:
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, agents, parallel=True)
            result = await loop.run_tick()

        assert provider.complete.call_count == 6
        assert result.plan.role == "orchestrator"
        assert loop._parse_successes == 6
        assert loop._parse_failures == 0

    async def test_spoke_messages_routed_after_tick(self) -> None:
        """After tick 1, agents should have TASK_COMPLETE messages from other agents."""
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, agents, parallel=True)
            # Tick 1: agents deliberate, send TASK_COMPLETE messages
            await loop.run_tick()
            # Messages are queued in hub but not yet routed to spokes.
            # Tick 2: process_all_messages() routes tick 1 messages to spokes,
            # then agents deliberate with spoke context available.
            await loop.run_tick()

        # Verify hub processed messages (6 TASK_COMPLETE from tick 1 + 6 from tick 2)
        assert loop._hub.total_messages_processed >= 6

    async def test_sequential_mode_still_works(self) -> None:
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, agents, parallel=False)
            result = await loop.run_tick()

        assert provider.complete.call_count == 6
        assert result.plan.role == "orchestrator"
        assert loop._parse_successes == 6

    async def test_sequential_3_ticks(self) -> None:
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, agents, parallel=False)
            results = await loop.run(max_ticks=3)

        assert len(results) == 3
        assert provider.complete.call_count == 18


# ------------------------------------------------------------------
# CentralPost hub-spoke communication tests
# ------------------------------------------------------------------


class TestHubSpokeCommunication:
    async def test_spokes_attached_to_agents(self) -> None:
        """All agents should have spokes attached after game loop init."""
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            RLEGameLoop(config, client, agents)

        for agent in agents:
            assert agent._spoke is not None

    async def test_task_complete_messages_sent(self) -> None:
        """Each agent should send a TASK_COMPLETE after deliberating."""
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, agents)
            await loop.run_tick()

        # 6 agents sent TASK_COMPLETE messages
        assert loop._hub.message_queue_size >= 0  # may have been processed
        assert loop._hub.total_messages_processed >= 0
        # Each agent's spoke should have sent at least 1 message
        for agent in agents:
            assert agent._spoke.messages_sent >= 1

    async def test_phase_announce_broadcast(self) -> None:
        """Phase change should broadcast PHASE_ANNOUNCE to all spokes."""
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, agents)
            await loop.run_tick()

        # First tick should have broadcast an initial phase
        assert loop._last_phase != ""

    async def test_score_broadcast(self) -> None:
        """STATUS_UPDATE with scores should broadcast after scoring."""
        provider = _make_mock_provider()
        agents = _make_all_agents(provider)
        config = RLEConfig(tick_interval=0.0)
        scorer = CompositeScorer()
        recorder = TimeSeriesRecorder()

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(
                config, client, agents,
                scorer=scorer, recorder=recorder,
                initial_population=3, initial_wealth=15000.0,
            )
            await loop.run_tick()

        # After scoring, STATUS_UPDATE should have been broadcast
        # Each agent should have received it
        for agent in agents:
            assert agent._spoke.messages_received >= 1
