"""Tests for the HuggingFace dataset card builder."""

from __future__ import annotations

from rle.tracking.hf_logger import build_dataset_card

_BOARD = {
    "baseline": {"mean_time_to_end_days": 8.0, "n_runs": 4},
    "rows": [
        {
            "model": "x-ai/grok-4.3",
            "mean_composite": 0.8359,
            "final_composite": 0.804,
            "vs_baseline_mean_delta": -0.0035,
            "ticks_above_baseline": "5/10",
            "raw_action_success": 0.7874,
            "est_cost_usd": 0.54,
            "real_cost_usd": 0.358,
        },
        {
            "model": "z-ai/glm-5.1",
            "mean_composite": 0.7818,
            "final_composite": 0.7396,
            "vs_baseline_mean_delta": 0.0276,
            "ticks_above_baseline": "7/10",
            "raw_action_success": 0.7111,
            "est_cost_usd": 0.81,
            "real_cost_usd": 0.939,
        },
        {
            "model": "claude-fable-5",
            "mean_composite": 0.8051,
            "final_composite": 0.7213,
            "vs_baseline_mean_delta": -0.015,
            "ticks_above_baseline": "4/10",
            "raw_action_success": 0.6942,
            "est_cost_usd": 5.48,
            "real_cost_usd": None,
        },
    ],
}


class TestBuildDatasetCard:
    def test_has_hub_frontmatter(self) -> None:
        card = build_dataset_card(_BOARD, "2026-06-11")
        assert card.startswith("---\n")
        assert "license: mit" in card
        assert "pretty_name:" in card

    def test_all_models_in_table_with_rank(self) -> None:
        card = build_dataset_card(_BOARD, "2026-06-11")
        assert "| 1 | x-ai/grok-4.3 |" in card
        assert "| 2 | z-ai/glm-5.1 |" in card
        assert "| 3 | claude-fable-5 |" in card

    def test_real_cost_unmarked_estimate_marked(self) -> None:
        card = build_dataset_card(_BOARD, "2026-06-11")
        assert "$0.36" in card  # billed ground truth, no marker
        assert "~$5.48" in card  # subscription model: estimate marker

    def test_baseline_beaters_called_out(self) -> None:
        card = build_dataset_card(_BOARD, "2026-06-11")
        assert "1 of 3 harness/model rows beat the unmanaged baseline." in card
        assert "(z-ai/glm-5.1)" in card

    def test_date_and_baseline_framing(self) -> None:
        card = build_dataset_card(_BOARD, "2026-06-11")
        assert "2026-06-11" in card
        assert "time-to-end 8.0 days" in card
        assert "not" in card and "statistically valid" in card

    def test_no_baseline_beaters_omits_paren(self) -> None:
        board = {
            "baseline": _BOARD["baseline"],
            "rows": [r for r in _BOARD["rows"] if r["model"] != "z-ai/glm-5.1"],
        }
        card = build_dataset_card(board, "2026-06-11")
        assert "0 of 2 harness/model rows beat the unmanaged baseline." in card


class TestHarnessRows:
    def test_rows_with_harness_are_labelled_harness_slash_model(self) -> None:
        board = {
            "baseline": _BOARD["baseline"],
            "rows": [
                {**_BOARD["rows"][1], "harness": "felix"},
                {**_BOARD["rows"][0], "harness": "some-tool"},
            ],
        }
        card = build_dataset_card(board, "2026-09-04")
        assert "| felix/z-ai/glm-5.1 |" in card
        assert "| some-tool/x-ai/grok-4.3 |" in card
        assert "(felix/z-ai/glm-5.1)" in card
