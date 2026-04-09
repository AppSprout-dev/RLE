"""Paired benchmark comparison: agent runs vs baseline (no-agent) runs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class PairedResult:
    """Statistical comparison of agent vs baseline scores for one scenario."""

    scenario: str
    agent_scores: list[float] = field(default_factory=list)
    baseline_scores: list[float] = field(default_factory=list)

    @property
    def agent_mean(self) -> float:
        return sum(self.agent_scores) / len(self.agent_scores) if self.agent_scores else 0.0

    @property
    def agent_std(self) -> float:
        return _std(self.agent_scores)

    @property
    def baseline_mean(self) -> float:
        if not self.baseline_scores:
            return 0.0
        return sum(self.baseline_scores) / len(self.baseline_scores)

    @property
    def baseline_std(self) -> float:
        return _std(self.baseline_scores)

    @property
    def delta(self) -> float:
        return self.agent_mean - self.baseline_mean

    @property
    def effect_size(self) -> float:
        """Cohen's d — standardized effect size."""
        pooled_std = math.sqrt(
            (self.agent_std ** 2 + self.baseline_std ** 2) / 2
        )
        if pooled_std == 0:
            return 0.0
        return self.delta / pooled_std

    @property
    def p_value(self) -> float | None:
        """Welch's t-test p-value. Returns None if insufficient data (< 2 runs)."""
        n_a = len(self.agent_scores)
        n_b = len(self.baseline_scores)
        if n_a < 2 or n_b < 2:
            return None
        var_a = self.agent_std ** 2
        var_b = self.baseline_std ** 2
        se = math.sqrt(var_a / n_a + var_b / n_b)
        if se == 0:
            return 0.0
        t_stat = self.delta / se
        # Welch-Satterthwaite degrees of freedom
        num = (var_a / n_a + var_b / n_b) ** 2
        denom = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
        df = num / denom if denom > 0 else 1
        return _t_to_p(abs(t_stat), df)

    @property
    def significance(self) -> str:
        """Human-readable significance marker."""
        p = self.p_value
        if p is None:
            return ""
        if p < 0.01:
            return "**"
        if p < 0.05:
            return "*"
        return ""

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "agent_mean": round(self.agent_mean, 4),
            "agent_std": round(self.agent_std, 4),
            "baseline_mean": round(self.baseline_mean, 4),
            "baseline_std": round(self.baseline_std, 4),
            "delta": round(self.delta, 4),
            "effect_size": round(self.effect_size, 2),
            "p_value": round(self.p_value, 4) if self.p_value is not None else None,
            "n_agent": len(self.agent_scores),
            "n_baseline": len(self.baseline_scores),
        }


def _std(values: list[float]) -> float:
    """Sample standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((x - mean) ** 2 for x in values) / (len(values) - 1))


def _t_to_p(t: float, df: float) -> float:
    """Approximate two-tailed p-value from t-statistic using normal approx.

    For df > 30 this is very accurate. For smaller df it's approximate
    but avoids scipy dependency.
    """
    # Use normal approximation (good enough for df > 4)
    z = t * (1 - 1 / (4 * max(df, 1)))
    # Standard normal CDF approximation (Abramowitz & Stegun)
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return 2 * p  # two-tailed


def print_paired_leaderboard(
    results: list[PairedResult], model: str | None = None, num_runs: int = 0,
) -> None:
    """Print a paired comparison leaderboard."""
    title = f"RLE BENCHMARK — {model}" if model else "RLE BENCHMARK"
    if num_runs:
        title += f" ({num_runs} runs)"
    print(f"\n{'=' * 75}")
    print(title)
    print("=" * 75)
    print(
        f"{'Scenario':<25} {'Agent':>12} {'Baseline':>12} "
        f"{'Delta':>8} {'p-value':>10}"
    )
    print("-" * 75)

    all_agent = []
    all_baseline = []
    for r in results:
        sig = r.significance
        p_str = f"p={r.p_value:.3f}" if r.p_value is not None else "n/a"
        print(
            f"{r.scenario:<25} {r.agent_mean:>5.3f}±{r.agent_std:.2f}"
            f"  {r.baseline_mean:>5.3f}±{r.baseline_std:.2f}"
            f"  {r.delta:>+6.3f}{sig:<2} {p_str:>10}"
        )
        all_agent.extend(r.agent_scores)
        all_baseline.extend(r.baseline_scores)

    print("-" * 75)
    overall = PairedResult("Overall", all_agent, all_baseline)
    sig = overall.significance
    p_str = f"p={overall.p_value:.4f}" if overall.p_value is not None else "n/a"
    print(
        f"{'Overall':<25} {overall.agent_mean:>5.3f}±{overall.agent_std:.2f}"
        f"  {overall.baseline_mean:>5.3f}±{overall.baseline_std:.2f}"
        f"  {overall.delta:>+6.3f}{sig:<2} {p_str:>10}"
    )
    print("=" * 75)
