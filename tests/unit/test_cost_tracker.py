"""Tests for the CostTracker module."""

from __future__ import annotations

import json
import time
import unittest.mock as mock

import httpx
import pytest

from rle.tracking.cost_tracker import (
    BilledCostReport,
    CostSnapshot,
    CostTracker,
    TokenUsage,
    create_cost_tracker,
    fetch_billed_costs,
    fetch_pricing,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_openrouter_response(models: list[dict]) -> httpx.Response:
    data = json.dumps({"data": models}).encode()
    return httpx.Response(
        status_code=200,
        content=data,
        headers={"content-type": "application/json"},
    )


def _make_transport_with_response(response: httpx.Response) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return httpx.MockTransport(handler)


def _make_error_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    return httpx.MockTransport(handler)


def _mock_async_client(transport: httpx.MockTransport) -> mock.MagicMock:
    """Build a mock AsyncClient context manager backed by the given transport."""
    real_client = httpx.AsyncClient(transport=transport)
    cm = mock.MagicMock()
    cm.__aenter__ = mock.AsyncMock(return_value=real_client)
    cm.__aexit__ = mock.AsyncMock(return_value=False)
    return cm


# ------------------------------------------------------------------
# TokenUsage tests
# ------------------------------------------------------------------


class TestTokenUsage:
    def test_total_tokens(self) -> None:
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50)
        assert usage.total_tokens == 150

    def test_total_tokens_includes_reasoning(self) -> None:
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, reasoning_tokens=200)
        assert usage.total_tokens == 350
        assert usage.billable_completion_tokens == 250

    def test_reasoning_defaults_to_zero(self) -> None:
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50)
        assert usage.reasoning_tokens == 0
        assert usage.billable_completion_tokens == 50

    def test_frozen(self) -> None:
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        with pytest.raises(Exception):
            usage.prompt_tokens = 99  # type: ignore[misc]


# ------------------------------------------------------------------
# CostTracker.record tests
# ------------------------------------------------------------------


class TestCostTrackerRecord:
    def test_record_accumulates_tokens(self) -> None:
        tracker = CostTracker("test-model", prompt_price=0.0, completion_price=0.0)
        tracker.record(TokenUsage(prompt_tokens=100, completion_tokens=50))
        tracker.record(TokenUsage(prompt_tokens=200, completion_tokens=75))

        snap = tracker.snapshot()
        assert snap.total_prompt_tokens == 300
        assert snap.total_completion_tokens == 125
        assert snap.total_tokens == 425
        assert snap.num_calls == 2

    def test_record_raw_works_as_convenience(self) -> None:
        tracker = CostTracker("test-model")
        tracker.record_raw(prompt_tokens=80, completion_tokens=40)
        tracker.record_raw(prompt_tokens=120, completion_tokens=60)

        snap = tracker.snapshot()
        assert snap.total_prompt_tokens == 200
        assert snap.total_completion_tokens == 100
        assert snap.num_calls == 2

    def test_record_accumulates_reasoning_tokens(self) -> None:
        tracker = CostTracker("test-model")
        tracker.record(TokenUsage(prompt_tokens=100, completion_tokens=50, reasoning_tokens=300))
        tracker.record_raw(prompt_tokens=100, completion_tokens=50, reasoning_tokens=200)

        snap = tracker.snapshot()
        assert snap.total_reasoning_tokens == 500
        # total_tokens folds reasoning in: (100+50) + (100+50) + 500
        assert snap.total_tokens == 800

    def test_record_and_record_raw_combined(self) -> None:
        tracker = CostTracker("test-model")
        tracker.record(TokenUsage(prompt_tokens=50, completion_tokens=25))
        tracker.record_raw(prompt_tokens=50, completion_tokens=25)

        snap = tracker.snapshot()
        assert snap.total_prompt_tokens == 100
        assert snap.total_completion_tokens == 50
        assert snap.num_calls == 2


# ------------------------------------------------------------------
# CostTracker.snapshot cost calculation tests
# ------------------------------------------------------------------


