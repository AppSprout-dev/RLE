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
from rle.agents.map_analyst import MapAnalyst
from rle.agents.medical_officer import MedicalOfficer
from rle.agents.research_director import ResearchDirector
from rle.agents.resource_manager import ResourceManager
from rle.agents.social_overseer import SocialOverseer
from rle.config import RLEConfig, bridge_openrouter_key
from rle.orchestration.game_loop import RLEGameLoop
from rle.rimapi.client import RimAPIClient
from rle.scenarios.evaluator import ScenarioEvaluator
from rle.scenarios.loader import list_scenarios
from rle.scenarios.schema import ScenarioConfig
from rle.scoring.composite import CompositeScorer
from rle.scoring.delta import PairedResult
from rle.scoring.recorder import TimeSeriesRecorder
from rle.tracking.cost_tracker import CostTracker, create_cost_tracker
from rle.tracking.event_log import EventLog
from rle.tracking.hf_logger import HFLogger
from rle.tracking.history import append_history, get_run_dir, update_baseline
from rle.tracking.metadata import collect_metadata
from rle.tracking.wandb_logger import WandBLogger

logger = logging.getLogger(__name__)

# Seconds to wait after loading a save before starting a run.
GAME_LOAD_WAIT_SECONDS = 2

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
    "/api/v1/resources/summary?map_id=0": {
        "total_items": 800, "total_market_value": 8000.0,
        "critical_resources": {
            "food_summary": {"food_total": 85},
            "medicine_total": 5, "weapon_count": 2,
        },
    },
    "/api/v1/map/buildings?map_id=0": [
        {"id": "s_01", "def_name": "Wall", "position": {"x": 10, "y": 0, "z": 10},
         "hit_points": 300.0, "max_hit_points": 300.0},
    ],
    "/api/v1/research/summary": {
        "current_project": "electricity", "progress": 0.45,
        "completed": ["stonecutting"], "available": ["electricity", "battery", "smithing"],
    },
    "/api/v1/incidents?map_id=0": {"incidents": []},
    "/api/v1/game/state": {
        "name": "New Hope", "wealth": 8000.0, "day": 5, "tick": 300000,
        "population": 3, "mood_average": 0.65, "food_days": 7.0,
    },
    "/api/v1/map/weather?map_id=0": {
        "weather": "clear", "temperature": 22.0,
    },
    "/api/v1/map/zones?map_id=0": [],
    "/api/v1/map/rooms?map_id=0": [],
    "/api/v1/map/ore?map_id=0": [],
    "/api/v1/map/farm/summary?map_id=0": {
        "total_growing_zones": 0, "planted_cells": 0,
        "harvestable_cells": 0, "crops": {},
    },
    "/api/v1/map/terrain?map_id=0": {
        "width": 10, "height": 10,
        "palette": ["Soil", "WaterMovingShallow", "SoilRich", "Granite_Rough"],
        "grid": [100, 0],
        "floor_palette": [], "floor_grid": [100, 0],
    },
}


