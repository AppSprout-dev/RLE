"""Tests for the RIMAPI SSE client."""

from __future__ import annotations

import json
import time

from rle.rimapi.sse_client import (
    ALL_EVENTS,
    COLONIST_EVENTS,
    INCIDENT_EVENTS,
    MAP_EVENTS,
    SYSTEM_EVENTS,
    RimAPIEvent,
    RimAPISSEClient,
)

# ------------------------------------------------------------------
# RimAPIEvent
# ------------------------------------------------------------------


class TestRimAPIEvent:
    def test_create_event(self) -> None:
        event = RimAPIEvent("letter_received", {"type": "raid"}, 1700000000.0)
        assert event.event_type == "letter_received"
        assert event.data == {"type": "raid"}
        assert event.timestamp == 1700000000.0

    def test_repr(self) -> None:
        event = RimAPIEvent("colonist_died", {"pawn_id": 123}, 0.0)
        assert "colonist_died" in repr(event)

    def test_event_type_sets(self) -> None:
        assert "letter_received" in INCIDENT_EVENTS
        assert "colonist_died" in COLONIST_EVENTS
        assert "pawn_killed" in MAP_EVENTS
        assert "heartbeat" in SYSTEM_EVENTS
        combined = INCIDENT_EVENTS | COLONIST_EVENTS | MAP_EVENTS | SYSTEM_EVENTS
        assert len(ALL_EVENTS) == len(combined)


# ------------------------------------------------------------------
# RimAPISSEClient — buffer operations
# ------------------------------------------------------------------


class TestSSEClientBuffer:
    def test_initial_state(self) -> None:
        sse = RimAPISSEClient()
        assert sse.buffer_size == 0
        assert not sse.is_running
        assert sse.drain() == []

    def test_drain_returns_and_clears(self) -> None:
        sse = RimAPISSEClient()
        # Manually push events into buffer
        sse._buffer.append(RimAPIEvent("heartbeat", {"tick": 100}, time.time()))
        sse._buffer.append(RimAPIEvent("letter_received", {"type": "raid"}, time.time()))
        assert sse.buffer_size == 2

        events = sse.drain()
        assert len(events) == 2
        assert sse.buffer_size == 0
        assert events[0].event_type == "heartbeat"
        assert events[1].event_type == "letter_received"

    def test_drain_by_type(self) -> None:
        sse = RimAPISSEClient()
        sse._buffer.append(RimAPIEvent("heartbeat", {}, time.time()))
        sse._buffer.append(RimAPIEvent("letter_received", {"type": "raid"}, time.time()))
        sse._buffer.append(RimAPIEvent("colonist_died", {"pawn": 1}, time.time()))
        sse._buffer.append(RimAPIEvent("heartbeat", {}, time.time()))

        incidents = sse.drain_by_type("letter_received", "colonist_died")
        assert len(incidents) == 2
        assert incidents[0].event_type == "letter_received"
        assert incidents[1].event_type == "colonist_died"
        # Heartbeats remain
        assert sse.buffer_size == 2

    def test_max_buffer_evicts_oldest(self) -> None:
        sse = RimAPISSEClient(max_buffer=3)
        for i in range(5):
            sse._buffer.append(RimAPIEvent("heartbeat", {"i": i}, time.time()))
        assert sse.buffer_size == 3
        events = sse.drain()
        assert events[0].data["i"] == 2  # oldest surviving is index 2

    def test_stop(self) -> None:
        sse = RimAPISSEClient()
        sse._running = True
        assert sse.is_running
        sse.stop()
        assert not sse.is_running


# ------------------------------------------------------------------
# Callbacks
# ------------------------------------------------------------------


class TestSSECallbacks:
    def test_on_callback_fires(self) -> None:
        sse = RimAPISSEClient()
        received: list[RimAPIEvent] = []
        sse.on("letter_received", received.append)

        sse._handle_event("letter_received", json.dumps({"type": "raid"}))
        assert len(received) == 1
        assert received[0].event_type == "letter_received"
        # Also buffered
        assert sse.buffer_size == 1

    def test_callback_for_different_type_not_fired(self) -> None:
        sse = RimAPISSEClient()
        received: list[RimAPIEvent] = []
        sse.on("colonist_died", received.append)

        sse._handle_event("heartbeat", json.dumps({"tick": 1}))
        assert len(received) == 0

    def test_multiple_callbacks(self) -> None:
        sse = RimAPISSEClient()
        a: list[str] = []
        b: list[str] = []
        sse.on("letter_received", lambda e: a.append(e.event_type))
        sse.on("letter_received", lambda e: b.append(e.event_type))

        sse._handle_event("letter_received", json.dumps({}))
        assert len(a) == 1
        assert len(b) == 1

    def test_callback_error_does_not_crash(self) -> None:
        sse = RimAPISSEClient()

        def bad_cb(event: RimAPIEvent) -> None:
            raise ValueError("oops")

        sse.on("heartbeat", bad_cb)
        # Should not raise
        sse._handle_event("heartbeat", json.dumps({"tick": 1}))
        assert sse.buffer_size == 1


# ------------------------------------------------------------------
# Event parsing
# ------------------------------------------------------------------


class TestSSEEventParsing:
    def test_valid_json(self) -> None:
        sse = RimAPISSEClient()
        sse._handle_event("letter_received", json.dumps({"type": "raid", "faction": "pirate"}))
        events = sse.drain()
        assert events[0].data == {"type": "raid", "faction": "pirate"}

    def test_invalid_json_falls_back(self) -> None:
        sse = RimAPISSEClient()
        sse._handle_event("error", "not valid json {{{")
        events = sse.drain()
        assert events[0].data == {"raw": "not valid json {{{"}