class TestCostTrackerSnapshot:
    def test_snapshot_computes_cost_correctly(self) -> None:
        tracker = CostTracker(
            "some-model",
            prompt_price=0.000005,
            completion_price=0.000025,
        )
        tracker.record(TokenUsage(prompt_tokens=1000, completion_tokens=500))

        snap = tracker.snapshot()
        # 1000 * 0.000005 + 500 * 0.000025 = 0.005 + 0.0125 = 0.0175
        assert snap.estimated_cost_usd == pytest.approx(0.0175, rel=1e-5)

    def test_reasoning_tokens_billed_at_completion_rate(self) -> None:
        tracker = CostTracker(
            "thinking-model",
            prompt_price=0.000005,
            completion_price=0.000025,
        )
        tracker.record(
            TokenUsage(prompt_tokens=1000, completion_tokens=500, reasoning_tokens=4000)
        )

        snap = tracker.snapshot()
        # prompt: 1000 * 5e-6 = 0.005
        # completion + reasoning: (500 + 4000) * 25e-6 = 0.1125
        assert snap.estimated_cost_usd == pytest.approx(0.1175, rel=1e-5)

    def test_snapshot_zero_cost_with_default_prices(self) -> None:
        tracker = CostTracker("free-model")
        tracker.record(TokenUsage(prompt_tokens=10000, completion_tokens=5000))

        snap = tracker.snapshot()
        assert snap.estimated_cost_usd == 0.0

    def test_snapshot_is_frozen_pydantic_model(self) -> None:
        tracker = CostTracker("model")
        snap = tracker.snapshot()
        assert isinstance(snap, CostSnapshot)
        with pytest.raises(Exception):
            snap.num_calls = 99  # type: ignore[misc]

    def test_snapshot_returns_correct_total_tokens(self) -> None:
        tracker = CostTracker("model", prompt_price=0.001, completion_price=0.002)
        tracker.record_raw(500, 250)

        snap = tracker.snapshot()
        assert snap.total_tokens == 750

    def test_wall_time_increases_over_time(self) -> None:
        tracker = CostTracker("model")
        snap1 = tracker.snapshot()
        time.sleep(0.05)
        snap2 = tracker.snapshot()
        assert snap2.wall_time_s >= snap1.wall_time_s


# ------------------------------------------------------------------
# Generation-ID accumulation (billed-cost reconciliation)
# ------------------------------------------------------------------


class TestGenerationIds:
    def test_records_in_order(self) -> None:
        tracker = CostTracker("model")
        tracker.record_generation_id("gen-1")
        tracker.record_generation_id("gen-2")
        assert tracker.generation_ids == ["gen-1", "gen-2"]

    def test_ignores_none_and_empty(self) -> None:
        tracker = CostTracker("model")
        tracker.record_generation_id(None)
        tracker.record_generation_id("")
        tracker.record_generation_id("gen-1")
        assert tracker.generation_ids == ["gen-1"]

    def test_property_returns_copy(self) -> None:
        tracker = CostTracker("model")
        tracker.record_generation_id("gen-1")
        ids = tracker.generation_ids
        ids.append("gen-tampered")
        assert tracker.generation_ids == ["gen-1"]


# ------------------------------------------------------------------
# fetch_billed_costs tests (OpenRouter /generation ground truth)
# ------------------------------------------------------------------


