"""Bootstrap confidence intervals for RLE benchmark statistics."""

from __future__ import annotations

import math
import random

from pydantic import BaseModel, ConfigDict


class BootstrapCI(BaseModel):
    """Bootstrap confidence interval at a configurable confidence level."""

    model_config = ConfigDict(frozen=True)

    mean: float
    ci_lower: float  # lower percentile bound
    ci_upper: float  # upper percentile bound
    std: float
    n_samples: int
    n_bootstrap: int = 10_000


def bootstrap_ci(
    values: list[float],
    n_bootstrap: int = 10_000,
    ci: float = 0.95,
    seed: int | None = None,
) -> BootstrapCI:
    """Compute bootstrap confidence interval using percentile method.

    Uses only stdlib random.choices() — no scipy/numpy dependency (see ADR-003).

    Args:
        values: Sample values (need at least 1)
        n_bootstrap: Number of bootstrap resamples (default 10,000)
        ci: Confidence level (default 0.95)
        seed: Optional random seed for reproducibility

    Raises:
        ValueError: If values is empty.
    """
    if not values:
        raise ValueError("values must not be empty")

    n = len(values)
    mean = sum(values) / n

    if n == 1:
        return BootstrapCI(
            mean=mean,
            ci_lower=mean,
            ci_upper=mean,
            std=0.0,
            n_samples=n,
            n_bootstrap=n_bootstrap,
        )

    # Population std (ddof=0) — sufficient for CI estimation
    std = math.sqrt(sum((x - mean) ** 2 for x in values) / n)

    rng = random.Random(seed)
    boot_means = sorted(sum(rng.choices(values, k=n)) / n for _ in range(n_bootstrap))

    alpha = 1.0 - ci
    lower_idx = max(0, min(int(alpha / 2 * n_bootstrap), n_bootstrap - 1))
    upper_idx = max(0, min(int(math.ceil((1.0 - alpha / 2) * n_bootstrap)) - 1, n_bootstrap - 1))

    return BootstrapCI(
        mean=mean,
        ci_lower=boot_means[lower_idx],
        ci_upper=boot_means[upper_idx],
        std=std,
        n_samples=n,
        n_bootstrap=n_bootstrap,
    )


def bootstrap_paired_delta(
    agent_scores: list[float],
    baseline_scores: list[float],
    n_bootstrap: int = 10_000,
    ci: float = 0.95,
    seed: int | None = None,
) -> BootstrapCI:
    """Bootstrap CI for the agent-baseline delta.

    Resamples paired differences to get CI on the performance gap.

    Args:
        agent_scores: Scores from the agent run.
        baseline_scores: Scores from the baseline run.
        n_bootstrap: Number of bootstrap resamples.
        ci: Confidence level (default 0.95).
        seed: Optional random seed for reproducibility.
    """
    n = min(len(agent_scores), len(baseline_scores))
    deltas = [agent_scores[i] - baseline_scores[i] for i in range(n)]
    return bootstrap_ci(deltas, n_bootstrap=n_bootstrap, ci=ci, seed=seed)
