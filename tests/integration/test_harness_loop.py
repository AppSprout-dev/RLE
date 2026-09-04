"""RLEGameLoop driven by non-Felix harnesses (the swappable-harness contract)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import ClassVar

from rle.agents.actions import Action, ActionPlan
from rle.config import RLEConfig
from rle.harness import BaseHarness, HarnessStepError, StepResult
from rle.harness.baseline import BaselineHarness
from rle.orchestration.action_executor import ActionOutcome, ExecutionResult
from rle.orchestration.game_loop import RLEGameLoop
from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent
from rle.scoring.composite import CompositeScorer
from rle.scoring.metrics import NEUTRAL
from rle.scoring.recorder import TimeSeriesRecorder
from rle.testing import MockRimAPI
from rle.tracking.event_log import EventLog, EventType


@asynccontextmanager
async def _client() -> AsyncIterator[RimAPIClient]:
    async with RimAPIClient("http://mock") as client:
        MockRimAPI().attach(client)
        yield client


class _ScriptedHarness(BaseHarness):
    """Proposes one work_priority write per tick; the loop executes it."""

    name: ClassVar[str] = "scripted"

    def __init__(self) -> None:
        super().__init__()
        self.seen_events: list[list[RimAPIEvent]] = []
        self.tick_ends: list[float | None] = []

    async def step(
        self, state: GameState, tick: int, macro_time: float, events: list[RimAPIEvent],
    ) -> StepResult:
        self.seen_events.append(events)
        plan = ActionPlan(
            role="scripted", tick=state.colony.tick,
            actions=[Action(
                action_type="work_priority", target_colonist_id="col_01",
                parameters={"Growing": 1}, reason="script",
            )],
        )
        self.parse_successes += 1
        return StepResult(plan=plan, proposals=(plan,), extras={"phase": "scripted"})

    async def on_tick_end(self, tick, state, step, execution, score) -> None:  # type: ignore[no-untyped-def]
        self.tick_ends.append(score.composite if score else None)


class _PreExecutedHarness(BaseHarness):
    """Applies its own writes (MCP-style) and reports the execution back."""

    name: ClassVar[str] = "pre-executed"

    async def step(
        self, state: GameState, tick: int, macro_time: float, events: list[RimAPIEvent],
    ) -> StepResult:
        outcomes = (
            ActionOutcome(
                action_type="draft", endpoint="draft", target_colonist_id="col_01",
                success=True, parameters={"is_drafted": True},
            ),
            ActionOutcome(
                action_type="draft", endpoint="draft", target_colonist_id="col_01",
                success=True, parameters={"is_drafted": False},
            ),
        )
        plan = ActionPlan(role="pre-executed", tick=state.colony.tick, actions=[])
        return StepResult(
            plan=plan,
            execution=ExecutionResult(executed=2, failed=0, total=2, outcomes=outcomes),
        )


class _FlakyHarness(BaseHarness):
    name: ClassVar[str] = "flaky"

    async def step(self, state, tick, macro_time, events):  # type: ignore[no-untyped-def]
        raise HarnessStepError("upstream agent crashed")


class _SlowHarness(BaseHarness):
    name: ClassVar[str] = "slow"

    async def step(self, state, tick, macro_time, events):  # type: ignore[no-untyped-def]
        await asyncio.sleep(5)
        raise AssertionError("should have timed out")


class TestScriptedHarness:
    async def test_loop_executes_harness_plan(self) -> None:
        harness = _ScriptedHarness()
        async with _client() as client:
            loop = RLEGameLoop(
                RLEConfig(tick_interval=0.0), client, harness=harness,
                scorer=CompositeScorer(), recorder=TimeSeriesRecorder(),
            )
            results = await loop.run(max_ticks=2)

        assert len(results) == 2
        assert all(r.harness == "scripted" for r in results)
        assert results[0].execution.executed == 1
        assert results[0].extras == {"phase": "scripted"}
        assert harness.tick_ends and harness.tick_ends[0] is not None
        assert loop.parse_successes == 2
        assert len(harness.seen_events) == 2

    async def test_dashboard_export_is_harness_neutral(self, tmp_path: Path) -> None:
        async with _client() as client:
            loop = RLEGameLoop(
                RLEConfig(tick_interval=0.0), client, harness=_ScriptedHarness(),
                dashboard_export_dir=tmp_path,
            )
            await loop.run_tick()
        data = json.loads((tmp_path / "latest_tick.json").read_text())
        assert data["harness"] == "scripted"
        assert data["phase"] == "scripted"
        assert len(data["agents"]) == 1
        assert data["extras"] == {"phase": "scripted"}


class TestPreExecutedHarness:
    async def test_loop_skips_executor_and_scores_coherence(self) -> None:
        async with _client() as client:
            loop = RLEGameLoop(
                RLEConfig(tick_interval=0.0), client, harness=_PreExecutedHarness(),
                scorer=CompositeScorer(),
            )
            await loop.run_tick()
            second = await loop.run_tick()

        # Execution came from the harness untouched
        assert second.execution.executed == 2
        # Tick 2 scores tick 1's contradictory draft/undraft: coherence 0.0
        assert second.score is not None
        assert second.score.metrics["plan_coherence"] == 0.0
        assert second.score.metrics["efficiency"] == 1.0


class TestBaselineThroughLoop:
    async def test_baseline_neutral_process_metrics(self) -> None:
        async with _client() as client:
            loop = RLEGameLoop(
                RLEConfig(tick_interval=0.0), client, harness=BaselineHarness(),
                scorer=CompositeScorer(),
            )
            await loop.run_tick()
            second = await loop.run_tick()
        assert second.score is not None
        assert second.score.metrics["efficiency"] == NEUTRAL
        assert second.score.metrics["plan_coherence"] == NEUTRAL

    async def test_legacy_no_agent_flag_still_works(self) -> None:
        async with _client() as client:
            loop = RLEGameLoop(RLEConfig(tick_interval=0.0), client, no_agent=True)
            result = await loop.run_tick()
        assert loop.harness.name == "baseline"
        assert result.plan.actions == []


class TestHarnessFailures:
    async def test_step_error_degrades_to_empty_tick(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        async with _client() as client:
            loop = RLEGameLoop(
                RLEConfig(tick_interval=0.0), client, harness=_FlakyHarness(), event_log=log,
            )
            result = await loop.run_tick()
        assert result.plan.actions == []
        errors = [e for e in log.events if e.event_type == EventType.ERROR]
        assert errors and errors[0].data["error_type"] == "harness_error"

    async def test_step_timeout_degrades_to_empty_tick(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        async with _client() as client:
            loop = RLEGameLoop(
                RLEConfig(tick_interval=0.0, tick_timeout_s=0.05), client,
                harness=_SlowHarness(), event_log=log,
            )
            result = await loop.run_tick()
        assert result.plan.actions == []
        errors = [e for e in log.events if e.event_type == EventType.ERROR]
        assert errors and errors[0].data["error_type"] == "harness_timeout"

    async def test_harness_and_agents_are_exclusive(self) -> None:
        async with _client() as client:
            try:
                RLEGameLoop(
                    RLEConfig(tick_interval=0.0), client, [object()], harness=BaselineHarness(),
                )
            except ValueError as exc:
                assert "not both" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("expected ValueError")
