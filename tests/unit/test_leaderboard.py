"""Tests for the leaderboard generator."""

from __future__ import annotations

import pytest

from rle.tracking.leaderboard import Leaderboard, LeaderboardEntry


def _history_entry(
    model: str,
    scenarios: list[dict[str, object]],
    cost_usd: float = 0.0,
    tokens: int = 0,
) -> dict[str, object]:
    return {
        "model": model,
        "scenarios": scenarios,
        "cost": {"estimated_cost_usd": cost_usd, "total_tokens": tokens, "wall_time_s": 10.0},
        "timestamp": "2026-04-09T12:00:00Z",
        "git_commit": "abc1234",
    }


def _scenario(name: str, score: float) -> dict[str, object]:
    return {"name": name, "score": score}


HISTORY = [
    _history_entry("claude-3.5", [_scenario("Crashlanded", 0.82), _scenario("Winter", 0.71)],
                   cost_usd=2.40, tokens=50000),
    _history_entry("gpt-4o", [_scenario("Crashlanded", 0.78), _scenario("Winter", 0.68)],
                   cost_usd=1.80, tokens=40000),
    _history_entry("nemotron-120b", [_scenario("Crashlanded", 0.75), _scenario("Winter", 0.65)],
                   cost_usd=0.0, tokens=30000),
]


class TestFromHistory:
    def test_groups_by_model(self) -> None:
        lb = Leaderboard()
        entries = lb.from_history(HISTORY)
        models = [e.model for e in entries]
        assert "claude-3.5" in models
        assert "gpt-4o" in models
        assert "nemotron-120b" in models

    def test_sorted_by_composite_descending(self) -> None:
        lb = Leaderboard()
        entries = lb.from_history(HISTORY)
        scores = [e.composite_score for e in entries]
        assert scores == sorted(scores, reverse=True)

    def test_takes_latest_run_per_model(self) -> None:
        history = [
            _history_entry("model-a", [_scenario("S1", 0.5)]),
            _history_entry("model-a", [_scenario("S1", 0.9)]),
        ]
        lb = Leaderboard()
        entries = lb.from_history(history)
        assert len(entries) == 1
        # Composite should reflect both runs averaged
        assert entries[0].n_runs == 2

    def test_empty_history(self) -> None:
        lb = Leaderboard()
        assert lb.from_history([]) == []


class TestToMarkdown:
    def test_produces_valid_markdown(self) -> None:
        lb = Leaderboard()
        entries = lb.from_history(HISTORY)
        md = lb.to_markdown(entries)
        lines = md.strip().split("\n")
        assert len(lines) >= 3  # header + separator + at least 1 row
        assert "| Model |" in lines[0]
        assert "---" in lines[1]

    def test_includes_cost_column(self) -> None:
        lb = Leaderboard()
        entries = lb.from_history(HISTORY)
        md = lb.to_markdown(entries)
        assert "Cost" in md
        assert "$2.40" in md

    def test_includes_significance_markers(self) -> None:
        entry = LeaderboardEntry(
            model="test",
            composite_score=0.8,
            scenarios={"S1": 0.82},
            significance_vs_baseline={"S1": "**"},
        )
        lb = Leaderboard()
        md = lb.to_markdown([entry])
        assert "0.82**" in md

    def test_empty_entries(self) -> None:
        lb = Leaderboard()
        assert lb.to_markdown([]) == ""


class TestParetoFrontier:
    def test_identifies_dominated_entries(self) -> None:
        entries = [
            LeaderboardEntry(model="A", composite_score=0.9, total_cost_usd=3.0),
            LeaderboardEntry(model="B", composite_score=0.8, total_cost_usd=1.0),
            LeaderboardEntry(model="C", composite_score=0.7, total_cost_usd=2.0),
        ]
        lb = Leaderboard()
        frontier = lb.pareto_frontier(entries)
        models = [e.model for e in frontier]
        assert "A" in models  # highest score
        assert "B" in models  # cheapest with decent score
        assert "C" not in models  # dominated by B (lower score AND higher cost)

    def test_same_cost_returns_highest_score(self) -> None:
        entries = [
            LeaderboardEntry(model="A", composite_score=0.9, total_cost_usd=1.0),
            LeaderboardEntry(model="B", composite_score=0.7, total_cost_usd=1.0),
        ]
        lb = Leaderboard()
        frontier = lb.pareto_frontier(entries)
        assert len(frontier) == 1
        assert frontier[0].model == "A"

    def test_single_entry(self) -> None:
        entry = LeaderboardEntry(model="solo", composite_score=0.5, total_cost_usd=1.0)
        lb = Leaderboard()
        assert lb.pareto_frontier([entry]) == [entry]

    def test_empty(self) -> None:
        lb = Leaderboard()
        assert lb.pareto_frontier([]) == []
