"""CLI: run all RLE scenarios for one or more harnesses and output a leaderboard."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

from rle.config import RLEConfig
from rle.docker import DockerGameServer
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
from rle.orchestration.game_loop import RLEGameLoop
from rle.orchestration.save_loader import load_save_and_settle
from rle.rimapi.client import RimAPIClient
from rle.scenarios.evaluator import ScenarioEvaluator
from rle.scenarios.loader import list_scenarios
from rle.scenarios.schema import ScenarioConfig
from rle.scoring.composite import CompositeScorer
from rle.scoring.delta import PairedResult, print_paired_leaderboard
from rle.scoring.recorder import TimeSeriesRecorder
from rle.testing.mock_rimapi import MockRimAPI
from rle.tracking.cost_tracker import CostTracker, create_cost_tracker, fetch_billed_costs
from rle.tracking.event_log import EventLog
from rle.tracking.hf_logger import HFLogger
from rle.tracking.history import append_history, get_run_dir, update_baseline
from rle.tracking.metadata import collect_metadata
from rle.tracking.wandb_logger import WandBLogger

logger = logging.getLogger(__name__)

# Felix roster ids, for --ablation (which is a Felix-only experiment).
_ALL_AGENT_IDS = [
    "map_analyst", "resource_manager", "defense_commander",
    "research_director", "social_overseer", "construction_planner",
    "medical_officer",
]

# Markers in per-tick action errors that indicate the *harness/RIMAPI plumbing*
# failed rather than the model deciding badly (issue #27, #33, CLAUDE.md
# "null-ref cascades"). A run that trips one is quarantined from leaderboard
# means by default (see analyze_spread.py for the post-hoc taxonomy).
HARNESS_FAILURE_MARKERS = (
    "Object reference not set",
    "NullReferenceException",
    "Invalid plant definition",
)


class RunError(RuntimeError):
    """A harness could not be constructed for this run."""


async def _load_save(client: RimAPIClient, config: RLEConfig, scenario: ScenarioConfig) -> bool:
    """Load + settle the scenario save. Returns False when the run must be skipped."""
    if not scenario.save_name:
        return True
    try:
        await load_save_and_settle(client, config.rimapi_url, scenario.save_name)
    except Exception as e:
        logger.warning("Could not load save %s: %s", scenario.save_name, e)
        return False
    return True


def _harness_failed(event_log: EventLog | None, start_index: int) -> bool:
    """True when any action error since ``start_index`` matches a plumbing marker."""
    if event_log is None:
        return False
    for event in event_log.events[start_index:]:
        err = event.data.get("error") or event.data.get("reason")
        if isinstance(err, str) and any(m in err for m in HARNESS_FAILURE_MARKERS):
            return True
    return False


async def _run_scenario(  # noqa: PLR0913
    scenario: ScenarioConfig,
    config: RLEConfig,
    client: RimAPIClient,
    harness_name: str,
    harness_options: dict[str, Any],
    output_dir: Path | None,
    *,
    max_ticks_override: int | None = None,
    smoke: bool = False,
    no_pause: bool = False,
    event_log: EventLog | None = None,
    cost_tracker: CostTracker | None = None,
    weave_module: object | None = None,
) -> dict[str, Any]:
    ctx = HarnessContext(
        config=config,
        client=client,
        expected_duration_days=scenario.expected_duration_days,
        initial_population=scenario.initial_population,
        scenario=scenario,
        event_log=event_log,
        cost_tracker=cost_tracker,
        tick_timeout_s=config.tick_timeout_s,
        smoke=smoke,
    )
    if weave_module is not None:
        ctx.extras["weave_module"] = weave_module
    try:
        harness = create_harness(harness_name, ctx, harness_options, smoke=smoke)
    except (HarnessNotFoundError, HarnessUnavailableError, HarnessOptionsError) as exc:
        raise RunError(str(exc)) from exc

    scorer = CompositeScorer(scenario.scoring_weights or None)
    recorder = TimeSeriesRecorder()
    evaluator = ScenarioEvaluator(scenario)
    events_before = len(event_log.events) if event_log else 0

    loop = RLEGameLoop(
        config, client,
        expected_duration_days=scenario.expected_duration_days,
        scorer=scorer,
        recorder=recorder,
        evaluator=evaluator,
        initial_population=scenario.initial_population,
        initial_wealth=8000.0,
        no_pause=no_pause,
        event_log=event_log,
        cost_tracker=cost_tracker,
        harness=harness,
        harness_context=ctx,
        scenario=scenario,
    )
    max_ticks = max_ticks_override or scenario.max_ticks
    t0 = time.monotonic()
    await loop.run(max_ticks=max_ticks)
    elapsed = time.monotonic() - t0

    final_score = 0.0
    if recorder.snapshots:
        final_score = scorer.final_score(recorder.snapshots).composite

    outcome = "timeout"
    if loop.evaluation_result:
        outcome = loop.evaluation_result.outcome

    ticks_run = len(loop.tick_results)
    total_calls = loop.parse_successes + loop.parse_failures
    parse_rate = loop.parse_successes / total_calls if total_calls else 0.0
    latencies = [t.step_latency_s for t in loop.tick_results]

    slug = scenario.name.lower().replace(" ", "_")
    if output_dir and recorder.snapshots:
        recorder.to_csv(output_dir / f"{harness.name}_{slug}.csv")

    deliberation_log = loop.deliberation_log
    if output_dir and deliberation_log:
        with open(output_dir / f"{harness.name}_{slug}_deliberations.jsonl", "w") as f:
            for entry in deliberation_log:
                f.write(json.dumps(entry) + "\n")

    return {
        "name": scenario.name,
        "difficulty": scenario.difficulty,
        "harness": harness.name,
        "harness_versions": harness.describe(),
        "outcome": outcome,
        "score": final_score,
        "ticks": ticks_run,
        "elapsed_s": round(elapsed, 2),
        "sec_per_tick": round(elapsed / ticks_run, 2) if ticks_run else 0.0,
        "mean_step_latency_s": (
            round(sum(latencies) / len(latencies), 3) if latencies else 0.0
        ),
        "parse_successes": loop.parse_successes,
        "parse_failures": loop.parse_failures,
        "parse_rate": round(parse_rate, 3),
        "harness_failed": _harness_failed(event_log, events_before),
    }


def _print_leaderboard(results: list[dict[str, Any]], model: str | None = None) -> None:
    print("\n" + "=" * 100)
    title = f"RLE BENCHMARK — {model}" if model else "RLE BENCHMARK LEADERBOARD"
    print(title)
    print("=" * 100)
    header = (
        f"{'Harness':<12} {'Scenario':<22} {'Diff':<7} {'Outcome':<9} "
        f"{'Score':>6} {'Ticks':>5} {'Time':>7} {'s/step':>6} "
        f"{'Parse%':>7} {'Fail':>4} {'HF':>3}"
    )
    print(header)
    print("-" * 100)
    for r in results:
        print(
            f"{r['harness']:<12} {r['name']:<22} {r['difficulty']:<7} {r['outcome']:<9} "
            f"{r['score']:>6.3f} {r['ticks']:>5} {r['elapsed_s']:>6.1f}s "
            f"{r['mean_step_latency_s']:>6.2f} {r['parse_rate']:>6.1%} "
            f"{r['parse_failures']:>4} {'!' if r.get('harness_failed') else '':>3}"
        )
    print("-" * 100)
    clean = [r for r in results if not r.get("harness_failed")]
    scores = [r["score"] for r in clean]
    passed = sum(1 for r in clean if r["outcome"] == "victory")
    avg = sum(scores) / len(scores) if scores else 0.0
    total_parse = sum(r["parse_successes"] for r in results)
    total_fail = sum(r["parse_failures"] for r in results)
    total_calls = total_parse + total_fail
    overall_parse_rate = total_parse / total_calls if total_calls else 0.0
    total_time = sum(r["elapsed_s"] for r in results)
    quarantined = len(results) - len(clean)
    print(
        f"Avg score: {avg:.3f} | Passed: {passed}/{len(clean)} | "
        f"Parse rate: {overall_parse_rate:.1%} ({total_fail} failures) | "
        f"Total time: {total_time:.1f}s"
        + (f" | {quarantined} run(s) quarantined (HF = harness failure)" if quarantined else "")
    )
    print("=" * 100)


def _build_config(args: argparse.Namespace, smoke: bool) -> RLEConfig:
    overrides: dict[str, Any] = {}
    if args.provider:
        overrides["provider"] = args.provider
    if args.model:
        overrides["model"] = args.model
    if args.base_url:
        overrides["provider_base_url"] = args.base_url
    if args.tick_interval is not None and not smoke:
        overrides["tick_interval"] = args.tick_interval
    if args.tick_timeout is not None:
        overrides["tick_timeout_s"] = args.tick_timeout
    if smoke and args.tick_interval is None:
        overrides["tick_interval"] = 0.0
    return RLEConfig(**overrides) if overrides else RLEConfig()


def _resolve_ticks(args: argparse.Namespace, use_mock_rimapi: bool) -> int | None:
    """Determine tick cap from CLI args."""
    if args.ticks:
        return args.ticks
    if use_mock_rimapi:
        return 10
    return None


async def _run_ablation(  # noqa: PLR0913
    args: argparse.Namespace,
    config: RLEConfig,
    harness_options: dict[str, Any],
    scenarios: list[ScenarioConfig],
    use_mock_rimapi: bool,
    num_runs: int,
    ticks_override: int | None,
) -> None:
    """Ablation study (Felix only): full roster + 7 single-agent-removed passes."""
    output_dir = Path(args.output) if args.output else get_run_dir(args.model)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with RimAPIClient(config.rimapi_url) as client:
        if use_mock_rimapi:
            MockRimAPI().attach(client)

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
                    if not use_mock_rimapi and not await _load_save(client, config, scenario):
                        print(f"    SKIP {scenario.name}{run_label} ({tag}): save load failed")
                        continue

                    print(f"  {scenario.name}{run_label} ({tag})...")
                    options = {**harness_options, "exclude_agent": exclude}
                    result = await _run_scenario(
                        scenario, config, client, "felix", options, None,
                        max_ticks_override=ticks_override,
                        smoke=use_mock_rimapi,
                        no_pause=args.no_pause,
                    )
                    pass_results.append({"scenario": scenario.name, "score": result["score"]})
                    print(f"    score={result['score']:.3f}")

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

    ablation_data = {
        "num_runs": num_runs,
        "ticks_per_scenario": ticks_override,
        "passes": [{"label": t, "results": r} for t, r in passes],
        "matrix": matrix,
    }
    ablation_path = output_dir / "ablation_results.json"
    ablation_path.write_text(json.dumps(ablation_data, indent=2))
    print(f"\nAblation results saved to {ablation_path}")


async def main(args: argparse.Namespace) -> None:  # noqa: PLR0912, PLR0915
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

    scenarios = list_scenarios()
    is_smoke_test = args.smoke_test or args.dry_run
    if args.dry_run:
        logger.warning("--dry-run is deprecated, use --smoke-test")
    config = _build_config(args, is_smoke_test)
    # Smoke test = mock game AND mock model. --smoke-test with --provider used
    # to mean "real LLM against the fake game"; that is now
    # --harness-opt smoke_llm=false territory for harnesses that support it.
    use_mock_rimapi = is_smoke_test and not args.docker

    num_runs = getattr(args, "runs", 1) or 1

    harness_names = selected_harnesses(args, config)
    harness_option_sets = {
        name: harness_options_for(name, args, config) for name in harness_names
    }

    if args.ablation:
        if harness_names != ["felix"]:
            raise SystemExit("--ablation is a Felix-only experiment (use --harness felix)")
        ticks_override = _resolve_ticks(args, use_mock_rimapi)
        await _run_ablation(
            args, config, harness_option_sets["felix"], scenarios, use_mock_rimapi,
            num_runs, ticks_override,
        )
        return

    # N >= 4 advisory (issue #45: N=1 content spreads are valid dataset
    # entries when labeled as such — the dataset card carries the framing)
    if args.push_hf and num_runs < 4:
        print(
            "WARNING: --push-hf with --runs < 4 — pushed as a content-spread "
            "entry, NOT statistically valid.",
        )
    if num_runs < 4 and not use_mock_rimapi:
        print(f"WARNING: N={num_runs} runs is below minimum (4) for statistical validity.")
    ticks_override = _resolve_ticks(args, use_mock_rimapi)

    output_dir = None
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize W&B logger (no-op if --wandb not passed or wandb not installed)
    wandb_logger = WandBLogger(
        enabled=args.wandb,
        run_name=f"{'+'.join(harness_names)}_{config.model}_{ticks_override or 'full'}ticks",
    )
    if wandb_logger.enabled:
        wandb_logger.log_config({
            **collect_metadata(random_seed=args.seed),
            "harnesses": harness_names,
            "harness_options": harness_option_sets,
            "model": config.model,
            "provider": config.provider,
            "ticks_per_scenario": ticks_override,
        })

    # Initialize cost tracker (fetches OpenRouter pricing; CLI may override)
    cost_tracker = await create_cost_tracker(
        config.model,
        prompt_price_override=(
            args.prompt_price_per_mtok / 1_000_000
            if args.prompt_price_per_mtok is not None else None
        ),
        completion_price_override=(
            args.completion_price_per_mtok / 1_000_000
            if args.completion_price_per_mtok is not None else None
        ),
    )

    event_log: EventLog | None = None
    if args.output:
        event_log = EventLog(Path(args.output) / "events.jsonl")

    no_baseline = getattr(args, "no_baseline", False) or harness_names == ["baseline"]
    is_paired = not use_mock_rimapi and not no_baseline

    results: list[dict[str, Any]] = []
    paired_results: list[PairedResult] = []

    docker_server: DockerGameServer | None = None
    if args.docker:
        docker_server = DockerGameServer(
            image=config.docker_image, port=config.docker_port,
        )
        await docker_server.start()
        config = RLEConfig(**{**config.model_dump(), "rimapi_url": docker_server.url})

    history_path: Path | None = None
    try:
        async with RimAPIClient(config.rimapi_url) as client:
            if use_mock_rimapi:
                MockRimAPI().attach(client)

            for harness_name in harness_names:
                harness_options = harness_option_sets[harness_name]
                if len(harness_names) > 1:
                    print(f"\n{'#' * 60}\n# HARNESS: {harness_name}\n{'#' * 60}")

                for scenario in scenarios:
                    if docker_server:
                        await docker_server.restart()
                    paired = (
                        PairedResult(scenario=f"{harness_name}/{scenario.name}")
                        if is_paired else None
                    )

                    for run_id in range(num_runs):
                        run_label = f" (run {run_id + 1}/{num_runs})" if num_runs > 1 else ""

                        if not use_mock_rimapi and not await _load_save(client, config, scenario):
                            print(f"  SKIP {scenario.name}{run_label}: save load failed")
                            continue

                        print(
                            f"\nRunning: {scenario.name} ({scenario.difficulty}) "
                            f"[{harness_name}]{run_label}...",
                        )
                        try:
                            result = await _run_scenario(
                                scenario, config, client, harness_name, harness_options,
                                output_dir,
                                max_ticks_override=ticks_override,
                                smoke=use_mock_rimapi,
                                no_pause=args.no_pause,
                                event_log=event_log,
                                cost_tracker=cost_tracker,
                                weave_module=wandb_logger.weave,
                            )
                        except RunError as exc:
                            exit_with_harness_error(exc)
                            return
                        results.append(result)
                        if paired:
                            paired.agent_scores.append(result["score"])
                        print(
                            f"  -> {harness_name}: {result['outcome']} "
                            f"| score={result['score']:.3f} | {result['ticks']} ticks "
                            f"| {result['elapsed_s']}s | parse {result['parse_rate']:.0%} "
                            f"({result['parse_failures']} fail)"
                            + (" | HARNESS FAILURE" if result["harness_failed"] else "")
                        )

                        # Baseline run (reload same save, unmanaged colony)
                        if paired is not None:
                            if not await _load_save(client, config, scenario):
                                logger.warning("Could not reload save for baseline")
                            print(f"  baseline{run_label}...")
                            baseline = await _run_scenario(
                                scenario, config, client, "baseline", {}, output_dir,
                                max_ticks_override=ticks_override,
                                no_pause=args.no_pause,
                            )
                            paired.baseline_scores.append(baseline["score"])
                            print(f"  -> baseline: score={baseline['score']:.3f}")

                    if paired:
                        paired_results.append(paired)

        # Print results
        if is_paired and paired_results:
            print_paired_leaderboard(paired_results, model=config.model, num_runs=num_runs)
        else:
            _print_leaderboard(results, model=config.model)

        # Reconcile estimates against OpenRouter's billed ground truth
        # (token-count estimates diverged up to 4x on the v0.3.0 spread).
        billed_report = None
        effective_base_url = config.provider_base_url or ""
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        generation_ids = cost_tracker.generation_ids
        if "openrouter.ai" in effective_base_url and openai_key and generation_ids:
            print(
                f"\nReconciling billed cost for {len(generation_ids)} "
                "generations against OpenRouter...",
            )
            billed_report = await fetch_billed_costs(generation_ids, openai_key)

        clean_results = [r for r in results if not r.get("harness_failed")]
        metadata = collect_metadata(random_seed=args.seed)
        summary: dict[str, Any] = {
            **metadata,
            "harness": harness_names[0] if len(harness_names) == 1 else "matrix",
            "harnesses": harness_names,
            "harness_options": harness_option_sets,
            "harness_versions": {
                r["harness"]: r["harness_versions"] for r in results
            },
            "model": config.model,
            "provider": config.provider,
            "base_url": config.provider_base_url,
            "tick_interval": config.tick_interval,
            "ticks_per_scenario": ticks_override,
            "num_runs": num_runs,
            "paired": is_paired,
            "scenarios": results,
            "quarantined_runs": len(results) - len(clean_results),
            "cost_snapshot": cost_tracker.snapshot().model_dump(),
        }
        if billed_report:
            summary["billed_cost"] = billed_report.model_dump()
        if event_log:
            summary["event_summary"] = event_log.summary().model_dump()
        if is_paired and paired_results:
            summary["paired_results"] = [p.to_dict() for p in paired_results]

        output_dir = Path(args.output) if args.output else get_run_dir(config.model)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "benchmark_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, default=str))
        print(f"\nResults exported to {output_dir}/")

        # Only track real benchmark runs (not smoke tests)
        scores = [r.get("score", 0) for r in clean_results]
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
            print("(smoke test: skipping history/baseline tracking)")

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

        if args.push_hf and history_path is not None:
            hf = HFLogger(
                repo_id=config.hf_dataset_repo, token=config.hf_token,
            )
            if hf.enabled:
                hf.push_results(
                    history_path=history_path,
                    baselines_dir=Path("results/baseline"),
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
        help="Mock RIMAPI + each harness's smoke variant (no game, no LLM)",
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
        help="(WIP, felix only) Run ablation study: full roster + 7 single-agent-removed runs",
    )
    parser.add_argument(
        "--provider",
        help="LLM provider name passed to the harness (felix: anthropic|openai|local|claude-code)",
    )
    parser.add_argument("--model", help="Model name (e.g. qwen/qwen3.5-9b)")
    parser.add_argument("--base-url", help="Provider API base URL (e.g. http://localhost:1234/v1)")
    add_harness_args(parser, repeatable=True)
    parser.add_argument("--ticks", type=int, help="Override max ticks per scenario")
    parser.add_argument(
        "--tick-interval", type=float,
        help="Seconds between ticks (default: 1.0, use 30-60 for live game)",
    )
    parser.add_argument(
        "--tick-timeout", type=float, default=None,
        help="Loop-level cap in seconds on a whole harness step (default: none).",
    )
    parser.add_argument(
        "--runs", type=int, default=1,
        help="Number of paired runs per scenario (default: 1, use 4+ for statistical rigor)",
    )
    parser.add_argument(
        "--no-baseline", action="store_true",
        help="Skip baseline (unmanaged) runs — harness-only, no paired comparison",
    )
    parser.add_argument(
        "--no-pause", action="store_true",
        help="Don't pause game during deliberation (SSE-driven)",
    )
    parser.add_argument("--wandb", action="store_true", help="Log to Weights & Biases")
    parser.add_argument("--push-hf", action="store_true", help="Push results to HuggingFace Hub")
    parser.add_argument(
        "--seed", type=int, default=None,
        help=(
            "Seed for RLE-side stochasticity (resolver tiebreaks, json_repair "
            "fallbacks). Does NOT control RimWorld's RNG. Recorded in the "
            "benchmark_summary for replay."
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
    parser.add_argument("--log-level", default="WARNING", help="Logging level")
    asyncio.run(main(parser.parse_args()))