def _generation_transport(costs: dict[str, float | None]) -> httpx.MockTransport:
    """Transport serving /generation?id=... from a gen_id -> total_cost map.

    IDs absent from the map 404 (like OpenRouter does for unknown ids).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        gen_id = request.url.params.get("id")
        if gen_id not in costs:
            return httpx.Response(status_code=404, json={"error": "not found"})
        return httpx.Response(
            status_code=200, json={"data": {"id": gen_id, "total_cost": costs[gen_id]}},
        )

    return httpx.MockTransport(handler)


class TestFetchBilledCosts:
    async def test_empty_ids_returns_none(self) -> None:
        assert await fetch_billed_costs([], "key") is None

    async def test_sums_billed_costs(self) -> None:
        transport = _generation_transport({"gen-1": 0.012, "gen-2": 0.03, "gen-3": 0.0005})
        report = await fetch_billed_costs(
            ["gen-1", "gen-2", "gen-3"], "key",
            transport=transport, retry_delay_s=0.0,
        )
        assert report is not None
        assert report.billed_cost_usd == pytest.approx(0.0425)
        assert report.billed_generations == 3
        assert report.missing_generations == 0
        assert report.source == "openrouter_generation_api"

    async def test_missing_generation_counts_as_lower_bound(self) -> None:
        transport = _generation_transport({"gen-1": 0.01})
        report = await fetch_billed_costs(
            ["gen-1", "gen-unknown"], "key",
            transport=transport, retry_delay_s=0.0,
        )
        assert report is not None
        assert report.billed_cost_usd == pytest.approx(0.01)
        assert report.billed_generations == 1
        assert report.missing_generations == 1

    async def test_all_missing_returns_none(self) -> None:
        transport = _generation_transport({})
        report = await fetch_billed_costs(
            ["gen-a", "gen-b"], "key", transport=transport, retry_delay_s=0.0,
        )
        assert report is None

    async def test_null_total_cost_treated_as_free(self) -> None:
        transport = _generation_transport({"gen-free": None})
        report = await fetch_billed_costs(
            ["gen-free"], "key", transport=transport, retry_delay_s=0.0,
        )
        assert report is not None
        assert report.billed_cost_usd == 0.0
        assert report.billed_generations == 1

    async def test_connection_errors_count_as_missing(self) -> None:
        transport = _make_error_transport()
        report = await fetch_billed_costs(
            ["gen-1"], "key", transport=transport, retry_delay_s=0.0,
        )
        assert report is None

    async def test_sends_bearer_auth(self) -> None:
        seen_auth: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_auth.append(request.headers.get("authorization"))
            return httpx.Response(status_code=200, json={"data": {"total_cost": 0.01}})

        report = await fetch_billed_costs(
            ["gen-1"], "sk-or-test", transport=httpx.MockTransport(handler),
            retry_delay_s=0.0,
        )
        assert report is not None
        assert seen_auth == ["Bearer sk-or-test"]

    def test_report_is_frozen(self) -> None:
        report = BilledCostReport(
            billed_cost_usd=1.0, billed_generations=2, missing_generations=0,
        )
        with pytest.raises(Exception):
            report.billed_cost_usd = 9.9  # type: ignore[misc]


# ------------------------------------------------------------------
# fetch_pricing tests
# ------------------------------------------------------------------


class TestFetchPricing:
    async def test_returns_correct_prices_when_model_found(self) -> None:
        models = [
            {
                "id": "nvidia/nemotron-3-super-120b-a12b:free",
                "pricing": {"prompt": "0.000005", "completion": "0.000025"},
            }
        ]
        transport = _make_transport_with_response(_make_openrouter_response(models))
        with mock.patch("httpx.AsyncClient", return_value=_mock_async_client(transport)):
            result = await fetch_pricing("nvidia/nemotron-3-super-120b-a12b:free")

        assert result == (0.000005, 0.000025)

    async def test_falls_back_on_connection_error(self) -> None:
        transport = _make_error_transport()
        with mock.patch("httpx.AsyncClient", return_value=_mock_async_client(transport)):
            result = await fetch_pricing("some-model")

        assert result == (0.0, 0.0)

    async def test_falls_back_when_model_not_found(self) -> None:
        models = [{"id": "different/model", "pricing": {"prompt": "0.001", "completion": "0.002"}}]
        transport = _make_transport_with_response(_make_openrouter_response(models))
        with mock.patch("httpx.AsyncClient", return_value=_mock_async_client(transport)):
            result = await fetch_pricing("missing/model")

        assert result == (0.0, 0.0)

    async def test_falls_back_on_http_error(self) -> None:
        def error_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=500, content=b"Internal Server Error")

        transport = httpx.MockTransport(error_handler)
        with mock.patch("httpx.AsyncClient", return_value=_mock_async_client(transport)):
            result = await fetch_pricing("any/model")

        assert result == (0.0, 0.0)


# ------------------------------------------------------------------
# create_cost_tracker tests
# ------------------------------------------------------------------


class TestCreateCostTracker:
    async def test_wires_pricing_into_tracker(self) -> None:
        with mock.patch(
            "rle.tracking.cost_tracker.fetch_pricing",
            new=mock.AsyncMock(return_value=(0.000003, 0.000015)),
        ):
            tracker = await create_cost_tracker("test/model")

        assert isinstance(tracker, CostTracker)
        tracker.record_raw(1000, 500)
        snap = tracker.snapshot()
        # 1000 * 0.000003 + 500 * 0.000015 = 0.003 + 0.0075 = 0.0105
        assert snap.estimated_cost_usd == pytest.approx(0.0105, rel=1e-5)

    async def test_create_cost_tracker_uses_zero_on_fetch_failure(self) -> None:
        with mock.patch(
            "rle.tracking.cost_tracker.fetch_pricing",
            new=mock.AsyncMock(return_value=(0.0, 0.0)),
        ):
            tracker = await create_cost_tracker("unknown/model")

        tracker.record_raw(5000, 2000)
        snap = tracker.snapshot()
        assert snap.estimated_cost_usd == 0.0
        # A9: pricing_source flags this as untrustworthy
        assert snap.pricing_source == "unknown"

    async def test_pricing_source_is_openrouter_when_fetched_nonzero(
        self,
    ) -> None:
        with mock.patch(
            "rle.tracking.cost_tracker.fetch_pricing",
            new=mock.AsyncMock(return_value=(0.000003, 0.000015)),
        ):
            tracker = await create_cost_tracker("test/model")

        snap = tracker.snapshot()
        assert snap.pricing_source == "openrouter_api"
        assert snap.prompt_price_per_token == pytest.approx(0.000003)
        assert snap.completion_price_per_token == pytest.approx(0.000015)

    async def test_override_bypasses_fetch_and_tags_source(self) -> None:
        """A9: CLI overrides take precedence over OpenRouter pricing and
        the snapshot records pricing_source=override for reconciliation."""
        # Even if the fetch would return a different price, the override wins.
        with mock.patch(
            "rle.tracking.cost_tracker.fetch_pricing",
            new=mock.AsyncMock(return_value=(0.000001, 0.000002)),
        ) as patched:
            tracker = await create_cost_tracker(
                "test/model",
                prompt_price_override=0.00000009,
                completion_price_override=0.00000045,
            )

        # Fetch is skipped entirely when both overrides provided.
        patched.assert_not_awaited()
        snap = tracker.snapshot()
        assert snap.pricing_source == "override"
        assert snap.prompt_price_per_token == pytest.approx(0.00000009)
        assert snap.completion_price_per_token == pytest.approx(0.00000045)

    async def test_snapshot_carries_pricing_for_reconciliation(self) -> None:
        """Operators reconciling estimates against actual OpenRouter receipts
        need to see exactly which prices the tracker used."""
        with mock.patch(
            "rle.tracking.cost_tracker.fetch_pricing",
            new=mock.AsyncMock(return_value=(0.00000009, 0.00000045)),
        ):
            tracker = await create_cost_tracker(
                "nvidia/nemotron-3-super-120b-a12b",
            )

        tracker.record_raw(815347, 267898)
        snap = tracker.snapshot()
        expected = 815347 * 0.00000009 + 267898 * 0.00000045
        assert snap.estimated_cost_usd == pytest.approx(expected, abs=1e-4)
        assert snap.prompt_price_per_token == pytest.approx(0.00000009)
        assert snap.completion_price_per_token == pytest.approx(0.00000045)
        assert snap.pricing_source == "openrouter_api"
