"""Unit tests for HeadlessCliHarness turn metering (extras.cost_usd)."""

from __future__ import annotations

import pytest

from rle.tracking.cost_tracker import CostSource, CostTracker

cli_base = pytest.importorskip("rle.harness.cli_base")


class TestApplyTurnMetering:
    def test_cost_only_turn_records_extras_without_tokens(self) -> None:
        tracker = CostTracker("openrouter/x-ai/grok-4.6")
        turn = cli_base.TurnResult(
            text="done",
            prompt_tokens=0,
            completion_tokens=0,
            extras={"cost_usd": 1.25, "generation_id": "gen-abc"},
        )
        payload = cli_base.apply_turn_metering(tracker, turn)

        snap = tracker.snapshot()
        assert snap.cost_source == CostSource.CONSOLE
        assert snap.console_cost_usd == pytest.approx(1.25)
        assert snap.estimated_cost_usd == 0.0
        assert snap.num_calls == 1
        assert tracker.generation_ids == ["gen-abc"]
        assert payload["cost_usd"] == pytest.approx(1.25)
        assert payload["generation_ids"] == ["gen-abc"]
        assert payload["estimated_cost"] == 0.0
        assert payload["prompt_tokens"] == 0

    def test_tokens_and_cost_do_not_double_count_calls(self) -> None:
        tracker = CostTracker(
            "x-ai/grok-4.6",
            prompt_price=0.000001,
            completion_price=0.000002,
            pricing_source="openrouter_api",
        )
        turn = cli_base.TurnResult(
            prompt_tokens=1000,
            completion_tokens=500,
            extras={"cost_usd": 0.05, "cost_source": "billed", "generation_ids": ["g1"]},
        )
        payload = cli_base.apply_turn_metering(tracker, turn)

        snap = tracker.snapshot()
        assert snap.num_calls == 1
        assert snap.cost_source == CostSource.BILLED
        assert snap.billed_cost_usd == pytest.approx(0.05)
        assert snap.estimated_cost_usd == pytest.approx(0.002)
        assert payload["estimated_cost"] == pytest.approx(0.002)

    def test_empty_turn_emits_nothing(self) -> None:
        tracker = CostTracker("model")
        payload = cli_base.apply_turn_metering(tracker, cli_base.TurnResult())
        assert payload == {}
        assert tracker.snapshot().num_calls == 0
