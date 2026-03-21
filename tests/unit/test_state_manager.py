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
