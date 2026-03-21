"""Tests for GameStateManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from rle.orchestration.state_manager import GameStateManager
from rle.rimapi.schemas import GameState


class TestRefresh:
    async def test_returns_game_state(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state
        mgr = GameStateManager(client)
        state = await mgr.refresh()
        assert state is sample_game_state
        client.get_game_state.assert_awaited_once()

    async def test_caches_current(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state
        mgr = GameStateManager(client)
        await mgr.refresh()
        assert mgr.current is sample_game_state

    async def test_appends_to_history(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state
        mgr = GameStateManager(client)
        await mgr.refresh()
        await mgr.refresh()
        assert len(mgr.history) == 2


class TestMacroTime:
    async def test_calculation(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state
        # sample_game_state.colony.day = 12, expected_duration = 60
        mgr = GameStateManager(client, expected_duration_days=60)
        await mgr.refresh()
        assert mgr.macro_time == pytest.approx(12 / 60)

    async def test_clamped_at_one(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state
        # day=12, expected=5 → 12/5 = 2.4, clamped to 1.0
        mgr = GameStateManager(client, expected_duration_days=5)
        await mgr.refresh()
        assert mgr.macro_time == 1.0

    def test_zero_before_refresh(self) -> None:
        client = MagicMock()
        mgr = GameStateManager(client)
        assert mgr.macro_time == 0.0


class TestCurrent:
    def test_raises_before_refresh(self) -> None:
        client = MagicMock()
        mgr = GameStateManager(client)
        with pytest.raises(RuntimeError, match="No state fetched"):
            _ = mgr.current


class TestHistoryCap:
    async def test_capped_at_50(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state
        mgr = GameStateManager(client)
        for _ in range(55):
            await mgr.refresh()
        assert len(mgr.history) == 50


class TestSSEIntegration:
    async def test_no_sse_client_means_empty_events(
        self, sample_game_state: GameState,
    ) -> None:
        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state
        mgr = GameStateManager(client)
        await mgr.refresh()
        assert mgr.pending_events == []
        assert not mgr.has_event("letter_received")

    async def test_drains_sse_on_refresh(
        self, sample_game_state: GameState,
    ) -> None:
        from rle.rimapi.sse_client import RimAPIEvent, RimAPISSEClient

        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state

        sse = RimAPISSEClient()
        sse._buffer.append(RimAPIEvent("letter_received", {"type": "raid"}, 1.0))
        sse._buffer.append(RimAPIEvent("colonist_died", {"pawn": 1}, 2.0))

        mgr = GameStateManager(client, sse_client=sse)
        await mgr.refresh()

        assert len(mgr.pending_events) == 2
        assert mgr.has_event("letter_received")
        assert mgr.has_event("colonist_died")
        assert not mgr.has_event("heartbeat")
        # Buffer drained
        assert sse.buffer_size == 0

    async def test_get_events_filters(
        self, sample_game_state: GameState,
    ) -> None:
        from rle.rimapi.sse_client import RimAPIEvent, RimAPISSEClient

        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state

        sse = RimAPISSEClient()
        sse._buffer.append(RimAPIEvent("heartbeat", {}, 1.0))
        sse._buffer.append(RimAPIEvent("letter_received", {"type": "raid"}, 2.0))
        sse._buffer.append(RimAPIEvent("heartbeat", {}, 3.0))

        mgr = GameStateManager(client, sse_client=sse)
        await mgr.refresh()

        incidents = mgr.get_events("letter_received")
        assert len(incidents) == 1
        assert incidents[0].event_type == "letter_received"

    async def test_events_reset_each_refresh(
        self, sample_game_state: GameState,
    ) -> None:
        from rle.rimapi.sse_client import RimAPIEvent, RimAPISSEClient

        client = AsyncMock()
        client.get_game_state.return_value = sample_game_state

        sse = RimAPISSEClient()
        sse._buffer.append(RimAPIEvent("colonist_died", {}, 1.0))

        mgr = GameStateManager(client, sse_client=sse)
        await mgr.refresh()
        assert len(mgr.pending_events) == 1

        # Second refresh with no new events
        await mgr.refresh()
        assert len(mgr.pending_events) == 0
