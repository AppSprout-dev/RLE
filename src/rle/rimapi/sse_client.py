"""Async SSE (Server-Sent Events) client for real-time RIMAPI events."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


class RimAPIEvent:
    """A single SSE event received from RIMAPI."""

    __slots__ = ("event_type", "data", "timestamp")

    def __init__(self, event_type: str, data: dict[str, Any], timestamp: float) -> None:
        self.event_type = event_type
        self.data = data
        self.timestamp = timestamp

    def __repr__(self) -> str:
        return f"RimAPIEvent({self.event_type!r}, keys={list(self.data.keys())})"


# Event types published by RIMAPI Harmony hooks.
INCIDENT_EVENTS = frozenset({"letter_received", "message_received"})
COLONIST_EVENTS = frozenset({
    "colonist_ate",
    "colonist_crafted",
    "colonist_bill_work",
    "colonist_died",
    "colonist_mental_break",
})
MAP_EVENTS = frozenset({"pawn_entered_map", "pawn_killed", "plant_harvested"})
SYSTEM_EVENTS = frozenset({"game_state", "heartbeat", "connected", "error", "log_message"})
ALL_EVENTS = INCIDENT_EVENTS | COLONIST_EVENTS | MAP_EVENTS | SYSTEM_EVENTS


class RimAPISSEClient:
    """Async SSE listener for RIMAPI event stream.

    Connects to ``/api/v1/events`` and buffers incoming events in a
    thread-safe deque.  The game loop drains the buffer each tick.

    Usage::

        sse = RimAPISSEClient("http://localhost:8765")
        task = asyncio.create_task(sse.listen())
        ...
        events = sse.drain()  # returns list of RimAPIEvent
        ...
        sse.stop()
        await task
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8765",
        max_buffer: int = 500,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._buffer: deque[RimAPIEvent] = deque(maxlen=max_buffer)
        self._running = False
        self._callbacks: dict[str, list[Callable[[RimAPIEvent], None]]] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    def on(self, event_type: str, callback: Callable[[RimAPIEvent], None]) -> None:
        """Register a callback for a specific event type."""
        self._callbacks.setdefault(event_type, []).append(callback)

    def drain(self) -> list[RimAPIEvent]:
        """Return and clear all buffered events."""
        events = list(self._buffer)
        self._buffer.clear()
        return events

    def drain_by_type(self, *event_types: str) -> list[RimAPIEvent]:
        """Drain only events matching the given types, leave others buffered."""
        matched = []
        remaining: deque[RimAPIEvent] = deque(maxlen=self._buffer.maxlen)
        for event in self._buffer:
            if event.event_type in event_types:
                matched.append(event)
            else:
                remaining.append(event)
        self._buffer = remaining
        return matched

    def stop(self) -> None:
        """Signal the listener to stop."""
        self._running = False

    async def listen(self) -> None:
        """Connect to SSE stream and buffer events until stopped.

        Reconnects automatically on connection loss with exponential backoff.
        """
        self._running = True
        backoff = 1.0

        while self._running:
            try:
                await self._stream()
                backoff = 1.0  # reset on clean disconnect
            except httpx.ConnectError:
                logger.warning(
                    "SSE connection failed, retrying in %.1fs", backoff,
                )
            except httpx.ReadError:
                logger.warning(
                    "SSE stream interrupted, reconnecting in %.1fs", backoff,
                )
            except Exception:
                logger.exception("SSE unexpected error, retrying in %.1fs", backoff)

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _stream(self) -> None:
        """Open a single SSE connection and process events."""
        url = f"{self._base_url}/api/v1/events"
        logger.info("SSE connecting to %s", url)

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.error("SSE endpoint returned %d", resp.status_code)
                    return

                logger.info("SSE connected")
                event_type = ""
                data_lines: list[str] = []

                async for line in resp.aiter_lines():
                    if not self._running:
                        break

                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                    elif line.startswith("data: "):
                        data_lines.append(line[6:])
                    elif line == "":
                        # Empty line = end of event
                        if event_type and data_lines:
                            raw = "\n".join(data_lines)
                            self._handle_event(event_type, raw)
                        event_type = ""
                        data_lines = []

    def _handle_event(self, event_type: str, raw_data: str) -> None:
        """Parse and buffer a single event."""
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            data = {"raw": raw_data}

        event = RimAPIEvent(event_type, data, time.time())
        self._buffer.append(event)

        # Fire callbacks
        for cb in self._callbacks.get(event_type, []):
            try:
                cb(event)
            except Exception:
                logger.exception("SSE callback error for %s", event_type)

        if event_type not in SYSTEM_EVENTS:
            logger.debug("SSE event: %s", event_type)
