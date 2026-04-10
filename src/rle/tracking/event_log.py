"""Structured event logging for RLE benchmark observability.

Produces a single append-only JSONL file per benchmark run capturing every
significant event. This is the offline source of truth — works everywhere
with no dependencies. W&B Weave provides optional rich visualization on top.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class EventType(str, Enum):
    """Categories of benchmark events."""

    TICK_START = "tick_start"
    STATE_REFRESH = "state_refresh"
    DELIBERATION = "deliberation"
    CONFLICT = "conflict"
    ACTION_EXEC = "action_exec"
    SCORE = "score"
    SSE_EVENT = "sse_event"
    ERROR = "error"
    PROVIDER_CALL = "provider_call"


class Event(BaseModel):
    """A single benchmark event."""

    model_config = ConfigDict(frozen=True)

    timestamp: float
    tick: int
    event_type: EventType
    agent: str | None = None
    data: dict[str, Any]


class RunSummary(BaseModel):
    """Aggregate statistics from an EventLog — the CI artifact."""

    model_config = ConfigDict(frozen=True)

    total_events: int
    errors_by_type: dict[str, int]
    avg_deliberation_ms: float
    action_success_rate: float
    total_tokens: int
    estimated_cost_usd: float


class EventLog:
    """Append-only JSONL event logger for benchmark runs."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._events: list[Event] = []
        self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115
        self._lock = threading.Lock()

    def emit(
        self,
        event_type: EventType,
        tick: int,
        agent: str | None = None,
        **data: Any,
    ) -> None:
        """Record an event. Thread-safe — writes immediately to JSONL file."""
        event = Event(
            timestamp=time.time(),
            tick=tick,
            event_type=event_type,
            agent=agent,
            data=data,
        )
        with self._lock:
            self._events.append(event)
            self._file.write(event.model_dump_json() + "\n")
            self._file.flush()

    def summary(self) -> RunSummary:
        """Compute aggregate statistics from recorded events."""
        error_counter: Counter[str] = Counter()
        deliberation_latencies: list[float] = []
        action_successes = 0
        action_total = 0
        total_tokens = 0
        total_cost = 0.0

        for event in self._events:
            if event.event_type == EventType.ERROR:
                error_counter[str(event.data.get("error_type", "unknown"))] += 1
            elif event.event_type == EventType.DELIBERATION:
                latency = event.data.get("latency_ms")
                if isinstance(latency, (int, float)):
                    deliberation_latencies.append(float(latency))
            elif event.event_type == EventType.ACTION_EXEC:
                action_total += 1
                if event.data.get("success"):
                    action_successes += 1
            elif event.event_type == EventType.PROVIDER_CALL:
                pt = event.data.get("prompt_tokens", 0)
                ct = event.data.get("completion_tokens", 0)
                if isinstance(pt, int) and isinstance(ct, int):
                    total_tokens += pt + ct
                cost = event.data.get("estimated_cost", 0.0)
                if isinstance(cost, (int, float)):
                    total_cost += float(cost)

        avg_latency = (
            sum(deliberation_latencies) / len(deliberation_latencies)
            if deliberation_latencies
            else 0.0
        )
        success_rate = (
            action_successes / action_total if action_total > 0 else 1.0
        )

        return RunSummary(
            total_events=len(self._events),
            errors_by_type=dict(error_counter),
            avg_deliberation_ms=round(avg_latency, 2),
            action_success_rate=round(success_rate, 4),
            total_tokens=total_tokens,
            estimated_cost_usd=round(total_cost, 6),
        )

    def close(self) -> None:
        """Flush and close the log file."""
        if not self._file.closed:
            self._file.flush()
            self._file.close()

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    @property
    def path(self) -> Path:
        return self._path

    def __enter__(self) -> EventLog:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()
