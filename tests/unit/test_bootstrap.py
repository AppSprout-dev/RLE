"""Tests for bootstrap confidence interval module."""

from __future__ import annotations

import random

import pytest

from rle.scoring.bootstrap import BootstrapCI, bootstrap_ci, bootstrap_paired_delta


class TestBootstrapCI:
    """Tests for bootstrap_ci function."""

    def test_known_distribution_contains_true_mean(self) -> None:
        """CI from uniform [0, 1] samples should contain 0.5."""
        values = [i / 99.0 for i in range(100)]
        result = bootstrap_ci(values, n_bootstrap=10_000, seed=42)
        assert result.ci_lower <= 0.5 <= result.ci_upper

    def test_ci_width_decreases_with_more_samples(self) -> None:
        """Wider CI expected with fewer samples."""
        rng = random.Random(0)
        small = [rng.gauss(0.5, 0.1) for _ in range(10)]
        rng2 = random.Random(0)
        large = [rng2.gauss(0.5, 0.1) for _ in range(100)]

        ci_small = bootstrap_ci(small, n_bootstrap=5_000, seed=1)
        ci_large = bootstrap_ci(large, n_bootstrap=5_000, seed=1)

        width_small = ci_small.ci_upper - ci_small.ci_lower
        width_large = ci_large.ci_upper - ci_large.ci_lower
        assert width_small > width_large

    def test_single_value_returns_degenerate_ci(self) -> None:
        """Single value should yield CI where lower == upper == mean."""
        result = bootstrap_ci([0.7])
        assert result.ci_lower == result.mean
        assert result.ci_upper == result.mean
        assert result.mean == pytest.approx(0.7)
        assert result.std == pytest.approx(0.0)

    def test_two_identical_values_ci_lower_equals_upper(self) -> None:
        """Two identical values produce CI where lower == upper."""
        result = bootstrap_ci([0.5, 0.5], n_bootstrap=1_000, seed=0)
        assert result.ci_lower == pytest.approx(0.5)
        assert result.ci_upper == pytest.approx(0.5)

    def test_seed_reproducibility(self) -> None:
        """Same seed must produce identical results."""
        values = [0.1, 0.3, 0.5, 0.7, 0.9]
        r1 = bootstrap_ci(values, n_bootstrap=1_000, seed=99)
        r2 = bootstrap_ci(values, n_bootstrap=1_000, seed=99)
        assert r1 == r2

    def test_different_seeds_produce_same_mean_different_ci(self) -> None:
        """Mean is seed-independent; CI bounds vary between seeds."""
        values = [0.1, 0.3, 0.5, 0.7, 0.9, 0.2, 0.4, 0.6, 0.8, 1.0]
        r1 = bootstrap_ci(values, n_bootstrap=500, seed=1)
        r2 = bootstrap_ci(values, n_bootstrap=500, seed=2)
        assert r1.mean == pytest.approx(r2.mean)
        assert r1.ci_lower != r2.ci_lower or r1.ci_upper != r2.ci_upper

    def test_empty_values_raises_value_error(self) -> None:
        """Empty values list should raise ValueError."""
        with pytest.raises(ValueError, match="empty"):
            bootstrap_ci([])

    def test_n_samples_field(self) -> None:
        """n_samples should reflect the input length."""
        values = [0.1, 0.2, 0.3, 0.4, 0.5]
        result = bootstrap_ci(values, n_bootstrap=100, seed=0)
        assert result.n_samples == 5

    def test_n_bootstrap_field(self) -> None:
        """n_bootstrap should be stored on result."""
        values = [0.1, 0.5, 0.9]
        result = bootstrap_ci(values, n_bootstrap=500, seed=0)
        assert result.n_bootstrap == 500

    def test_mean_is_arithmetic_mean(self) -> None:
        """Mean field must equal arithmetic mean of inputs."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = bootstrap_ci(values, n_bootstrap=100, seed=0)
        assert result.mean == pytest.approx(3.0)

    def test_ci_bounds_ordered(self) -> None:
        """Lower bound must be <= upper bound."""
        values = [0.2, 0.8, 0.4, 0.6, 0.3, 0.7]
        result = bootstrap_ci(values, n_bootstrap=1_000, seed=42)
        assert result.ci_lower <= result.ci_upper

    def test_result_is_frozen(self) -> None:
        """BootstrapCI must be immutable (frozen Pydantic model)."""
        result = bootstrap_ci([0.5, 0.6], n_bootstrap=100, seed=0)
        with pytest.raises(Exception):
            result.mean = 0.0  # type: ignore[misc]


class TestBootstrapPairedDelta:
    """Tests for bootstrap_paired_delta function."""

    def test_positive_delta_ci_contains_true_delta(self) -> None:
        """When agent consistently outperforms baseline, CI should contain true delta."""
        rng = random.Random(42)
        agent = [0.7 + rng.gauss(0.0, 0.05) for _ in range(30)]
        rng2 = random.Random(99)
        baseline = [0.5 + rng2.gauss(0.0, 0.05) for _ in range(30)]
        result = bootstrap_paired_delta(agent, baseline, n_bootstrap=5_000, seed=0)
        assert result.ci_lower <= result.mean <= result.ci_upper
        assert result.mean == pytest.approx(0.2, abs=0.05)

    def test_negative_delta_ci_is_negative(self) -> None:
        """When baseline outperforms agent, CI should be negative."""
        agent = [0.3] * 20
        baseline = [0.7] * 20
        result = bootstrap_paired_delta(agent, baseline, n_bootstrap=1_000, seed=0)
        assert result.ci_upper < 0.0
        assert result.mean == pytest.approx(-0.4)

    def test_unequal_lengths_uses_min_length(self) -> None:
        """Mismatched list lengths should use min length without error."""
        agent = [0.6, 0.7, 0.8]
        baseline = [0.5, 0.5]
        result = bootstrap_paired_delta(agent, baseline, n_bootstrap=100, seed=0)
        assert result.n_samples == 2

    def test_identical_scores_delta_is_zero(self) -> None:
        """Zero delta between identical agent and baseline scores."""
        scores = [0.5, 0.6, 0.7, 0.8]
        result = bootstrap_paired_delta(scores, scores, n_bootstrap=500, seed=0)
        assert result.mean == pytest.approx(0.0)
        assert result.ci_lower == pytest.approx(0.0)
        assert result.ci_upper == pytest.approx(0.0)

    def test_returns_bootstrap_ci_instance(self) -> None:
        """Return type must be BootstrapCI."""
        result = bootstrap_paired_delta([0.6, 0.7], [0.5, 0.5], n_bootstrap=100, seed=0)
        assert isinstance(result, BootstrapCI)

    def test_seed_reproducibility(self) -> None:
        """Same seed produces same result."""
        agent = [0.6, 0.7, 0.8, 0.75]
        baseline = [0.5, 0.5, 0.6, 0.55]
        r1 = bootstrap_paired_delta(agent, baseline, n_bootstrap=500, seed=7)
        r2 = bootstrap_paired_delta(agent, baseline, n_bootstrap=500, seed=7)
        assert r1 == r2
