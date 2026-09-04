"""CLI entry point: run a single RLE scenario with scoring and evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from pathlib import Path

from rle.config import RLEConfig
from rle.harness import (
    HarnessContext,
    HarnessNotFoundError,
    HarnessOptionsError,
    HarnessUnavailableError,
    add_harness_args,
    create_harness,
    exit_with_harness_error,
    harness_options_for,
    maybe_handle_harness_list,
    selected_harnesses,
)
from rle.orchestration.camera_director import CameraDirector
from rle.orchestration.game_loop import RLEGameLoop
from rle.orchestration.save_loader import load_save_and_settle
from rle.rimapi.client import RimAPIClient
from rle.rimapi.sse_client import RimAPISSEClient
from rle.scenarios.evaluator import ScenarioEvaluator
from rle.scenarios.loader import list_scenarios, load_scenario
from rle.scoring.composite import CompositeScorer
from rle.scoring.recorder import TimeSeriesRecorder
from rle.tracking.cost_tracker import create_cost_tracker, fetch_billed_costs
from rle.tracking.event_log import EventLog
from rle.tracking.history import append_history
from rle.tracking.metadata import collect_metadata

DEFINITIONS_DIR = Path(__file__).parent.parent / "src" / "rle" / "scenarios" / "definitions"

# Runaway guard for --until-death runs (the evaluator's terminal conditions
# are the intended stop; this only catches a colony that never dies or wins).
_UNTIL_DEATH_SAFETY_CAP = 5000


def _find_scenario(query: str) -> Path:
    """Find a scenario YAML by name prefix or number."""
    for path in sorted(DEFINITIONS_DIR.glob("*.yaml")):
        if path.stem.startswith(query) or query in path.stem:
            return path
    raise SystemExit(f"Scenario not found: {query}")


def _per_mtok_to_per_token(price_per_mtok: float | None) -> float | None:
    """Convert a CLI override in USD per million tokens to per-token."""
    return None if price_per_mtok is None else price_per_mtok / 1_000_000


def _write_deliberations_jsonl(
    path: Path, deliberations: list[dict[str, object]],
) -> None:
    """Write per-tick deliberation records to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for entry in deliberations:
            f.write(json.dumps(entry) + "\n")


