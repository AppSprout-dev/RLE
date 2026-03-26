"""Integration test: full scenario run with scoring, evaluation, and benchmark flow."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
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
from rle.orchestration.game_loop import RLEGameLoop
from rle.rimapi.client import RimAPIClient
from rle.scenarios.evaluator import ScenarioEvaluator
from rle.scenarios.loader import list_scenarios, load_scenario
from rle.scoring.composite import CompositeScorer
from rle.scoring.recorder import TimeSeriesRecorder

DEFINITIONS_DIR = (
    Path(__file__).parent.parent.parent / "src" / "rle" / "scenarios" / "definitions"
)

ACTION_PLAN_JSON = json.dumps({
    "actions": [
        {
            "action_type": "no_action",
            "reason": "Mock deliberation",
        },
    ],
    "summary": "Mock plan.",
    "confidence": 0.65,
})


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


def _make_transport(day: int = 12) -> httpx.MockTransport:
    routes: dict[str, dict | list] = {
        "/api/v1/colonists": [
            {
                "colonist_id": "col_01", "name": "Tynan", "health": 0.95,
                "mood": 0.72, "skills": {"shooting": 8, "construction": 5,
                "cooking": 3, "mining": 6},
                "traits": ["industrious"], "current_job": "mining",
                "is_drafted": False, "needs": {"food": 0.6},
                "injuries": [], "position": [42, 18],
            },
            {
                "colonist_id": "col_02", "name": "Cassandra", "health": 0.88,
                "mood": 0.65, "skills": {"construction": 7, "growing": 8},
                "traits": ["kind"], "current_job": "growing",
                "is_drafted": False, "needs": {"food": 0.5},
                "injuries": [], "position": [30, 22],
            },
            {
                "colonist_id": "col_03", "name": "Randy", "health": 0.92,
                "mood": 0.58, "skills": {"shooting": 10, "melee": 7},
                "traits": ["tough"], "current_job": None,
                "is_drafted": False, "needs": {"food": 0.4},
                "injuries": [], "position": [50, 10],
            },
        ],
        "/api/v1/resources/summary?map_id=0": {
            "total_items": 500, "total_market_value": 1500.0,
            "critical_resources": {
                "food_summary": {"food_total": 120},
                "medicine_total": 8, "weapon_count": 3,
            },
        },
        "/api/v1/map/buildings?map_id=0": [],
        "/api/v1/research/summary": {
            "current_project": "electricity", "progress": 0.45,
            "completed": ["stonecutting"],
            "available": ["electricity", "battery"],
        },
        "/api/v1/incidents?map_id=0": {"incidents": []},
        "/api/v1/game/state": {
            "name": "New Hope", "wealth": 15000.0, "day": day,
            "tick": day * 60000, "population": 3, "mood_average": 0.65,
            "food_days": 8.5,
        },
        "/api/v1/map/weather?map_id=0": {
            "weather": "clear", "temperature": 22.0,
        },
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


def _make_provider() -> MagicMock:
    provider = MagicMock(spec=BaseProvider)
    provider.complete.return_value = CompletionResult(
        content=ACTION_PLAN_JSON, model="mock",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )
    return provider


def _make_all_agents(provider: MagicMock) -> list:
    helix = HelixConfig.default().to_geometry()
    return [
        ResourceManager("rm", provider, helix, spawn_time=0.0, velocity=1.0),
        DefenseCommander("dc", provider, helix, spawn_time=0.0, velocity=1.0),
        ResearchDirector("rd", provider, helix, spawn_time=0.0, velocity=1.0),
        SocialOverseer("so", provider, helix, spawn_time=0.0, velocity=1.0),
        ConstructionPlanner("cp", provider, helix, spawn_time=0.0, velocity=1.0),
        MedicalOfficer("mo", provider, helix, spawn_time=0.0, velocity=1.0),
    ]


# ------------------------------------------------------------------
# Scenario run with integrated scoring
# ------------------------------------------------------------------


class TestIntegratedScenarioRun:
    async def test_crashlanded_with_scoring(self) -> None:
        scenario = load_scenario(DEFINITIONS_DIR / "01_crashlanded_survival.yaml")
        provider = _make_provider()
        agents = _make_all_agents(provider)
        scorer = CompositeScorer(scenario.scoring_weights or None)
        recorder = TimeSeriesRecorder()
        evaluator = ScenarioEvaluator(scenario)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(day=12), base_url="http://test",
            )
            loop = RLEGameLoop(
                config, client, agents,
                expected_duration_days=scenario.expected_duration_days,
                scorer=scorer,
                recorder=recorder,
                evaluator=evaluator,
                initial_population=scenario.initial_population,
                initial_wealth=15000.0,
            )
            await loop.run(max_ticks=10)

        # Scoring integrated — every tick has a score
        assert len(recorder.snapshots) == 10
        for result in loop.tick_results:
            assert result.score is not None

        final = scorer.final_score(recorder.snapshots)
        assert 0.0 <= final.composite <= 1.0
        assert "survival" in final.metrics
        assert "mood" in final.metrics

    async def test_csv_export(self) -> None:
        provider = _make_provider()
        agents = _make_all_agents(provider)
        scorer = CompositeScorer()
        recorder = TimeSeriesRecorder()
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(
                config, client, agents,
                scorer=scorer, recorder=recorder,
                initial_population=3, initial_wealth=15000.0,
            )
            await loop.run(max_ticks=3)

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name
        recorder.to_csv(csv_path)

        content = Path(csv_path).read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 4  # header + 3 rows
        assert "composite" in lines[0]
        assert "survival" in lines[0]

    async def test_evaluator_continues_at_day_12(self) -> None:
        """day=12, victory needs days>=30, so game continues."""
        scenario = load_scenario(DEFINITIONS_DIR / "01_crashlanded_survival.yaml")
        provider = _make_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm", provider, helix, spawn_time=0.0, velocity=1.0)
        evaluator = ScenarioEvaluator(scenario)
        config = RLEConfig(tick_interval=0.0)

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(day=12), base_url="http://test",
            )
            loop = RLEGameLoop(
                config, client, [agent], evaluator=evaluator,
                initial_population=scenario.initial_population,
            )
            await loop.run(max_ticks=5)

        # No victory/defeat at day 12 — loop ran all 5 ticks
        assert len(loop.tick_results) == 5
        assert loop.evaluation_result is None


# ------------------------------------------------------------------
# Full benchmark flow (all 6 scenarios)
# ------------------------------------------------------------------


class TestBenchmarkFlow:
    async def test_all_scenarios_run(self) -> None:
        """Load all 6 scenarios, run each for 5 ticks, collect scores."""
        provider = _make_provider()
        scenarios = list_scenarios(DEFINITIONS_DIR)
        assert len(scenarios) == 6

        results = []
        for scenario in scenarios:
            agents = _make_all_agents(provider)
            scorer = CompositeScorer(scenario.scoring_weights or None)
            recorder = TimeSeriesRecorder()
            config = RLEConfig(tick_interval=0.0)

            async with RimAPIClient("http://test") as client:
                client._client = httpx.AsyncClient(
                    transport=_make_transport(), base_url="http://test",
                )
                loop = RLEGameLoop(
                    config, client, agents,
                    expected_duration_days=scenario.expected_duration_days,
                    scorer=scorer,
                    recorder=recorder,
                    initial_population=scenario.initial_population,
                    initial_wealth=8000.0,
                )
                await loop.run(max_ticks=5)

            final = scorer.final_score(recorder.snapshots)
            results.append({
                "name": scenario.name,
                "score": final.composite,
                "ticks": len(loop.tick_results),
            })

        assert len(results) == 6
        for r in results:
            assert r["ticks"] == 5
            assert 0.0 <= r["score"] <= 1.0
