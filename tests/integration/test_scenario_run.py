"""Integration test: full scenario run with scoring and evaluation."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
from felix_agent_sdk.core import HelixConfig
from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.providers.types import CompletionResult
from rle.agents.resource_manager import ResourceManager
from rle.config import RLEConfig
from rle.orchestration.game_loop import RLEGameLoop
from rle.scenarios.evaluator import ScenarioEvaluator
from rle.scenarios.loader import load_scenario
from rle.scoring.composite import CompositeScorer
from rle.scoring.metrics import MetricContext
from rle.scoring.recorder import TimeSeriesRecorder

DEFINITIONS_DIR = Path(__file__).parent.parent.parent / "src" / "rle" / "scenarios" / "definitions"

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


def _make_transport(day: int = 12) -> httpx.MockTransport:
    colonist = {
        "colonist_id": "col_01", "name": "Tynan", "health": 0.95, "mood": 0.72,
        "skills": {"shooting": 8, "construction": 5, "cooking": 3, "mining": 6},
        "traits": ["industrious"], "current_job": "mining", "is_drafted": False,
        "needs": {"food": 0.6}, "injuries": [], "position": [42, 18],
    }
    routes: dict[str, dict | list] = {
        "/api/colonists": [colonist],
        "/api/resources": {
            "food": 120.5, "medicine": 8, "steel": 300, "wood": 450,
            "components": 12, "silver": 1500, "power_net": 200.0, "items": {},
        },
        "/api/map": {
            "size": [250, 250], "biome": "temperate_forest", "season": "summer",
            "temperature": 22.0, "structures": [],
        },
        "/api/research": {
            "current_project": "electricity", "progress": 0.45,
            "completed": ["stonecutting"], "available": ["electricity", "battery"],
        },
        "/api/threats": [],
        "/api/colony": {
            "name": "New Hope", "wealth": 15000.0, "day": day, "tick": day * 60000,
            "population": 3, "mood_average": 0.72, "food_days": 8.5,
        },
        "/api/weather": {"condition": "clear", "temperature": 22.0, "outdoor_severity": 0.0},
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


def _make_provider() -> MagicMock:
    provider = MagicMock(spec=BaseProvider)
    provider.complete.return_value = CompletionResult(
        content=ACTION_PLAN_JSON, model="mock",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )
    return provider


class TestCrashlandedScenarioRun:
    async def test_full_scenario_with_scoring(self) -> None:
        # Load scenario
        scenario = load_scenario(DEFINITIONS_DIR / "01_crashlanded_survival.yaml")
        scorer = CompositeScorer(scenario.scoring_weights or None)
        recorder = TimeSeriesRecorder()

        # Setup agent + loop
        provider = _make_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        from rle.rimapi.client import RimAPIClient

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(day=12), base_url="http://test",
            )
            loop = RLEGameLoop(
                config, client, [agent],
                expected_duration_days=scenario.expected_duration_days,
            )

            # Run 10 ticks with scoring
            context = MetricContext(
                initial_population=scenario.initial_population,
                initial_wealth=15000.0,
            )

            for _ in range(10):
                tick_result = await loop.run_tick()
                context.tick_results.append(tick_result)

                state = loop._state_manager.current
                context.state_history.append(state)

                snapshot = scorer.score(state, context)
                recorder.record(snapshot)

        # Verify scoring
        assert len(recorder.snapshots) == 10
        final = scorer.final_score(recorder.snapshots)
        assert 0.0 <= final.composite <= 1.0
        assert "survival" in final.metrics
        assert "mood" in final.metrics

    async def test_csv_export(self) -> None:
        scorer = CompositeScorer()
        recorder = TimeSeriesRecorder()
        provider = _make_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        from rle.rimapi.client import RimAPIClient

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent])
            context = MetricContext(initial_population=3, initial_wealth=15000.0)

            for _ in range(3):
                tick_result = await loop.run_tick()
                context.tick_results.append(tick_result)
                state = loop._state_manager.current
                snapshot = scorer.score(state, context)
                recorder.record(snapshot)

        # Export and verify CSV
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name
        recorder.to_csv(csv_path)

        content = Path(csv_path).read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 4  # header + 3 data rows
        assert "composite" in lines[0]
        assert "survival" in lines[0]

    async def test_evaluator_continues(self) -> None:
        """With day=12 and victory needing days>=30, evaluator returns None."""
        scenario = load_scenario(DEFINITIONS_DIR / "01_crashlanded_survival.yaml")
        evaluator = ScenarioEvaluator(scenario)
        provider = _make_provider()
        helix = HelixConfig.default().to_geometry()
        agent = ResourceManager("rm-01", provider, helix, spawn_time=0.0, velocity=1.0)
        config = RLEConfig(tick_interval=0.0)

        from rle.rimapi.client import RimAPIClient

        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(
                transport=_make_transport(day=12), base_url="http://test",
            )
            loop = RLEGameLoop(config, client, [agent])
            await loop.run_tick()
            state = loop._state_manager.current

        context = MetricContext(initial_population=3)
        result = evaluator.evaluate(state, context)
        assert result is None  # Game continues — day 12 < 30
