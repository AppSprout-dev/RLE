"""Game state manager — fetches, caches, and derives values from RIMAPI state."""

from __future__ import annotations

from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent, RimAPISSEClient


class GameStateManager:
    """Thin wrapper around RimAPIClient that caches state and computes macro time.

    Optionally integrates an SSE client for real-time event awareness.
    """

    def __init__(
        self,
        client: RimAPIClient,
        expected_duration_days: int = 60,
        sse_client: RimAPISSEClient | None = None,
    ) -> None:
        self._client = client
        self._expected_duration_days = expected_duration_days
        self._current_state: GameState | None = None
        self._history: list[GameState] = []
        self._sse_client = sse_client
        self._pending_events: list[RimAPIEvent] = []

    async def refresh(self) -> GameState:
        """Fetch fresh state from RIMAPI, cache it, append to history.

        Also drains any buffered SSE events into ``pending_events``.
        """
        self._current_state = await self._client.get_game_state()
        self._history.append(self._current_state)
        if len(self._history) > 50:
            self._history.pop(0)
        # Drain SSE buffer each tick
        if self._sse_client is not None:
            self._pending_events = self._sse_client.drain()
        else:
            self._pending_events = []
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

    @property
    def pending_events(self) -> list[RimAPIEvent]:
        """SSE events received since last refresh. Empty if no SSE client."""
        return self._pending_events

    def has_event(self, *event_types: str) -> bool:
        """Check if any pending events match the given types."""
        return any(e.event_type in event_types for e in self._pending_events)

    def get_events(self, *event_types: str) -> list[RimAPIEvent]:
        """Filter pending events by type."""
        return [e for e in self._pending_events if e.event_type in event_types]
