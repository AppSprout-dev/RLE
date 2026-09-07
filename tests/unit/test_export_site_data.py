"""Pareto eligibility for site export — unknown $0 is never a point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import export_site_data as export  # noqa: E402


def _row(**overrides: object) -> dict:
    base: dict[str, object] = {
        "model": "x-ai/grok-4.6",
        "name": "cli-agent",
        "mean_composite": 0.8,
        "final_composite": 0.75,
        "vs_baseline_mean_delta": 0.01,
        "ticks_above_baseline": "6/10",
        "end_day": 4,
        "raw_action_success": 0.7,
        "ex_artifact_success": 0.8,
        "avg_latency_s": 2.0,
        "wall_min": 5.0,
        "est_cost_usd": 0.0,
        "real_cost_usd": None,
        "cost_source": "unknown",
        "pareto_eligible": False,
    }
    base.update(overrides)
    return base


class TestBuildModelPareto:
    def test_unknown_zero_is_not_a_pareto_point(self) -> None:
        model = export.build_model(_row())
        assert model["costUsd"] is None
        assert model["costSource"] == "unknown"
        assert model["paretoEligible"] is False

    def test_billed_uses_real_cost(self) -> None:
        model = export.build_model(_row(
            cost_source="billed",
            real_cost_usd=0.857,
            display_cost_usd=0.857,
            est_cost_usd=1.2,
            pareto_eligible=True,
        ))
        assert model["costUsd"] == pytest.approx(0.86)
        assert model["costSource"] == "billed"
        assert model["costEstimated"] is False
        assert model["paretoEligible"] is True

    def test_estimated_uses_est_cost(self) -> None:
        model = export.build_model(_row(
            name="cli-agent",
            cost_source="estimated",
            est_cost_usd=1.594858,
            display_cost_usd=1.594858,
            pareto_eligible=True,
        ))
        assert model["costUsd"] == pytest.approx(1.59)
        assert model["costSource"] == "estimated"
        assert model["costEstimated"] is True
        assert model["paretoEligible"] is True

    def test_console_uses_console_cost(self) -> None:
        model = export.build_model(_row(
            name="acp",
            cost_source="console",
            console_cost_usd=7.0,
            display_cost_usd=7.0,
            est_cost_usd=0.0,
            pareto_eligible=True,
        ))
        assert model["costUsd"] == pytest.approx(7.0)
        assert model["costSource"] == "console"
        assert model["paretoEligible"] is True


class TestBuildMetaSpend:
    def test_unknown_zero_excluded_from_total_spend(self) -> None:
        board = {
            "baseline": {"mean_time_to_end_days": 8, "n_runs": 4},
            "rows": [
                _row(name="raw", cost_source="unknown", est_cost_usd=0.0),
                _row(
                    name="felix",
                    cost_source="billed",
                    real_cost_usd=0.857,
                    display_cost_usd=0.857,
                    pareto_eligible=True,
                ),
            ],
        }
        args = argparse.Namespace(
            scenario="Crashlanded", seed=42, ticks=10, n_runs=1, date="2026-09-07",
        )
        meta = export.build_meta(board, [], args)
        assert meta["totalSpendUsd"] == pytest.approx(0.86)

    def test_pack_cost_backfill_is_documented(self) -> None:
        assert export.PACK_COST_BACKFILL["cli-agent"]["cost_source"] == "estimated"
        assert export.PACK_COST_BACKFILL["felix"]["cost_source"] == "billed"
        assert export.PACK_COST_BACKFILL["acp"]["cost_source"] == "console"
        assert export.PACK_COST_BACKFILL["raw-grok"]["cost_source"] == "unknown"
