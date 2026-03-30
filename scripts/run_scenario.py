"""CLI entry point: run a single RLE scenario with scoring and evaluation."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from felix_agent_sdk.core import HelixConfig
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
from rle.rimapi.sse_client import RimAPISSEClient
from rle.scenarios.evaluator import ScenarioEvaluator
from rle.scenarios.loader import list_scenarios, load_scenario
from rle.scoring.composite import CompositeScorer
from rle.scoring.recorder import TimeSeriesRecorder

DEFINITIONS_DIR = Path(__file__).parent.parent / "src" / "rle" / "scenarios" / "definitions"


def _find_scenario(query: str) -> Path:
    """Find a scenario YAML by name prefix or number."""
    for path in sorted(DEFINITIONS_DIR.glob("*.yaml")):
        if path.stem.startswith(query) or query in path.stem:
            return path
    raise SystemExit(f"Scenario not found: {query}")


def _create_agents(provider, helix):  # type: ignore[no-untyped-def]
    """Create all 6 role agents."""
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


def _print_results(loop: RLEGameLoop, recorder: TimeSeriesRecorder) -> None:
    """Print final score summary."""
    if not recorder.snapshots:
        print("No scores recorded.")
        return

    last = recorder.snapshots[-1]
    print("\n--- Final Score ---")
    for name, value in sorted(last.metrics.items()):
        bar = "#" * int(value * 20)
        print(f"  {name:20s} {value:.3f} |{bar}")
    print(f"  {'COMPOSITE':20s} {last.composite:.3f}")

    if loop.evaluation_result:
        er = loop.evaluation_result
        print(f"\nOutcome: {er.outcome.upper()} ({er.reason})")
        print(f"Day {er.day}, tick {er.tick}")


async def main(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # List mode
    if args.list:
        scenarios = list_scenarios(DEFINITIONS_DIR)
        print(f"{'#':<4} {'Name':<25} {'Difficulty':<10} {'Days':<6} {'Ticks'}")
        for i, s in enumerate(scenarios, 1):
            ticks = s.max_ticks or "∞"
            print(f"{i:<4} {s.name:<25} {s.difficulty:<10} {s.expected_duration_days:<6} {ticks}")
        return

    if not args.scenario:
        print("Usage: run_scenario.py <scenario_name> [options]")
        print("       run_scenario.py --list")
        sys.exit(1)

    # Load scenario
    scenario_path = _find_scenario(args.scenario)
    scenario = load_scenario(scenario_path)
    print(f"Scenario: {scenario.name} ({scenario.difficulty})")
    print(f"Duration: {scenario.expected_duration_days} days, max {scenario.max_ticks} ticks")

    # Setup
    overrides: dict[str, str] = {}
    if args.provider:
        overrides["provider"] = args.provider
    if args.model:
        overrides["model"] = args.model
    if args.base_url:
        overrides["provider_base_url"] = args.base_url
    if args.tick_interval is not None:
        overrides["tick_interval"] = str(args.tick_interval)
    config = RLEConfig(**overrides) if overrides else RLEConfig()
    provider = config.get_provider()
    helix = HelixConfig.default().to_geometry()
    agents = _create_agents(provider, helix)
    if args.no_think:
        for agent in agents:
            agent.set_no_think(True)

    scorer = CompositeScorer(scenario.scoring_weights or None)
    recorder = TimeSeriesRecorder()
    evaluator = ScenarioEvaluator(scenario)

    visualizer = None
    if args.visualize:
        visualizer = HelixVisualizer(helix, title="R L E")
        for agent in agents:
            display = AGENT_DISPLAY[agent.agent_id]
            visualizer.register_agent(
                agent.agent_id, label=display["label"], color=display["color"],
            )

    max_ticks = args.ticks or scenario.max_ticks

    # SSE listener for real-time events (optional, only when RIMAPI is live)
    sse = RimAPISSEClient(config.rimapi_url)
    sse_task = asyncio.create_task(sse.listen())

    async with RimAPIClient(config.rimapi_url) as client:
        loop = RLEGameLoop(
            config, client, agents,
            expected_duration_days=scenario.expected_duration_days,
            scorer=scorer,
            recorder=recorder,
            evaluator=evaluator,
            initial_population=scenario.initial_population,
            visualizer=visualizer,
            parallel=not args.sequential,
            sse_client=sse,
            dashboard_export_dir=Path(args.output) if args.output else None,
            no_agent=args.no_agent,
            no_pause=args.no_pause,
        )
        try:
            if visualizer:
                with visualizer.live():
                    await loop.run(max_ticks=max_ticks)
            else:
                await loop.run(max_ticks=max_ticks)
        finally:
            sse.stop()
            sse_task.cancel()

    # Output
    _print_results(loop, recorder)

    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{scenario_path.stem}.csv"
        recorder.to_csv(csv_path)
        print(f"\nCSV exported to {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an RLE scenario")
    parser.add_argument("scenario", nargs="?", help="Scenario name or number prefix")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument(
        "--provider", choices=["anthropic", "openai", "local"],
        help="LLM provider (default: from config)",
    )
    parser.add_argument("--model", help="Model name (e.g. unsloth/nvidia-nemotron-3-nano-4b)")
    parser.add_argument("--base-url", help="Provider API base URL")
    parser.add_argument("--ticks", type=int, help="Override max ticks")
    parser.add_argument(
        "--tick-interval", type=float,
        help="Seconds between ticks (default: 1.0, use 30-60 for live game)",
    )
    parser.add_argument("--output", help="Output directory for CSV results")
    parser.add_argument("--visualize", action="store_true", help="Show live helix visualization")
    parser.add_argument(
        "--sequential", action="store_true",
        help="Run agents sequentially (default: parallel)",
    )
    parser.add_argument("--no-think", action="store_true", help="Skip reasoning tokens")
    parser.add_argument(
        "--no-agent", action="store_true",
        help="Baseline mode: no agent deliberation, colony runs unmanaged",
    )
    parser.add_argument(
        "--no-pause", action="store_true",
        help="Don't pause game during deliberation (SSE-driven, game runs continuously)",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    asyncio.run(main(parser.parse_args()))
