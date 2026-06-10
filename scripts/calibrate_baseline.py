"""Phase B1: calibrate a scenario's no-agent baseline.

Runs N seeded --no-agent --until-death runs against the live game, then
aggregates them into a pinned <scenario>.baseline.json sidecar next to the
scenario YAML. The baseline is an immutable scenario property — re-run this
only when the scenario's save or SCORING_VERSION changes.

Usage:
    python scripts/calibrate_baseline.py crashlanded --seeds 42 43 44 45
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rle.scenarios.loader import baseline_path, load_baseline, load_scenario
from rle.scoring.baseline import aggregate_baseline, read_run
from rle.tracking.metadata import SCORING_VERSION, collect_metadata

DEFINITIONS_DIR = (
    Path(__file__).parent.parent / "src" / "rle" / "scenarios" / "definitions"
)


def _find_scenario_path(query: str) -> Path:
    for path in sorted(DEFINITIONS_DIR.glob("*.yaml")):
        if path.stem.startswith(query) or query in path.stem:
            return path
    raise SystemExit(f"No scenario matching {query!r} in {DEFINITIONS_DIR}")


def _run_one(
    scenario_query: str, seed: int, out_dir: Path, tick_interval: float,
) -> None:
    cmd = [
        sys.executable, str(Path(__file__).parent / "run_scenario.py"),
        scenario_query,
        "--no-agent", "--until-death", "--no-pause",
        "--seed", str(seed),
        "--output", str(out_dir),
        "--tick-interval", str(tick_interval),
    ]
    print(f"[baseline] seed {seed} -> {out_dir}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(
            f"Baseline run for seed {seed} failed (exit {result.returncode}); "
            f"aborting calibration — partial baselines must not be written.",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario name or number prefix")
    parser.add_argument(
        "--seeds", type=int, nargs="+", default=[42, 43, 44, 45],
        help="One run per seed (default: 42 43 44 45; N>=4 for validity)",
    )
    parser.add_argument(
        "--output", default="results/baseline",
        help="Directory for per-run artifacts (default: results/baseline)",
    )
    parser.add_argument("--tick-interval", type=float, default=30.0)
    parser.add_argument(
        "--aggregate-only", action="store_true",
        help="Skip the runs; aggregate existing per-seed dirs under --output",
    )
    args = parser.parse_args()

    scenario_path = _find_scenario_path(args.scenario)
    scenario = load_scenario(scenario_path)
    out_root = Path(args.output) / scenario_path.stem

    run_dirs = [out_root / f"seed{seed}" for seed in args.seeds]
    if not args.aggregate_only:
        for seed, run_dir in zip(args.seeds, run_dirs):
            run_dir.mkdir(parents=True, exist_ok=True)
            _run_one(args.scenario, seed, run_dir, args.tick_interval)

    runs = [read_run(d) for d in run_dirs]
    metadata = collect_metadata()
    reference = aggregate_baseline(
        runs,
        scenario_name=scenario.name,
        recorded_on=datetime.now(timezone.utc).isoformat(),
        scoring_version=SCORING_VERSION,
        save_sha256=scenario.save_sha256,
        rimapi_dll_sha256=str(metadata.get("rimapi_dll_sha256") or "") or None,
        rle_commit=str(metadata.get("git_commit") or "") or None,
    )

    sidecar = baseline_path(scenario_path)
    sidecar.write_text(reference.model_dump_json(indent=2), encoding="utf-8")
    print(f"[baseline] wrote {sidecar}")

    # Round-trip through the strict loader so a bad sidecar fails HERE,
    # not at the start of someone's benchmark run.
    loaded = load_baseline(scenario_path, scenario)
    assert loaded is not None
    print(
        f"[baseline] {loaded.scenario_name}: n={loaded.n_runs} "
        f"seeds={list(loaded.seeds)} outcomes={list(loaded.outcomes)} "
        f"time_to_end={loaded.time_to_end_days_mean:.1f}d "
        f"trajectory={len(loaded.score_trajectory)} points",
    )


if __name__ == "__main__":
    main()