def _build_run_summary(  # noqa: PLR0913
    args: argparse.Namespace,
    config: RLEConfig,
    harness_name: str,
    harness_options: dict[str, object],
    harness_describe: dict[str, str],
    scenario_name: str,
    scenario_save_name: str,
    max_ticks: int | None,
    outcome: str,
    final_score: float | None,
    ticks_run: int,
    mean_step_latency_s: float | None,
    cost_snapshot_dict: dict[str, object],
    event_summary_dict: dict[str, object] | None,
    billed_cost_dict: dict[str, object] | None = None,
) -> dict[str, object]:
    """Compose the per-scenario summary JSON (metadata + config + result)."""
    summary: dict[str, object] = {
        **collect_metadata(random_seed=args.seed, harness_describe=harness_describe),
        "scenario": scenario_name,
        "scenario_save_name": scenario_save_name,
        "harness": harness_name,
        "harness_options": harness_options,
        "model": config.model,
        "provider": config.provider,
        "base_url": config.provider_base_url,
        "no_pause": args.no_pause,
        "tick_interval": config.tick_interval,
        "max_ticks": max_ticks,
        "outcome": outcome,
        "final_score": final_score,
        "ticks_run": ticks_run,
        "mean_step_latency_s": mean_step_latency_s,
        "cost_snapshot": cost_snapshot_dict,
    }
    if billed_cost_dict is not None:
        summary["billed_cost"] = billed_cost_dict
    if event_summary_dict is not None:
        summary["event_summary"] = event_summary_dict
    return summary


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

    if maybe_handle_harness_list(args):
        return

    # Seed RLE-side stochasticity (resolver tiebreaks, json_repair fallbacks).
    # RimWorld's RNG is unaffected — see metadata.collect_metadata docstring.
    if args.seed is not None:
        random.seed(args.seed)

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
    overrides: dict[str, object] = {}
    if args.provider:
        overrides["provider"] = args.provider
    if args.model:
        overrides["model"] = args.model
    if args.base_url:
        overrides["provider_base_url"] = args.base_url
    if args.tick_interval is not None:
        overrides["tick_interval"] = args.tick_interval
    if args.tick_timeout is not None:
        overrides["tick_timeout_s"] = args.tick_timeout
    config = RLEConfig(**overrides) if overrides else RLEConfig()  # type: ignore[arg-type]

    harness_name = selected_harnesses(args, config)[0]
    harness_options = harness_options_for(harness_name, args, config)
    print(f"Harness: {harness_name} {harness_options or ''}".rstrip())

    scorer = CompositeScorer(scenario.scoring_weights or None)
    recorder = TimeSeriesRecorder()
    evaluator = ScenarioEvaluator(scenario)

    if args.until_death:
        # Natural-conclusion mode (Phase B): no scenario tick cap — the run
        # ends when the evaluator hits a terminal condition (all colonists
        # dead, or victory). The safety cap only guards against a runaway
        # loop if the colony somehow never reaches either.
        scenario = scenario.model_copy(update={"max_ticks": None})
        max_ticks = args.ticks or _UNTIL_DEATH_SAFETY_CAP
    else:
        max_ticks = args.ticks or scenario.max_ticks

    # Initialize tracking (optional, when --output is specified)
    event_log: EventLog | None = None
    if args.output:
        Path(args.output).mkdir(parents=True, exist_ok=True)
        event_log = EventLog(Path(args.output) / "events.jsonl")
    cost_tracker = await create_cost_tracker(
        config.model,
        prompt_price_override=_per_mtok_to_per_token(args.prompt_price_per_mtok),
        completion_price_override=_per_mtok_to_per_token(args.completion_price_per_mtok),
    )

    # SSE listener for real-time events (optional, only when RIMAPI is live)
    sse = RimAPISSEClient(config.rimapi_url)
    sse_task = asyncio.create_task(sse.listen())

    async with RimAPIClient(config.rimapi_url) as client:
        # Load the scenario's save file for a consistent starting state
        if scenario.save_name:
            print(f"Loading save: {scenario.save_name}")
            try:
                unforbid_count = await load_save_and_settle(
                    client, config.rimapi_url, scenario.save_name,
                )
                if unforbid_count:
                    print(f"Unforbid {unforbid_count} items.")
                print("Save loaded, game ready.")
            except Exception as e:
                print(f"Warning: Could not load save '{scenario.save_name}': {e}")
                print("Continuing with current game state...")

        # Execute pre-game setup commands (spawn items, pawns, etc.)
        for cmd in scenario.setup_commands:
            try:
                if cmd.type == "spawn_pawn":
                    await client.spawn_pawn(**cmd.params)
                elif cmd.type == "spawn_item":
                    await client.spawn_item(**cmd.params)
                elif cmd.type == "drop_pod":
                    await client.send_drop_pod(**cmd.params)
                elif cmd.type == "change_weather":
                    await client.change_weather(**cmd.params)
                else:
                    print(f"Unknown setup command: {cmd.type}")
            except Exception as e:
                print(f"Setup command {cmd.type} failed: {e}")

        camera_director = None
        if args.camera_director:
            camera_director = CameraDirector(
                client,
                output_dir=Path(args.output) if args.output else None,
            )

        harness_ctx = HarnessContext(
            config=config,
            client=client,
            expected_duration_days=scenario.expected_duration_days,
            initial_population=scenario.initial_population,
            scenario=scenario,
            event_log=event_log,
            cost_tracker=cost_tracker,
            tick_timeout_s=config.tick_timeout_s,
        )
        try:
            harness = create_harness(harness_name, harness_ctx, harness_options)
        except (HarnessNotFoundError, HarnessUnavailableError, HarnessOptionsError) as exc:
            sse.stop()
            sse_task.cancel()
            exit_with_harness_error(exc)
            return

        loop = RLEGameLoop(
            config, client,
            expected_duration_days=scenario.expected_duration_days,
            scorer=scorer,
            recorder=recorder,
            evaluator=evaluator,
            initial_population=scenario.initial_population,
            sse_client=sse,
            dashboard_export_dir=Path(args.output) if args.output else None,
            no_pause=args.no_pause,
            event_log=event_log,
            cost_tracker=cost_tracker,
            triggered_incidents=scenario.triggered_incidents,
            auto_dismiss_dialogs=not args.no_dismiss_dialogs,
            camera_director=camera_director,
            harness=harness,
            harness_context=harness_ctx,
            scenario=scenario,
        )
        try:
            await loop.run(max_ticks=max_ticks)
        finally:
            sse.stop()
            sse_task.cancel()

    # Output
    _print_results(loop, recorder)

    # Reconcile estimates against OpenRouter's billed ground truth — the
    # token-count estimator diverged up to 4x in both directions on the
    # v0.3.0 spread (thinking-model usage shapes, caching discounts).
    billed_report = None
    effective_base_url = config.provider_base_url or ""
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    generation_ids = cost_tracker.generation_ids
    if "openrouter.ai" in effective_base_url and openai_key and generation_ids:
        print(
            f"\nReconciling billed cost for {len(generation_ids)} generations "
            "against OpenRouter...",
        )
        billed_report = await fetch_billed_costs(generation_ids, openai_key)

    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{scenario_path.stem}.csv"
        recorder.to_csv(csv_path)
        print(f"\nCSV exported to {csv_path}")

        deliberation_log = loop.deliberation_log
        if deliberation_log:
            log_path = output_dir / f"{scenario_path.stem}_deliberations.jsonl"
            await asyncio.to_thread(_write_deliberations_jsonl, log_path, deliberation_log)
            print(f"Deliberations exported to {log_path}")

        latencies = [t.step_latency_s for t in loop.tick_results]
        # Replay-grade scenario summary with full metadata + cost + score.
        summary = _build_run_summary(
            args=args,
            config=config,
            harness_name=harness.name,
            harness_options=harness_options,
            harness_describe=harness.describe(),
            scenario_name=scenario.name,
            scenario_save_name=scenario.save_name,
            max_ticks=max_ticks,
            outcome=(
                loop.evaluation_result.outcome
                if loop.evaluation_result else "timeout"
            ),
            final_score=(
                recorder.snapshots[-1].composite if recorder.snapshots else None
            ),
            ticks_run=len(loop.tick_results),
            mean_step_latency_s=(
                round(sum(latencies) / len(latencies), 3) if latencies else None
            ),
            cost_snapshot_dict=cost_tracker.snapshot().model_dump(),
            event_summary_dict=(
                event_log.summary().model_dump() if event_log else None
            ),
            billed_cost_dict=(
                billed_report.model_dump() if billed_report else None
            ),
        )
        summary_path = output_dir / f"{scenario_path.stem}_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, default=str))
        print(f"Summary exported to {summary_path}")

        # Append to results/benchmark_history.jsonl so this run is replayable
        # alongside benchmark-suite runs. The leaderboard can filter on
        # run_type to keep single-scenario runs out of multi-scenario rollups.
        # Skip when no real LLM was called (smoke tests / pre-flight checks).
        if cost_tracker.snapshot().num_calls > 0:
            history_entry = {
                **summary,
                "run_type": "scenario",
                "scenarios": [{
                    "name": scenario.name,
                    "difficulty": scenario.difficulty,
                    "score": summary["final_score"],
                    "outcome": summary["outcome"],
                    "ticks": summary["ticks_run"],
                }],
            }
            history_path = append_history(history_entry)
            print(f"History appended to {history_path}")

    # Print cost summary
    snap = cost_tracker.snapshot()
    if snap.num_calls > 0:
        print(
            f"\nTokens: {snap.total_tokens} ({snap.num_calls} calls) "
            f"| Est. cost: ${snap.estimated_cost_usd:.4f} "
            f"| Wall time: {snap.wall_time_s:.1f}s",
        )
    if billed_report:
        unbilled = (
            f" ({billed_report.missing_generations} unbilled — lower bound)"
            if billed_report.missing_generations else ""
        )
        print(
            f"Billed cost (OpenRouter ground truth): "
            f"${billed_report.billed_cost_usd:.4f} over "
            f"{billed_report.billed_generations} generations{unbilled}",
        )

    if event_log:
        event_log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an RLE scenario")
    parser.add_argument("scenario", nargs="?", help="Scenario name or number prefix")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument(
        "--provider",
        help="LLM provider name passed to the harness (felix: anthropic|openai|local|claude-code)",
    )
    parser.add_argument("--model", help="Model name (e.g. unsloth/nvidia-nemotron-3-nano-4b)")
    parser.add_argument("--base-url", help="Provider API base URL")
    add_harness_args(parser)
    parser.add_argument("--ticks", type=int, help="Override max ticks")
    parser.add_argument(
        "--tick-interval", type=float,
        help="Seconds between ticks (default: 1.0, use 30-60 for live game)",
    )
    parser.add_argument(
        "--tick-timeout", type=float, default=None,
        help="Loop-level cap in seconds on a whole harness step (default: none).",
    )
    parser.add_argument("--output", help="Output directory for CSV results")
    parser.add_argument(
        "--until-death", action="store_true",
        help="Ignore the scenario tick cap; run until the evaluator reaches "
             "a terminal condition (all colonists dead, or victory). "
             "Phase B natural-conclusion mode.",
    )
    parser.add_argument(
        "--no-pause", action="store_true",
        help="Don't pause game during deliberation (SSE-driven, game runs continuously)",
    )
    parser.add_argument(
        "--camera-director", action="store_true",
        help="Drive the game camera to the action each tick for cinematic "
             "capture (writes camera_cues.jsonl to --output). Issue #34.",
    )
    parser.add_argument(
        "--no-dismiss-dialogs", action="store_true",
        help="Don't auto-dismiss force-pause popups (colony-name dialog, debug "
             "log). Dismissal is on by default for unattended runs. Issue #33.",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help=(
            "Seed for RLE-side stochasticity (resolver tiebreaks, json_repair "
            "fallbacks). Does NOT control RimWorld's RNG. Recorded in the run "
            "summary for replay."
        ),
    )
    parser.add_argument(
        "--prompt-price-per-mtok", type=float, default=None,
        help=(
            "Override prompt token price in USD per million tokens. Use this "
            "when the OpenRouter /models price diverges from your actual "
            "billed cost (e.g. BYOK markup or provider routing surcharges)."
        ),
    )
    parser.add_argument(
        "--completion-price-per-mtok", type=float, default=None,
        help="Override completion token price (USD per million tokens).",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    asyncio.run(main(parser.parse_args()))
