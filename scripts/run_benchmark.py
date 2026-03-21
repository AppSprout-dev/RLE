"""CLI: run all RLE scenarios and output a leaderboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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
from rle.scenarios.loader import list_scenarios
from rle.scenarios.schema import ScenarioConfig
from rle.scoring.composite import CompositeScorer
from rle.scoring.recorder import TimeSeriesRecorder

# Mock data for --dry-run mode
_MOCK_ACTION_PLAN = json.dumps({
    "actions": [
        {
            "action_type": "no_action",
            "reason": "Mock mode — no real LLM call",
        },
    ],
    "summary": "Mock deliberation.",
    "confidence": 0.6,
})

_MOCK_ROUTES: dict[str, dict | list] = {
    "/api/colonists": [
        {
            "colonist_id": "col_01", "name": "Tynan", "health": 0.95,
            "mood": 0.72, "skills": {"shooting": 8, "construction": 5,
            "cooking": 3, "mining": 6, "intellectual": 4},
            "traits": ["industrious"], "current_job": "mining",
            "is_drafted": False, "needs": {"food": 0.6, "rest": 0.8},
            "injuries": [], "position": [42, 18],
        },
        {
            "colonist_id": "col_02", "name": "Cassandra", "health": 0.88,
            "mood": 0.65, "skills": {"shooting": 3, "construction": 7,
            "cooking": 6, "growing": 8, "intellectual": 6},
            "traits": ["kind"], "current_job": "growing",
            "is_drafted": False, "needs": {"food": 0.5, "rest": 0.7},
            "injuries": [], "position": [30, 22],
        },
        {
            "colonist_id": "col_03", "name": "Randy", "health": 0.92,
            "mood": 0.58, "skills": {"shooting": 10, "melee": 7,
            "construction": 3, "cooking": 2},
            "traits": ["tough", "brawler"], "current_job": None,
            "is_drafted": False, "needs": {"food": 0.4, "rest": 0.6},
            "injuries": [], "position": [50, 10],
        },
    ],
    "/api/resources": {
        "food": 85.0, "medicine": 5, "steel": 200, "wood": 350,
        "components": 8, "silver": 800, "power_net": 150.0, "items": {},
    },
    "/api/map": {
        "size": [250, 250], "biome": "temperate_forest", "season": "summer",
        "temperature": 22.0, "structures": [
            {"structure_id": "s_01", "def_name": "Wall", "position": [10, 10],
             "hit_points": 300.0, "max_hit_points": 300.0},
        ],
    },
    "/api/research": {
        "current_project": "electricity", "progress": 0.45,
        "completed": ["stonecutting"], "available": ["electricity", "battery", "smithing"],
    },
    "/api/threats": [],
    "/api/colony": {
        "name": "New Hope", "wealth": 8000.0, "day": 5, "tick": 300000,
        "population": 3, "mood_average": 0.65, "food_days": 7.0,
    },
    "/api/weather": {
        "condition": "clear", "temperature": 22.0, "outdoor_severity": 0.0,
    },
}


def _make_mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        if path in _MOCK_ROUTES:
            return httpx.Response(
                200, content=json.dumps(_MOCK_ROUTES[path]).encode(),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(404, content=b"Not found")

    return httpx.MockTransport(handler)


def _make_mock_provider() -> MagicMock:
    provider = MagicMock(spec=BaseProvider)
    provider.complete.return_value = CompletionResult(
        content=_MOCK_ACTION_PLAN, model="mock-model",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )
    return provider


def _create_agents(provider, helix):  # type: ignore[no-untyped-def]
    return [
        ResourceManager("resource_manager", provider, helix, spawn_time=0.0, velocity=1.0),
        DefenseCommander(
            "defense_commander", provider, helix, spawn_time=0.0, velocity=1.0,
        ),
        ResearchDirector(
            "research_director", provider, helix, spawn_time=0.0, velocity=1.0,
        ),
        SocialOverseer("social_overseer", provider, helix, spawn_time=0.0, velocity=1.0),
        ConstructionPlanner(
            "construction_planner", provider, helix, spawn_time=0.0, velocity=1.0,
        ),
        MedicalOfficer("medical_officer", provider, helix, spawn_time=0.0, velocity=1.0),
    ]


async def _run_scenario(
    scenario: ScenarioConfig,
    config: RLEConfig,
    client: RimAPIClient,
    provider,  # type: ignore[no-untyped-def]
    helix,  # type: ignore[no-untyped-def]
    output_dir: Path | None,
    max_ticks_override: int | None = None,
) -> dict:
    agents = _create_agents(provider, helix)
    scorer = CompositeScorer(scenario.scoring_weights or None)
    recorder = TimeSeriesRecorder()
    evaluator = ScenarioEvaluator(scenario)

    loop = RLEGameLoop(
        config, client, agents,
        expected_duration_days=scenario.expected_duration_days,
        scorer=scorer,
        recorder=recorder,
        evaluator=evaluator,
        initial_population=scenario.initial_population,
        initial_wealth=8000.0,
    )
    max_ticks = max_ticks_override or scenario.max_ticks
    await loop.run(max_ticks=max_ticks)

    final_score = 0.0
    if recorder.snapshots:
        final = scorer.final_score(recorder.snapshots)
        final_score = final.composite

    outcome = "timeout"
    if loop.evaluation_result:
        outcome = loop.evaluation_result.outcome

    ticks_run = len(loop.tick_results)

    if output_dir and recorder.snapshots:
        csv_name = scenario.name.lower().replace(" ", "_") + ".csv"
        recorder.to_csv(output_dir / csv_name)

    return {
        "name": scenario.name,
        "difficulty": scenario.difficulty,
        "outcome": outcome,
        "score": final_score,
        "ticks": ticks_run,
    }


def _print_leaderboard(results: list[dict]) -> None:
    print("\n" + "=" * 72)
    print("RLE BENCHMARK LEADERBOARD")
    print("=" * 72)
    header = (
        f"{'Scenario':<25} {'Difficulty':<10} {'Outcome':<10} "
        f"{'Score':>7} {'Ticks':>6}"
    )
    print(header)
    print("-" * 72)
    for r in results:
        print(
            f"{r['name']:<25} {r['difficulty']:<10} {r['outcome']:<10} "
            f"{r['score']:>7.3f} {r['ticks']:>6}"
        )
    print("-" * 72)
    scores = [r["score"] for r in results]
    passed = sum(1 for r in results if r["outcome"] == "victory")
    avg = sum(scores) / len(scores) if scores else 0.0
    print(f"Average score: {avg:.3f} | Passed: {passed}/{len(results)}")
    print("=" * 72)


async def main(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    helix = HelixConfig.default().to_geometry()
    scenarios = list_scenarios()
    config = RLEConfig(tick_interval=0.0)

    # Dry-run uses mock provider + mock RIMAPI transport
    if args.dry_run:
        provider = _make_mock_provider()
    else:
        config = RLEConfig()
        provider = config.get_provider()

    output_dir = None
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Cap ticks in dry-run to keep it fast
    ticks_override = args.ticks if args.ticks else (10 if args.dry_run else None)

    results = []
    async with RimAPIClient(config.rimapi_url) as client:
        if args.dry_run:
            client._client = httpx.AsyncClient(
                transport=_make_mock_transport(), base_url="http://mock",
            )

        for scenario in scenarios:
            print(f"\nRunning: {scenario.name} ({scenario.difficulty})...")
            result = await _run_scenario(
                scenario, config, client, provider, helix, output_dir,
                max_ticks_override=ticks_override,
            )
            results.append(result)
            print(
                f"  -> {result['outcome']} | score={result['score']:.3f} "
                f"| {result['ticks']} ticks"
            )

    _print_leaderboard(results)

    if output_dir:
        print(f"\nCSV results exported to {output_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all RLE benchmark scenarios")
    parser.add_argument("--output", help="Output directory for CSV results")
    parser.add_argument("--dry-run", action="store_true", help="Use mock provider and RIMAPI")
    parser.add_argument("--ticks", type=int, help="Override max ticks per scenario")
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    asyncio.run(main(parser.parse_args()))
