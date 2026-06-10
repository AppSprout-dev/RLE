"""Phase B1 baseline aggregation: N no-agent runs → a pinned BaselineReference."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean

from rle.scenarios.schema import BaselinePoint, BaselineReference
from rle.scoring.bootstrap import bootstrap_ci

# Columns in the per-tick CSV that are not individual metrics.
_NON_METRIC_COLUMNS = frozenset({"tick", "day", "composite"})


@dataclass
class BaselineRun:
    """One no-agent run's per-tick series, as read from its artifacts."""

    seed: int
    outcome: str
    days: list[float] = field(default_factory=list)
    composites: list[float] = field(default_factory=list)
    metrics: dict[str, list[float]] = field(default_factory=dict)

    @property
    def time_to_end_days(self) -> float:
        return self.days[-1] if self.days else 0.0


def read_run(run_dir: Path) -> BaselineRun:
    """Read one run's CSV + summary JSON into a BaselineRun."""
    csv_paths = sorted(run_dir.glob("*_survival.csv")) or sorted(run_dir.glob("*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No per-tick CSV found in {run_dir}")
    summary_paths = sorted(run_dir.glob("*_summary.json"))
    if not summary_paths:
        raise FileNotFoundError(f"No summary JSON found in {run_dir}")
    summary = json.loads(summary_paths[0].read_text(encoding="utf-8"))

    run = BaselineRun(
        seed=int(summary.get("random_seed") or 0),
        outcome=str(summary.get("outcome", "unknown")),
    )
    with open(csv_paths[0], encoding="utf-8") as f:
        for row in csv.DictReader(f):
            run.days.append(float(row["day"]))
            run.composites.append(float(row["composite"]))
            for col, value in row.items():
                if col not in _NON_METRIC_COLUMNS:
                    run.metrics.setdefault(col, []).append(float(value))
    return run


def aggregate_baseline(
    runs: list[BaselineRun],
    *,
    scenario_name: str,
    recorded_on: str,
    scoring_version: str,
    save_sha256: str | None = None,
    rimapi_dll_sha256: str | None = None,
    rle_commit: str | None = None,
    ci_seed: int = 0,
) -> BaselineReference:
    """Aggregate N runs into a pinned BaselineReference.

    Trajectory points are loop-tick indexed; runs end at different ticks, so
    each point averages over the runs that were still going (n_runs records
    how many). CIs need at least 2 values and are omitted otherwise.
    """
    if not runs:
        raise ValueError("aggregate_baseline requires at least one run")

    end_days = [r.time_to_end_days for r in runs]
    end_ci: tuple[float, float] | None = None
    if len(end_days) >= 2:
        ci = bootstrap_ci(end_days, seed=ci_seed)
        end_ci = (ci.ci_lower, ci.ci_upper)

    metric_names = sorted({m for r in runs for m in r.metrics})
    points: list[BaselinePoint] = []
    for i in range(max(len(r.composites) for r in runs)):
        alive = [r for r in runs if len(r.composites) > i]
        composites = [r.composites[i] for r in alive]
        composite_ci: tuple[float, float] | None = None
        if len(composites) >= 2:
            ci = bootstrap_ci(composites, seed=ci_seed)
            composite_ci = (ci.ci_lower, ci.ci_upper)
        points.append(BaselinePoint(
            tick=i,
            composite_mean=fmean(composites),
            composite_ci95=composite_ci,
            n_runs=len(alive),
            metric_means={
                m: fmean(r.metrics[m][i] for r in alive if m in r.metrics)
                for m in metric_names
                if any(m in r.metrics for r in alive)
            },
        ))

    return BaselineReference(
        scenario_name=scenario_name,
        n_runs=len(runs),
        seeds=tuple(r.seed for r in runs),
        outcomes=tuple(r.outcome for r in runs),
        time_to_end_days_mean=fmean(end_days),
        time_to_end_days_ci95=end_ci,
        score_trajectory=tuple(points),
        recorded_on=recorded_on,
        save_sha256=save_sha256,
        rimapi_dll_sha256=rimapi_dll_sha256,
        rle_commit=rle_commit,
        scoring_version=scoring_version,
    )
