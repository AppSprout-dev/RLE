"""CLI: run all RLE scenarios and output a leaderboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
from felix_agent_sdk.core import HelixConfig
from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.providers.types import CompletionResult
from felix_agent_sdk.visualization import HelixVisualizer
from rle.agents import AGENT_DISPLAY
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
    "/api/v1/colonists": [
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
    "/api/v1/resources": {
        "food": 85.0, "medicine": 5, "steel": 200, "wood": 350,
        "components": 8, "silver": 800, "power_net": 150.0, "items": {},
    },
    "/api/v1/map": {
        "size": [250, 250], "biome": "temperate_forest", "season": "summer",
        "temperature": 22.0, "structures": [
            {"structure_id": "s_01", "def_name": "Wall", "position": [10, 10],
             "hit_points": 300.0, "max_hit_points": 300.0},
        ],
    },
    "/api/v1/research/summary": {
        "current_project": "electricity", "progress": 0.45,
        "completed": ["stonecutting"], "available": ["electricity", "battery", "smithing"],
    },
    "/api/v1/threats": [],
    "/api/v1/game/state": {
        "name": "New Hope", "wealth": 8000.0, "day": 5, "tick": 300000,
        "population": 3, "mood_average": 0.65, "food_days": 7.0,
    },
    "/api/v1/map/weather": {
        "condition": "clear", "temperature": 22.0, "outdoor_severity": 0.0,
    },
}


_MOCK_POST_ROUTES: set[str] = {
    "/api/v1/game/speed",
    "/api/v1/pawn/edit/status",
    "/api/v1/pawn/edit/priority",
    "/api/v1/pawn/move",
    "/api/v1/colony/blueprint",
    "/api/v1/colony/haul",
    "/api/v1/colony/growing",
    "/api/v1/colony/power",
    "/api/v1/colony/recreation",
    "/api/v1/colony/medicine",
    "/api/v1/colony/bed",
    "/api/v1/pawn/job",
    "/api/v1/colony/research",
}


def _make_mock_transport() -> httpx.MockTransport:
    _POST_OK = httpx.Response(
        200, content=b'{"ok": true}',
        headers={"content-type": "application/json"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode().split("?")[0]
        if request.method == "POST" and path in _MOCK_POST_ROUTES:
            return _POST_OK
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


def _create_agents(provider, helix, *, provider_kwargs=None, no_think=False):  # type: ignore[no-untyped-def]
    agents = [
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
    if provider_kwargs:
        for agent in agents:
            agent.set_provider_kwargs(**provider_kwargs)
    if no_think:
        for agent in agents:
            agent.set_no_think(True)
    return agents


def _create_visualizer(helix, agents) -> HelixVisualizer:  # type: ignore[no-untyped-def]
    """Create a HelixVisualizer with all agents registered."""
    visualizer = HelixVisualizer(helix, title="R L E")
    for agent in agents:
        display = AGENT_DISPLAY[agent.agent_id]
        visualizer.register_agent(
            agent.agent_id, label=display["label"], color=display["color"],
        )
    return visualizer


async def _run_scenario(
    scenario: ScenarioConfig,
    config: RLEConfig,
    client: RimAPIClient,
    provider,  # type: ignore[no-untyped-def]
    helix,  # type: ignore[no-untyped-def]
    output_dir: Path | None,
    max_ticks_override: int | None = None,
    provider_kwargs: dict | None = None,
    visualize: bool = False,
    no_think: bool = False,
) -> dict:
    agents = _create_agents(provider, helix, provider_kwargs=provider_kwargs, no_think=no_think)
    scorer = CompositeScorer(scenario.scoring_weights or None)
    recorder = TimeSeriesRecorder()
    evaluator = ScenarioEvaluator(scenario)
    visualizer = _create_visualizer(helix, agents) if visualize else None

    loop = RLEGameLoop(
        config, client, agents,
        expected_duration_days=scenario.expected_duration_days,
        scorer=scorer,
        recorder=recorder,
        evaluator=evaluator,
        initial_population=scenario.initial_population,
        initial_wealth=8000.0,
        visualizer=visualizer,
    )
    max_ticks = max_ticks_override or scenario.max_ticks
    t0 = time.monotonic()
    if visualizer:
        with visualizer.live():
            await loop.run(max_ticks=max_ticks)
    else:
        await loop.run(max_ticks=max_ticks)
    elapsed = time.monotonic() - t0

    final_score = 0.0
    if recorder.snapshots:
        final = scorer.final_score(recorder.snapshots)
        final_score = final.composite

    outcome = "timeout"
    if loop.evaluation_result:
        outcome = loop.evaluation_result.outcome

    ticks_run = len(loop.tick_results)
    total_calls = loop._parse_successes + loop._parse_failures
    parse_rate = loop._parse_successes / total_calls if total_calls else 0.0

    if output_dir and recorder.snapshots:
        csv_name = scenario.name.lower().replace(" ", "_") + ".csv"
        recorder.to_csv(output_dir / csv_name)

    if output_dir and loop._deliberation_log:
        log_name = scenario.name.lower().replace(" ", "_") + "_deliberations.jsonl"
        with open(output_dir / log_name, "w") as f:
            for entry in loop._deliberation_log:
                f.write(json.dumps(entry) + "\n")

    return {
        "name": scenario.name,
        "difficulty": scenario.difficulty,
        "outcome": outcome,
        "score": final_score,
        "ticks": ticks_run,
        "elapsed_s": round(elapsed, 2),
        "sec_per_tick": round(elapsed / ticks_run, 2) if ticks_run else 0.0,
        "parse_successes": loop._parse_successes,
        "parse_failures": loop._parse_failures,
        "parse_rate": round(parse_rate, 3),
    }


def _print_leaderboard(results: list[dict], model: str | None = None) -> None:
    print("\n" + "=" * 88)
    title = f"RLE BENCHMARK — {model}" if model else "RLE BENCHMARK LEADERBOARD"
    print(title)
    print("=" * 88)
    header = (
        f"{'Scenario':<25} {'Diff':<7} {'Outcome':<9} "
        f"{'Score':>6} {'Ticks':>5} {'Time':>7} {'s/tick':>6} "
        f"{'Parse%':>7} {'Fail':>4}"
    )
    print(header)
    print("-" * 88)
    for r in results:
        print(
            f"{r['name']:<25} {r['difficulty']:<7} {r['outcome']:<9} "
            f"{r['score']:>6.3f} {r['ticks']:>5} {r['elapsed_s']:>6.1f}s "
            f"{r['sec_per_tick']:>6.2f} {r['parse_rate']:>6.1%} {r['parse_failures']:>4}"
        )
    print("-" * 88)
    scores = [r["score"] for r in results]
    passed = sum(1 for r in results if r["outcome"] == "victory")
    avg = sum(scores) / len(scores) if scores else 0.0
    total_parse = sum(r["parse_successes"] for r in results)
    total_fail = sum(r["parse_failures"] for r in results)
    total_calls = total_parse + total_fail
    overall_parse_rate = total_parse / total_calls if total_calls else 0.0
    total_time = sum(r["elapsed_s"] for r in results)
    print(
        f"Avg score: {avg:.3f} | Passed: {passed}/{len(results)} | "
        f"Parse rate: {overall_parse_rate:.1%} ({total_fail} failures) | "
        f"Total time: {total_time:.1f}s"
    )
    print("=" * 88)


def _build_provider(args: argparse.Namespace) -> tuple[BaseProvider, RLEConfig]:
    """Build LLM provider from CLI args. Returns (provider, config)."""
    if args.dry_run and not args.provider:
        return _make_mock_provider(), RLEConfig(tick_interval=0.0)

    overrides: dict[str, str] = {}
    if args.provider:
        overrides["provider"] = args.provider
    if args.model:
        overrides["model"] = args.model
    if args.base_url:
        overrides["provider_base_url"] = args.base_url
    config = RLEConfig(**overrides) if overrides else RLEConfig()
    return config.get_provider(), config


def _resolve_ticks(args: argparse.Namespace, use_mock_rimapi: bool) -> int | None:
    """Determine tick cap from CLI args."""
    if args.ticks:
        return args.ticks
    if use_mock_rimapi:
        return 10
    return None


async def main(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    helix = HelixConfig.default().to_geometry()
    scenarios = list_scenarios()
    provider, config = _build_provider(args)
    use_mock_rimapi = args.dry_run or args.provider is not None
    ticks_override = _resolve_ticks(args, use_mock_rimapi)

    output_dir = None
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Build provider kwargs (e.g. no-think for Qwen3.5)
    provider_kwargs: dict[str, Any] = {}
    if args.no_think:
        provider_kwargs["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": False},
        }

    results = []
    async with RimAPIClient(config.rimapi_url) as client:
        if use_mock_rimapi:
            client._client = httpx.AsyncClient(
                transport=_make_mock_transport(), base_url="http://mock",
            )

        for scenario in scenarios:
            print(f"\nRunning: {scenario.name} ({scenario.difficulty})...")
            result = await _run_scenario(
                scenario, config, client, provider, helix, output_dir,
                max_ticks_override=ticks_override,
                provider_kwargs=provider_kwargs or None,
                visualize=args.visualize,
                no_think=args.no_think,
            )
            results.append(result)
            print(
                f"  -> {result['outcome']} | score={result['score']:.3f} "
                f"| {result['ticks']} ticks | {result['elapsed_s']}s "
                f"| parse {result['parse_rate']:.0%} ({result['parse_failures']} fail)"
            )

    _print_leaderboard(results, model=args.model)

    if output_dir:
        summary = {
            "model": args.model or config.model,
            "provider": args.provider or config.provider,
            "base_url": args.base_url or None,
            "no_think": args.no_think,
            "ticks_per_scenario": ticks_override,
            "scenarios": results,
        }
        summary_path = output_dir / "benchmark_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))
        print(f"\nResults exported to {output_dir}/")
        print(f"Summary JSON: {summary_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all RLE benchmark scenarios")
    parser.add_argument("--output", help="Output directory for CSV results")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Use mock RIMAPI (combine with --provider for real LLM + fake game)",
    )
    parser.add_argument(
        "--provider", choices=["anthropic", "openai", "local"],
        help="LLM provider (default: from config)",
    )
    parser.add_argument("--model", help="Model name (e.g. qwen/qwen3.5-9b)")
    parser.add_argument("--base-url", help="Provider API base URL (e.g. http://localhost:1234/v1)")
    parser.add_argument("--ticks", type=int, help="Override max ticks per scenario")
    parser.add_argument("--no-think", action="store_true", help="Disable thinking mode (Qwen3.5)")
    parser.add_argument("--visualize", action="store_true", help="Show live helix visualization")
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    asyncio.run(main(parser.parse_args()))
