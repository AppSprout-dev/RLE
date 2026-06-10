"""Tests for Phase B1 baseline aggregation and the sidecar loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rle.scenarios.loader import (
    BaselineMismatchError,
    baseline_path,
    load_baseline,
    load_scenario,
)
from rle.scenarios.schema import BaselineReference
from rle.scoring.baseline import BaselineRun, aggregate_baseline, read_run
from rle.tracking.metadata import SCORING_VERSION

_SCENARIO_YAML = """\
name: Test Scenario
description: test
difficulty: easy
expected_duration_days: 30
initial_population: 3
victory_conditions: []
failure_conditions: []
save_name: test_save
save_sha256: aabbcc
"""


def _make_run(
    seed: int, composites: list[float], outcome: str = "defeat",
) -> BaselineRun:
    return BaselineRun(
        seed=seed,
        outcome=outcome,
        days=[i * 0.5 for i in range(len(composites))],
        composites=composites,
        metrics={"mood": [0.5] * len(composites)},
    )


class TestAggregateBaseline:
    def test_unequal_run_lengths(self) -> None:
        ref = aggregate_baseline(
            [
                _make_run(42, [0.9, 0.8, 0.7]),
                _make_run(43, [0.9, 0.6]),
            ],
            scenario_name="Test", recorded_on="2026-06-10T00:00:00Z",
            scoring_version="1.1",
        )
        assert ref.n_runs == 2
        assert ref.seeds == (42, 43)
        assert len(ref.score_trajectory) == 3
        assert ref.score_trajectory[0].n_runs == 2
        assert ref.score_trajectory[0].composite_mean == pytest.approx(0.9)
        assert ref.score_trajectory[1].composite_mean == pytest.approx(0.7)
        # Only the longer run is alive at tick 2 — no CI with one value
        assert ref.score_trajectory[2].n_runs == 1
        assert ref.score_trajectory[2].composite_ci95 is None
        assert ref.score_trajectory[2].composite_mean == pytest.approx(0.7)

    def test_time_to_end_stats(self) -> None:
        ref = aggregate_baseline(
            [
                _make_run(42, [0.9] * 21),  # days 0..10
                _make_run(43, [0.9] * 41),  # days 0..20
            ],
            scenario_name="Test", recorded_on="2026-06-10T00:00:00Z",
            scoring_version="1.1",
        )
        assert ref.time_to_end_days_mean == pytest.approx(15.0)
        assert ref.time_to_end_days_ci95 is not None

    def test_metric_means_carried(self) -> None:
        ref = aggregate_baseline(
            [_make_run(42, [0.9, 0.8])],
            scenario_name="Test", recorded_on="2026-06-10T00:00:00Z",
            scoring_version="1.1",
        )
        assert ref.score_trajectory[0].metric_means["mood"] == pytest.approx(0.5)

    def test_empty_runs_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one run"):
            aggregate_baseline(
                [], scenario_name="Test",
                recorded_on="2026-06-10T00:00:00Z", scoring_version="1.1",
            )


class TestReadRun:
    def test_reads_csv_and_summary(self, tmp_path: Path) -> None:
        (tmp_path / "01_test_survival.csv").write_text(
            "tick,day,mood,composite\n100,0,0.5,0.9\n200,1,0.4,0.8\n",
            encoding="utf-8",
        )
        (tmp_path / "01_test_summary.json").write_text(
            json.dumps({"random_seed": 42, "outcome": "defeat"}),
            encoding="utf-8",
        )
        run = read_run(tmp_path)
        assert run.seed == 42
        assert run.outcome == "defeat"
        assert run.composites == [0.9, 0.8]
        assert run.metrics["mood"] == [0.5, 0.4]
        assert run.time_to_end_days == pytest.approx(1.0)

    def test_missing_csv_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="CSV"):
            read_run(tmp_path)


class TestLoadBaseline:
    def _write_scenario(self, tmp_path: Path) -> Path:
        path = tmp_path / "01_test.yaml"
        path.write_text(_SCENARIO_YAML, encoding="utf-8")
        return path

    def _write_baseline(
        self, scenario_yaml: Path, *, save_sha256: str = "aabbcc",
        scoring_version: str = SCORING_VERSION,
    ) -> None:
        ref = BaselineReference(
            scenario_name="Test Scenario", n_runs=1, seeds=(42,),
            outcomes=("defeat",), time_to_end_days_mean=10.0,
            score_trajectory=(), recorded_on="2026-06-10T00:00:00Z",
            save_sha256=save_sha256, scoring_version=scoring_version,
        )
        baseline_path(scenario_yaml).write_text(
            ref.model_dump_json(), encoding="utf-8",
        )

    def test_no_sidecar_returns_none(self, tmp_path: Path) -> None:
        path = self._write_scenario(tmp_path)
        scenario = load_scenario(path, allow_unpinned=True)
        assert load_baseline(path, scenario) is None

    def test_matching_baseline_loads(self, tmp_path: Path) -> None:
        path = self._write_scenario(tmp_path)
        scenario = load_scenario(path, allow_unpinned=True)
        self._write_baseline(path)
        ref = load_baseline(path, scenario)
        assert ref is not None
        assert ref.scenario_name == "Test Scenario"

    def test_save_sha_mismatch_fails_fast(self, tmp_path: Path) -> None:
        path = self._write_scenario(tmp_path)
        scenario = load_scenario(path, allow_unpinned=True)
        self._write_baseline(path, save_sha256="stale")
        with pytest.raises(BaselineMismatchError, match="save_sha256"):
            load_baseline(path, scenario)

    def test_scoring_version_mismatch_fails_fast(self, tmp_path: Path) -> None:
        path = self._write_scenario(tmp_path)
        scenario = load_scenario(path, allow_unpinned=True)
        self._write_baseline(path, scoring_version="0.9")
        with pytest.raises(BaselineMismatchError, match="scoring_version"):
            load_baseline(path, scenario)
