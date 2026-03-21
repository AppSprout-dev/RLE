"""Game state manager — fetches, caches, and derives values from RIMAPI state."""

from __future__ import annotations

from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import GameState


class GameStateManager:
    """Thin wrapper around RimAPIClient that caches state and computes macro time."""

    def __init__(
        self, client: RimAPIClient, expected_duration_days: int = 60,
    ) -> None:
        self._client = client
        self._expected_duration_days = expected_duration_days
        self._current_state: GameState | None = None
        self._history: list[GameState] = []

    async def refresh(self) -> GameState:
        """Fetch fresh state from RIMAPI, cache it, append to history."""
        self._current_state = await self._client.get_game_state()
        self._history.append(self._current_state)
        if len(self._history) > 50:
            self._history.pop(0)
        return self._current_state

    @property
    def current(self) -> GameState:
        """Most recently fetched state. Raises if never refreshed."""
        if self._current_state is None:
            raise RuntimeError("No state fetched yet — call refresh() first")
        return self._current_state

    @property
    def macro_time(self) -> float:
        """Helix macro time: min(1.0, game_day / expected_duration_days)."""
        if self._current_state is None:
            return 0.0
        return min(1.0, self._current_state.colony.day / self._expected_duration_days)

    @property
    def history(self) -> list[GameState]:
        return list(self._history)
