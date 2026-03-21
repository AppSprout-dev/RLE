"""CLI: run all RLE scenarios and output a leaderboard."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from felix_agent_sdk.core import HelixConfig
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


def _create_agents(provider, helix):  # type: ignore[no-untyped-def]
    return [
        ResourceManager("resource_manager", provider, helix, spawn_time=0.0, velocity=1.0),
        DefenseCommander("defense_commander", provider, helix, spawn_time=0.0, velocity=1.0),
        ResearchDirector("research_director", provider, helix, spawn_time=0.0, velocity=1.0),
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
    )
    await loop.run(max_ticks=scenario.max_ticks)

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
    header = f"{'Scenario':<25} {'Difficulty':<10} {'Outcome':<10} {'Score':>7} {'Ticks':>6}"
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

    config = RLEConfig()
    provider = config.get_provider()
    helix = HelixConfig.default().to_geometry()
    scenarios = list_scenarios()

    output_dir = None
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    async with RimAPIClient(config.rimapi_url) as client:
        for scenario in scenarios:
            print(f"\nRunning: {scenario.name} ({scenario.difficulty})...")
            result = await _run_scenario(
                scenario, config, client, provider, helix, output_dir,
            )
            results.append(result)

    _print_leaderboard(results)

    if output_dir:
        print(f"\nCSV results exported to {output_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all RLE benchmark scenarios")
    parser.add_argument("--output", help="Output directory for CSV results")
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    asyncio.run(main(parser.parse_args()))