def _make_mock_transport() -> httpx.MockTransport:
    _POST_OK = httpx.Response(
        200, content=b'{"success": true, "errors": [], "warnings": []}',
        headers={"content-type": "application/json"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        # All POSTs succeed in mock mode (game control, actions, etc.)
        if request.method == "POST":
            return _POST_OK
        # GET routes matched by full path including query string
        raw = request.url.raw_path.decode()
        if raw in _MOCK_ROUTES:
            return httpx.Response(
                200, content=json.dumps(_MOCK_ROUTES[raw]).encode(),
                headers={"content-type": "application/json"},
            )
        # Also try without query string for routes stored that way
        path = raw.split("?")[0]
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


def _create_agents(  # type: ignore[no-untyped-def]
    provider, helix, *, provider_kwargs=None, no_think=False,
    exclude_agent: str | None = None,
):
    all_agents = [
        MapAnalyst("map_analyst", provider, helix, spawn_time=0.0, velocity=1.0),
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
    agents = [a for a in all_agents if a.agent_id != exclude_agent]
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
    parallel: bool = True,
    no_agent: bool = False,
    no_pause: bool = False,
    event_log: EventLog | None = None,
    cost_tracker: CostTracker | None = None,
    weave_module: object | None = None,
) -> dict:
    agents = _create_agents(provider, helix, provider_kwargs=provider_kwargs, no_think=no_think)
    if weave_module is not None:
        for agent in agents:
            agent.enable_weave(weave_module)
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
        parallel=parallel,
        no_agent=no_agent,
        no_pause=no_pause,
        event_log=event_log,
        cost_tracker=cost_tracker,
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
    bridge_openrouter_key(config)
    return config.get_provider(), config


def _resolve_ticks(args: argparse.Namespace, use_mock_rimapi: bool) -> int | None:
    """Determine tick cap from CLI args."""
    if args.ticks:
        return args.ticks
    if use_mock_rimapi:
        return 10
    return None


_ALL_AGENT_IDS = [
    "map_analyst", "resource_manager", "defense_commander",
    "research_director", "social_overseer", "construction_planner",
    "medical_officer",
]


async def _run_ablation(
    args: argparse.Namespace,
    config: RLEConfig,
    provider: object,
    helix: object,
    scenarios: list[ScenarioConfig],
    use_mock_rimapi: bool,
    num_runs: int,
    ticks_override: int | None,
    provider_kwargs: dict[str, Any] | None,
) -> None:
    """Run ablation study: full benchmark + 7 single-agent-removed benchmarks."""
    output_dir = Path(args.output) if args.output else get_run_dir(args.model)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with RimAPIClient(config.rimapi_url) as client:
        if use_mock_rimapi:
            client._client = httpx.AsyncClient(
                transport=_make_mock_transport(), base_url="http://mock",
            )

        # Pass 0: full benchmark (all agents)
        passes: list[tuple[str, list[dict[str, Any]]]] = []
        labels = ["all_agents", *_ALL_AGENT_IDS]

        for label in labels:
            exclude = label if label != "all_agents" else None
            tag = f"without_{label}" if exclude else "all_agents"
            print(f"\n{'=' * 60}")
            print(f"ABLATION PASS: {tag}")
            print(f"{'=' * 60}")

            pass_results: list[dict[str, Any]] = []
            for scenario in scenarios:
                for run_id in range(num_runs):
                    run_label = f" (run {run_id + 1}/{num_runs})" if num_runs > 1 else ""
                    if scenario.save_name and not use_mock_rimapi:
                        try:
                            await client.load_game(scenario.save_name)
                            await asyncio.sleep(GAME_LOAD_WAIT_SECONDS)
                        except Exception as e:
                            logger.warning("Could not load save %s: %s", scenario.save_name, e)

                    print(f"  {scenario.name}{run_label} ({tag})...")
                    agents = _create_agents(
                        provider, helix,
                        provider_kwargs=provider_kwargs,
                        no_think=args.no_think,
                        exclude_agent=exclude,
                    )
                    scorer = CompositeScorer(scenario.scoring_weights or None)
                    recorder = TimeSeriesRecorder()
                    evaluator = ScenarioEvaluator(scenario)
                    loop = RLEGameLoop(
                        config, client, agents,
                        expected_duration_days=scenario.expected_duration_days,
                        scorer=scorer, recorder=recorder, evaluator=evaluator,
                        initial_population=scenario.initial_population,
                        initial_wealth=8000.0,
                        parallel=not args.sequential,
                        no_pause=args.no_pause,
                    )
                    await loop.run(max_ticks=ticks_override or scenario.max_ticks)

                    final_score = 0.0
                    if recorder.snapshots:
                        final_score = scorer.final_score(recorder.snapshots).composite
                    pass_results.append({
                        "scenario": scenario.name,
                        "score": final_score,
                    })
                    print(f"    score={final_score:.3f}")

            passes.append((tag, pass_results))

    # Build ablation matrix
    full_scores: dict[str, list[float]] = {}
    for r in passes[0][1]:
        full_scores.setdefault(r["scenario"], []).append(r["score"])

    matrix: dict[str, dict[str, float]] = {}
    for tag, pass_results in passes[1:]:
        agent_name = tag.replace("without_", "")
        matrix[agent_name] = {}
        removed_scores: dict[str, list[float]] = {}
        for r in pass_results:
            removed_scores.setdefault(r["scenario"], []).append(r["score"])
        for scenario_name in full_scores:
            full_avg = sum(full_scores[scenario_name]) / len(full_scores[scenario_name])
            rem_avg = sum(removed_scores.get(scenario_name, [0.0])) / max(
                1, len(removed_scores.get(scenario_name, [])),
            )
            matrix[agent_name][scenario_name] = round(full_avg - rem_avg, 4)

    # Print ablation table
    scenario_names = list(full_scores.keys())
    print(f"\n{'=' * 88}")
    print("ABLATION MATRIX (score delta: positive = agent helps)")
    print(f"{'=' * 88}")
    header = f"{'Agent':<22}" + "".join(f"{s[:12]:>13}" for s in scenario_names) + f"{'Avg':>10}"
    print(header)
    print("-" * 88)
    for agent_name, deltas in matrix.items():
        vals = [deltas.get(s, 0.0) for s in scenario_names]
        avg_delta = sum(vals) / len(vals) if vals else 0.0
        row = f"{agent_name:<22}"
        for v in vals:
            sign = "+" if v >= 0 else ""
            row += f"{sign}{v:>12.4f}"
        row += f"{'+' if avg_delta >= 0 else ''}{avg_delta:>9.4f}"
        print(row)
    print(f"{'=' * 88}")

    # Save results
    ablation_data = {
        "num_runs": num_runs,
        "ticks_per_scenario": ticks_override,
        "passes": [{"label": t, "results": r} for t, r in passes],
        "matrix": matrix,
    }
    ablation_path = output_dir / "ablation_results.json"
    ablation_path.write_text(json.dumps(ablation_data, indent=2))
    print(f"\nAblation results saved to {ablation_path}")


async def main(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    helix = HelixConfig.default().to_geometry()
    scenarios = list_scenarios()
    provider, config = _build_provider(args)
    is_smoke_test = args.smoke_test or args.dry_run
    if args.dry_run:
        logger.warning("--dry-run is deprecated, use --smoke-test")
    if args.tick_interval is not None and not is_smoke_test:
        config = RLEConfig(**{**config.model_dump(), "tick_interval": args.tick_interval})
    use_mock_rimapi = (is_smoke_test or args.provider is not None) and not args.docker

    num_runs = getattr(args, "runs", 1) or 1

    if args.ablation:
        ticks_override = _resolve_ticks(args, use_mock_rimapi)
        provider_kwargs_abl: dict[str, Any] = {}
        if args.no_think:
            provider_kwargs_abl["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": False},
            }
        await _run_ablation(
            args, config, provider, helix, scenarios, use_mock_rimapi,
            num_runs, ticks_override, provider_kwargs_abl or None,
        )
        return

    # N >= 4 enforcement
    if args.push_hf and num_runs < 4:
        print("ERROR: Leaderboard submission requires --runs 4 or higher.")
        return
    if num_runs < 4 and not use_mock_rimapi:
        print(f"WARNING: N={num_runs} runs is below minimum (4) for statistical validity.")
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

    # Initialize W&B logger (no-op if --wandb not passed or wandb not installed)
    wandb_logger = WandBLogger(
        enabled=args.wandb,
        run_name=f"{args.model or config.model}_{ticks_override or 'full'}ticks",
    )
    if wandb_logger.enabled:
        wandb_logger.log_config({
            **collect_metadata(),
            "model": args.model or config.model,
            "provider": args.provider or config.provider,
            "no_think": args.no_think,
            "parallel": not args.sequential,
            "ticks_per_scenario": ticks_override,
        })

    # Initialize cost tracker (fetches OpenRouter pricing)
    cost_tracker = await create_cost_tracker(args.model or config.model)

    # Initialize event log
    event_log: EventLog | None = None
    if args.output:
        event_log = EventLog(Path(args.output) / "events.jsonl")

    no_baseline = getattr(args, "no_baseline", False)
    is_paired = not use_mock_rimapi and not no_baseline

    results = []
    paired_results: list[PairedResult] = []

    # Docker lifecycle (optional)
    docker_server = None
    if args.docker:
        from rle.docker import DockerGameServer
        docker_server = DockerGameServer(
            image=config.docker_image, port=config.docker_port,
        )
        await docker_server.start()
        config = RLEConfig(**{
            **config.model_dump(),
            "rimapi_url": docker_server.url,
        })

    try:
        async with RimAPIClient(config.rimapi_url) as client:
            if use_mock_rimapi:
                client._client = httpx.AsyncClient(
                    transport=_make_mock_transport(), base_url="http://mock",
                )

            for scenario in scenarios:
                if docker_server:
                    await docker_server.restart()
                paired = PairedResult(scenario=scenario.name) if is_paired else None

                for run_id in range(num_runs):
                    run_label = f" (run {run_id + 1}/{num_runs})" if num_runs > 1 else ""

                    # Load save if available (for reproducible initial conditions)
                    if scenario.save_name and not use_mock_rimapi:
                        try:
                            await client.load_game(scenario.save_name)
                            await asyncio.sleep(GAME_LOAD_WAIT_SECONDS)
                        except Exception as e:
                            logger.warning("Could not load save %s: %s", scenario.save_name, e)

                    # Agent run
                    print(f"\nRunning: {scenario.name} ({scenario.difficulty}){run_label}...")
                    result = await _run_scenario(
                        scenario, config, client, provider, helix, output_dir,
                        max_ticks_override=ticks_override,
                        provider_kwargs=provider_kwargs or None,
                        visualize=args.visualize,
                        no_think=args.no_think,
                        parallel=not args.sequential,
                        no_pause=args.no_pause,
                        event_log=event_log,
                        cost_tracker=cost_tracker,
                        weave_module=wandb_logger.weave,
                    )
                    results.append(result)
                    if paired:
                        paired.agent_scores.append(result["score"])
                    print(
                        f"  -> agent: {result['outcome']} | score={result['score']:.3f} "
                        f"| {result['ticks']} ticks | {result['elapsed_s']}s "
                        f"| parse {result['parse_rate']:.0%} ({result['parse_failures']} fail)"
                    )

                    # Baseline run (reload same save, no agents)
                    if is_paired:
                        if scenario.save_name:
                            try:
                                await client.load_game(scenario.save_name)
                                await asyncio.sleep(GAME_LOAD_WAIT_SECONDS)
                            except Exception as e:
                                logger.warning("Could not reload save: %s", e)

                        print(f"  baseline{run_label}...")
                        baseline = await _run_scenario(
                            scenario, config, client, provider, helix, output_dir,
                            max_ticks_override=ticks_override,
                            no_agent=True,
                        )
                        paired.baseline_scores.append(baseline["score"])
                        print(f"  -> baseline: score={baseline['score']:.3f}")

                if paired:
                    paired_results.append(paired)

        # Print results
        if is_paired and paired_results:
            from rle.scoring.delta import print_paired_leaderboard
            print_paired_leaderboard(paired_results, model=args.model, num_runs=num_runs)
        else:
            _print_leaderboard(results, model=args.model)

        # Build enriched summary with metadata
        metadata = collect_metadata()
        summary: dict[str, Any] = {
            **metadata,
            "model": args.model or config.model,
            "provider": args.provider or config.provider,
            "base_url": args.base_url or None,
            "no_think": args.no_think,
            "parallel": not args.sequential,
            "tick_interval": config.tick_interval,
            "ticks_per_scenario": ticks_override,
            "num_runs": num_runs,
            "paired": is_paired,
            "scenarios": results,
            "cost_snapshot": cost_tracker.snapshot().model_dump(),
        }
        if event_log:
            summary["event_summary"] = event_log.summary().model_dump()
        if is_paired and paired_results:
            summary["paired_results"] = [p.to_dict() for p in paired_results]

        # Auto-generate run directory if --output not specified
        output_dir = Path(args.output) if args.output else get_run_dir(args.model)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "benchmark_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, default=str))
        print(f"\nResults exported to {output_dir}/")

        # Only track real benchmark runs (not mock/dry-run JSON compliance tests)
        scores = [r.get("score", 0) for r in results]
        avg = sum(scores) / len(scores) if scores else 0
        if not use_mock_rimapi:
            history_path = append_history(summary)
            print(f"History appended to {history_path}")

            is_new_best, prev_score = update_baseline(summary)
            if is_new_best:
                delta = f"+{avg - prev_score:.3f}" if prev_score else "first run"
                print(f"NEW BASELINE: {avg:.3f} ({delta})")
            elif prev_score is not None:
                print(f"Baseline: {prev_score:.3f} (this run: {avg:.3f})")
        else:
            print("(dry-run: skipping history/baseline tracking)")

        # W&B logging (optional)
        if wandb_logger.enabled:
            wandb_logger.log_final_summary(
                avg_score=avg,
                parse_rate=sum(r.get("parse_successes", 0) for r in results)
                / max(1, sum(r["parse_successes"] + r["parse_failures"] for r in results)),
                total_time=sum(r.get("elapsed_s", 0) for r in results),
            )
            for r in results:
                wandb_logger.log_scenario_result(r)
            wandb_logger.finish()
            print("W&B run logged")

        # HuggingFace Hub push (optional)
        if args.push_hf:
            hf = HFLogger(enabled=True)
            if hf.enabled:
                hf.push_results(
                    history_path=history_path,
                    baselines_dir=Path("results/baselines"),
                    run_dir=output_dir,
                )
                print("Results pushed to HuggingFace Hub")

    finally:
        if event_log:
            event_log.close()
        if docker_server:
            await docker_server.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all RLE benchmark scenarios")
    parser.add_argument("--output", help="Output directory for CSV results")
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Use mock RIMAPI (combine with --provider for real LLM + fake game)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="(Deprecated, use --smoke-test) Use mock RIMAPI",
    )
    parser.add_argument(
        "--docker", action="store_true",
        help="Use Docker container for headless RimWorld (requires docker/Dockerfile built)",
    )
    parser.add_argument(
        "--ablation", action="store_true",
        help="(WIP) Run ablation study: full benchmark + 7 single-agent-removed runs",
    )
    parser.add_argument(
        "--provider", choices=["anthropic", "openai", "local"],
        help="LLM provider (default: from config)",
    )
    parser.add_argument("--model", help="Model name (e.g. qwen/qwen3.5-9b)")
    parser.add_argument("--base-url", help="Provider API base URL (e.g. http://localhost:1234/v1)")
    parser.add_argument("--ticks", type=int, help="Override max ticks per scenario")
    parser.add_argument(
        "--tick-interval", type=float,
        help="Seconds between ticks (default: 1.0, use 30-60 for live game)",
    )
    parser.add_argument("--no-think", action="store_true", help="Disable thinking mode (Qwen3.5)")
    parser.add_argument("--visualize", action="store_true", help="Show live helix visualization")
    parser.add_argument(
        "--sequential", action="store_true",
        help="Run agents sequentially (default: parallel)",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of paired runs per scenario (default: 1, use 4+ for statistical rigor)",
    )
    parser.add_argument(
        "--no-baseline", action="store_true",
        help="Skip baseline (no-agent) runs — agent-only, no paired comparison",
    )
    parser.add_argument(
        "--no-pause", action="store_true",
        help="Don't pause game during deliberation (SSE-driven)",
    )
    parser.add_argument("--wandb", action="store_true", help="Log to Weights & Biases")
    parser.add_argument("--push-hf", action="store_true", help="Push results to HuggingFace Hub")
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    asyncio.run(main(parser.parse_args()))
