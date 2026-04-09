"""Leaderboard generation from RLE benchmark history.

Builds model x scenario results matrix with significance markers,
cost-normalized rankings, and Pareto frontier computation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from rle.scoring.delta import _std


class LeaderboardEntry(BaseModel):
    """One model's benchmark results."""

    model_config = ConfigDict(frozen=True)

    model: str
    composite_score: float
    composite_ci: tuple[float, float] | None = None
    total_cost_usd: float = 0.0
    cost_per_scenario: float = 0.0
    total_tokens: int = 0
    total_wall_time_s: float = 0.0
    n_runs: int = 1
    scenarios: dict[str, float] = {}
    significance_vs_baseline: dict[str, str] = {}
    timestamp: str = ""
    git_commit: str = ""


def _collect_scenario_scores(
    runs: list[dict[str, Any]],
) -> dict[str, list[float]]:
    """Group scenario scores across multiple runs for one model."""
    scores: dict[str, list[float]] = {}
    for run in runs:
        for sc in run.get("scenarios", []):
            name = sc.get("name", "")
            score = sc.get("score")
            if name and isinstance(score, (int, float)):
                scores.setdefault(name, []).append(float(score))
    return scores


def _per_run_composites(runs: list[dict[str, Any]]) -> list[float]:
    """Extract per-run average composite scores."""
    composites: list[float] = []
    for run in runs:
        scenario_scores = [
            sc["score"]
            for sc in run.get("scenarios", [])
            if isinstance(sc.get("score"), (int, float))
        ]
        if scenario_scores:
            composites.append(sum(scenario_scores) / len(scenario_scores))
    return composites


class Leaderboard:
    """Manages the RLE benchmark leaderboard."""

    def from_history(self, history: list[dict[str, Any]]) -> list[LeaderboardEntry]:
        """Build sorted leaderboard from benchmark_history.jsonl entries."""
        by_model: dict[str, list[dict[str, Any]]] = {}
        for entry in history:
            model = entry.get("model", "unknown")
            by_model.setdefault(model, []).append(entry)

        entries: list[LeaderboardEntry] = []
        for model, runs in by_model.items():
            latest = runs[-1]
            scenario_scores = _collect_scenario_scores(runs)
            scenario_means = {k: sum(v) / len(v) for k, v in scenario_scores.items()}

            composites = _per_run_composites(runs)
            composite = sum(composites) / len(composites) if composites else 0.0
            n_runs = len(runs)

            ci: tuple[float, float] | None = None
            if len(composites) >= 2:
                std = _std(composites)
                se = std / len(composites) ** 0.5
                # 95% CI via t-approximation
                t_crit = 1.96 if len(composites) > 30 else 2.0
                ci = (composite - t_crit * se, composite + t_crit * se)

            cost = float(latest.get("cost", {}).get("estimated_cost_usd", 0.0))
            tokens = int(latest.get("cost", {}).get("total_tokens", 0))
            wall = float(latest.get("cost", {}).get("wall_time_s", 0.0))
            n_scenarios = max(len(scenario_means), 1)

            entries.append(LeaderboardEntry(
                model=model,
                composite_score=round(composite, 4),
                composite_ci=ci,
                total_cost_usd=cost,
                cost_per_scenario=round(cost / n_scenarios, 4),
                total_tokens=tokens,
                total_wall_time_s=wall,
                n_runs=n_runs,
                scenarios=scenario_means,
                timestamp=str(latest.get("timestamp", "")),
                git_commit=str(latest.get("git_commit", "")),
            ))

        entries.sort(key=lambda e: e.composite_score, reverse=True)
        return entries

    def to_markdown(self, entries: list[LeaderboardEntry]) -> str:
        """Render model x scenario matrix as Markdown table."""
        if not entries:
            return ""

        all_scenarios = sorted(
            {s for e in entries for s in e.scenarios}
        )
        short_names = [s.split()[0] if " " in s else s[:12] for s in all_scenarios]

        header = "| Model | " + " | ".join(short_names) + " | Avg | Cost |"
        sep = "|" + "|".join("---" for _ in range(len(short_names) + 3)) + "|"

        rows = [header, sep]
        for entry in entries:
            cells = [entry.model]
            for scenario in all_scenarios:
                score = entry.scenarios.get(scenario)
                sig = entry.significance_vs_baseline.get(scenario, "")
                cells.append(f"{score:.2f}{sig}" if score is not None else "—")
            cells.append(f"{entry.composite_score:.2f}")
            cells.append(f"${entry.total_cost_usd:.2f}")
            rows.append("| " + " | ".join(cells) + " |")

        return "\n".join(rows)

    def to_csv(self, entries: list[LeaderboardEntry], path: str) -> None:
        """Export leaderboard as CSV."""
        if not entries:
            return

        all_scenarios = sorted({s for e in entries for s in e.scenarios})
        header = ["model"] + all_scenarios + ["avg", "cost_usd", "n_runs"]

        lines = [",".join(header)]
        for entry in entries:
            row = [entry.model]
            for s in all_scenarios:
                score = entry.scenarios.get(s)
                row.append(f"{score:.4f}" if score is not None else "")
            row.append(f"{entry.composite_score:.4f}")
            row.append(f"{entry.total_cost_usd:.4f}")
            row.append(str(entry.n_runs))
            lines.append(",".join(row))

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def pareto_frontier(
        self, entries: list[LeaderboardEntry],
    ) -> list[LeaderboardEntry]:
        """Return entries on the cost-accuracy Pareto frontier.

        An entry is Pareto-optimal if no other entry has both
        higher composite_score AND lower total_cost_usd.
        """
        frontier: list[LeaderboardEntry] = []
        for entry in entries:
            dominated = any(
                other.composite_score >= entry.composite_score
                and other.total_cost_usd <= entry.total_cost_usd
                and (
                    other.composite_score > entry.composite_score
                    or other.total_cost_usd < entry.total_cost_usd
                )
                for other in entries
                if other is not entry
            )
            if not dominated:
                frontier.append(entry)
        frontier.sort(key=lambda e: e.composite_score, reverse=True)
        return frontier
