"""Tests for the CostTracker module."""

from __future__ import annotations

import json
import time
import unittest.mock as mock

import httpx
import pytest

from rle.tracking.cost_tracker import (
    CostSnapshot,
    CostTracker,
    TokenUsage,
    create_cost_tracker,
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
