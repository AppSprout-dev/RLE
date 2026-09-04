"""RLE game loop — the environment side of a run.

The loop owns the game: pause/unpause, state refresh, action execution,
scoring, scenario evaluation, dashboard export. Deciding *what* to do each
tick is delegated to a :class:`~rle.harness.protocol.BaseHarness`, so the same
loop benchmarks the Felix multi-agent stack, an unmanaged baseline, or an
external coding agent attached over MCP without knowing which one it has.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time as _time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from rle.agents.actions import ActionPlan, resolve_endpoint
from rle.config import RLEConfig
from rle.harness.compat import build_legacy_harness
from rle.harness.protocol import (
    BaseHarness,
    HarnessContext,
    HarnessStepError,
    StepResult,
)
from rle.orchestration.action_executor import ActionExecutor, ExecutionResult
from rle.orchestration.camera_director import CameraDirector
from rle.orchestration.state_manager import GameStateManager
from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPISSEClient
from rle.scenarios.evaluator import EvaluationResult, ScenarioEvaluator
from rle.scenarios.schema import ScenarioConfig, TriggeredIncident
from rle.scoring.composite import CompositeScorer, ScoreSnapshot
from rle.scoring.metrics import MetricContext
from rle.scoring.recorder import TimeSeriesRecorder
from rle.tracking.cost_tracker import CostTracker
from rle.tracking.event_log import EventLog, EventType

logger = logging.getLogger(__name__)


class TickResult(BaseModel):
    """Summary of a single game tick."""

    model_config = ConfigDict(frozen=True)

    tick: int
    day: int
    macro_time: float
    plan: ActionPlan
    execution: ExecutionResult
    score: ScoreSnapshot | None = None
    harness: str = ""
    step_latency_s: float = 0.0
    extras: dict[str, Any] = {}


class RLEGameLoop:
    """Turn-based loop: pause → read → harness.step → execute → score → unpause."""

    def __init__(
        self,
        config: RLEConfig,
        client: RimAPIClient,
        agents: Sequence[Any] | None = None,
        expected_duration_days: int = 60,
        scorer: CompositeScorer | None = None,
        recorder: TimeSeriesRecorder | None = None,
        evaluator: ScenarioEvaluator | None = None,
        initial_population: int = 3,
        initial_wealth: float = 0.0,
        visualizer: Any | None = None,
        parallel: bool = True,
        sse_client: RimAPISSEClient | None = None,
        dashboard_export_dir: Path | None = None,
        no_agent: bool = False,
        no_pause: bool = False,
        event_log: EventLog | None = None,
        cost_tracker: CostTracker | None = None,
        triggered_incidents: list[TriggeredIncident] | None = None,
        screenshots_enabled: bool = False,
        auto_dismiss_dialogs: bool = True,
        camera_director: CameraDirector | None = None,
        speed_keepalive_s: float = 10.0,
        *,
        harness: BaseHarness | None = None,
        harness_context: HarnessContext | None = None,
        scenario: ScenarioConfig | None = None,
    ) -> None:
        """``harness`` is the modern entry point (pass the ``harness_context``
        it was created with so both sides share one client/event log).
        ``agents`` / ``no_agent`` / ``parallel`` / ``visualizer`` are legacy
        arguments that build a Felix or baseline harness for you (see
        ``rle.harness.compat``)."""
        if harness is not None and agents:
            raise ValueError("Pass either harness= or the legacy agents= argument, not both")
        self._config = config
        self._client = client
        self._no_pause = no_pause
        self._state_manager = GameStateManager(client, expected_duration_days, sse_client)
        self._executor = ActionExecutor(client)
        self._scorer = scorer
        self._recorder = recorder
        self._evaluator = evaluator
        self._tick_results: list[TickResult] = []
        self._running = False
        self._evaluation_result: EvaluationResult | None = None
        self._metric_context = MetricContext(
            initial_population=initial_population,
            initial_wealth=initial_wealth,
        )
        self._dashboard_export_dir = dashboard_export_dir
        self._event_log = event_log
        self._cost_tracker = cost_tracker
        self._triggered_incidents = triggered_incidents or []
        self._screenshots_enabled = screenshots_enabled
        self._auto_dismiss_dialogs = auto_dismiss_dialogs
        self._camera_director = camera_director
        self._speed_keepalive_s = speed_keepalive_s

        self._harness: BaseHarness = harness or build_legacy_harness(
            agents,
            no_agent=no_agent,
            parallel=parallel,
            visualizer=visualizer,
            role_timeout_s=config.role_timeout_s,
        )
        if harness_context is None:
            harness_context = HarnessContext(
                config=config,
                client=client,
                expected_duration_days=expected_duration_days,
                initial_population=initial_population,
                scenario=scenario,
                event_log=event_log,
                cost_tracker=cost_tracker,
                tick_timeout_s=config.tick_timeout_s,
            )
        else:
            # The loop is authoritative for run-shaped facts the caller may
            # not have known when it built the context.
            harness_context.expected_duration_days = expected_duration_days
            harness_context.initial_population = initial_population
            if scenario is not None:
                harness_context.scenario = scenario
            if harness_context.event_log is None:
                harness_context.event_log = event_log
            if harness_context.cost_tracker is None:
                harness_context.cost_tracker = cost_tracker
        self._harness_ctx = harness_context
        self._setup_done = False

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def _emit(
        self, event_type: EventType, tick: int,
        agent: str | None = None, **data: object,
    ) -> None:
        """Emit an event if EventLog is configured. Thread-safe."""
        if self._event_log is not None:
            self._event_log.emit(event_type, tick, agent=agent, **data)

    @property
    def harness(self) -> BaseHarness:
        return self._harness

    @property
    def harness_context(self) -> HarnessContext:
        return self._harness_ctx

    @property
    def cost_tracker(self) -> CostTracker | None:
        return self._cost_tracker

    async def _ensure_setup(self) -> None:
        if not self._setup_done:
            await self._harness.setup(self._harness_ctx)
            self._setup_done = True

    async def _dismiss_blocking_dialogs(self, tick_num: int) -> None:
        """Close force-pause popups that stall unattended runs (issue #33).

        The colony-name dialog (Dialog_NamePlayerSettlement) force-pauses the
        game ~once per run; the dev-mode debug-log window auto-opens on RIMAPI
        errors and obscures footage. Both are dismissed every tick via RIMAPI's
        window/close endpoint. No-ops gracefully on older RIMAPI builds.
        """
        try:
            result = await self._client.close_windows(force_pause_only=True)
        except Exception:
            logger.debug("Dialog dismissal failed", exc_info=True)
            return
        closed = result.get("closed_windows") or []
        if closed:
            logger.info("Dismissed force-pause window(s): %s", ", ".join(closed))
            self._emit(
                EventType.TICK_START, tick_num, dismissed_windows=list(closed),
            )

    async def _step_harness(
        self, state: GameState, tick_num: int, macro_time: float,
    ) -> tuple[StepResult, float]:
        """Run the harness for one tick under the loop-level timeout.

        ``HarnessStepError`` and a timeout degrade to an empty step plus an
        ERROR event so a flaky harness produces a scored (bad) tick instead of
        aborting the run. Any other exception is a bug and propagates.
        """
        events = self._state_manager.pending_events
        empty = StepResult(
            plan=ActionPlan(
                role=self._harness.name, tick=state.colony.tick, actions=[],
                summary="harness produced no step",
            ),
        )
        t0 = _time.monotonic()
        timeout = self._harness_ctx.tick_timeout_s
        try:
            coro = self._harness.step(state, tick_num, macro_time, events)
            step = await (asyncio.wait_for(coro, timeout=timeout) if timeout else coro)
        except asyncio.TimeoutError:
            logger.warning(
                "Harness %s step timed out after %.1fs (tick %d)",
                self._harness.name, timeout or 0.0, tick_num,
            )
            self._emit(
                EventType.ERROR, tick_num, agent=self._harness.name,
                error_type="harness_timeout", timeout_s=timeout,
            )
            step = empty
        except HarnessStepError as exc:
            logger.warning(
                "Harness %s step failed (tick %d): %s", self._harness.name, tick_num, exc,
            )
            self._emit(
                EventType.ERROR, tick_num, agent=self._harness.name,
                error_type="harness_error", reason=str(exc),
            )
            step = empty
        return step, _time.monotonic() - t0

    def _export_tick_json(
        self, step: StepResult, exec_result: ExecutionResult, snapshot: ScoreSnapshot | None,
        tick: int, day: int, macro_time: float,
        screenshot_data_uri: str | None = None,
    ) -> None:
        """Write tick data as JSON for the rimapi-dashboard to consume.

        Harness-neutral schema: ``agents`` lists whatever sub-plans the harness
        reported (seven for Felix, one for a single agent, none for baseline);
        harness-specific telemetry rides in ``extras``.
        """
        if not self._dashboard_export_dir:
            return
        self._dashboard_export_dir.mkdir(parents=True, exist_ok=True)
        resolved = step.plan
        data = {
            "tick": tick,
            "day": day,
            "macro_time": macro_time,
            "harness": self._harness.name,
            "phase": str(step.extras.get("phase", "")),
            "agents": [
                {
                    "role": p.role,
                    "summary": p.summary,
                    "confidence": p.confidence,
                    "num_actions": len(p.actions),
                    "actions": [
                        {
                            "action_type": a.action_type,
                            "target": a.target_colonist_id,
                            "priority": a.priority,
                            "reason": a.reason,
                        }
                        for a in p.actions
                    ],
                }
                for p in step.proposals
            ],
            "resolved": {
                "role": resolved.role,
                "num_actions": len(resolved.actions),
                "actions": [
                    {
                        "action_type": a.action_type,
                        "target": a.target_colonist_id,
                        "priority": a.priority,
                    }
                    for a in resolved.actions
                ],
            },
            "execution": {
                "executed": exec_result.executed,
                "failed": exec_result.failed,
                "total": exec_result.total,
            },
            "score": {
                "composite": snapshot.composite,
                "metrics": snapshot.metrics,
            } if snapshot else None,
            "screenshot_data_uri": screenshot_data_uri,
            "extras": step.extras,
        }
        (self._dashboard_export_dir / "latest_tick.json").write_text(
            json.dumps(data, indent=2, default=str),
        )

    def _update_metric_context(
        self, result: TickResult, state: GameState, tick_num: int,
    ) -> None:
        """Append tick data to metric context for scoring history."""
        ctx = self._metric_context
        ctx.tick_results.append(result)
        ctx.state_history.append(state)
        already_drafted = any(c.is_drafted for c in state.colonists)
        seen_ids = {t.threat_id for t in ctx.threats_seen}
        for threat in state.threats:
            # Null incident placeholders (the /incidents endpoint emits them)
            # are not threats — counting one made threat_response unwinnable
            # in a run with zero hostiles (issue #25).
            if threat.enemy_count <= 0 and threat.threat_level <= 0.0:
                continue
            if threat.threat_id in seen_ids:
                continue
            ctx.threats_seen.append(threat)
            ctx.threat_seen_tick[threat.threat_id] = tick_num
            if already_drafted:
                ctx.first_draft_tick[threat.threat_id] = 0

    def _record_draft_response(
        self, exec_result: ExecutionResult, tick_num: int,
    ) -> None:
        """Record per-threat response delay once a draft action executes (#25)."""
        drafted = any(
            o.success
            and resolve_endpoint(o.action_type) == "draft"
            and o.parameters.get("is_drafted", True) is not False
            for o in exec_result.outcomes
        )
        if not drafted:
            return
        ctx = self._metric_context
        for threat in ctx.threats_seen:
            seen = ctx.threat_seen_tick.get(threat.threat_id, tick_num)
            ctx.first_draft_tick.setdefault(
                threat.threat_id, max(0, tick_num - seen),
            )

    async def _fire_scheduled_incidents(self, tick_num: int) -> None:
        """Fire any triggered_incidents whose tick_offset matches."""
        for incident in self._triggered_incidents:
            if incident.tick_offset == tick_num:
                logger.info(
                    "Firing scheduled incident %s at tick %d",
                    incident.name, tick_num,
                )
                try:
                    await self._client.trigger_incident(
                        incident.name,
                        map_id=incident.map_id,
                        **incident.incident_parms,
                    )
                    self._emit(
                        EventType.ACTION_EXEC, tick_num,
                        action_type="trigger_incident",
                        target=incident.name, success=True,
                    )
                except Exception:
                    logger.warning(
                        "Failed to trigger incident %s",
                        incident.name, exc_info=True,
                    )

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    async def run_tick(self) -> TickResult:
        """Execute one turn.

        In pause mode (default): pause → read → step → execute → unpause.
        In no-pause mode: read → step → execute while the game keeps running.
        """
        await self._ensure_setup()
        tick_num = len(self._tick_results)

        # 1. Pause (skip in no-pause mode — game keeps running)
        if not self._no_pause:
            await self._client.pause_game()

        self._emit(EventType.TICK_START, tick_num)

        # 1a. Dismiss force-pause nuisance windows (colony-name dialog, debug
        # log) so unattended runs don't stall mid-benchmark (issue #33).
        if self._auto_dismiss_dialogs:
            await self._dismiss_blocking_dialogs(tick_num)

        # 1b. Fire scheduled incidents (before state read captures effects)
        if self._triggered_incidents:
            await self._fire_scheduled_incidents(tick_num)

        # 2. Read state
        state = await self._state_manager.refresh()
        current_time = self._state_manager.macro_time
        self._emit(
            EventType.STATE_REFRESH, tick_num,
            day=state.colony.day, macro_time=current_time,
        )

        # 2b. Drive the cinematic camera to this tick's focus (opt-in capture
        # runs only; never raises into the tick). Issue #34.
        if self._camera_director is not None:
            await self._camera_director.direct(
                tick_num, state, self._state_manager.pending_events, _time.time(),
            )

        # 3. Harness decides (and, for tool-using harnesses, may already act)
        step, step_latency = await self._step_harness(state, tick_num, current_time)

        # 4. Execute — unless the harness already applied its writes
        if step.execution is None:
            exec_result = await self._executor.execute(step.plan)
            for outcome in exec_result.outcomes:
                self._emit(
                    EventType.ACTION_EXEC, tick_num,
                    action_type=outcome.action_type,
                    target=outcome.target_colonist_id,
                    success=outcome.success,
                    error=outcome.error,
                    parameters=outcome.parameters,
                )
        else:
            exec_result = step.execution

        # 4a. Track draft responses for the threat_response metric (issue #25)
        self._record_draft_response(exec_result, tick_num)

        # 5. Score this tick
        snapshot: ScoreSnapshot | None = None
        if self._scorer:
            snapshot = self._scorer.score(state, self._metric_context)
            if self._recorder:
                self._recorder.record(snapshot)
            self._emit(
                EventType.SCORE, tick_num,
                composite=snapshot.composite, metrics=snapshot.metrics,
            )

        # 6. Feedback to the harness (action errors, score, visualisers)
        await self._harness.on_tick_end(tick_num, state, step, exec_result, snapshot)

        # 7. Capture screenshot (opt-in, before export so it's in the JSON)
        screenshot_uri: str | None = None
        if self._screenshots_enabled:
            ss = await self._client.take_screenshot()
            if ss is not None:
                screenshot_uri = ss.data_uri

        # 8. Export tick data for dashboard
        self._export_tick_json(
            step, exec_result, snapshot,
            state.colony.tick, state.colony.day, current_time,
            screenshot_data_uri=screenshot_uri,
        )

        # 9. Unpause (skip in no-pause mode — game was never paused)
        if not self._no_pause:
            await self._client.unpause_game()

        result = TickResult(
            tick=state.colony.tick,
            day=state.colony.day,
            macro_time=current_time,
            plan=step.plan,
            execution=exec_result,
            score=snapshot,
            harness=self._harness.name,
            step_latency_s=round(step_latency, 3),
            extras=step.extras,
        )
        self._tick_results.append(result)

        # 10. Update metric context and evaluate scenario
        self._update_metric_context(result, state, tick_num)
        if self._evaluator:
            eval_result = self._evaluator.evaluate(
                state, self._metric_context, tick_count=len(self._tick_results),
            )
            if eval_result:
                self._evaluation_result = eval_result
                self._running = False

        return result

    async def _speed_keepalive(self) -> None:
        """Re-assert game speed periodically (no-pause mode only).

        RimWorld force-pauses on threat letters (mad animal, raid). With
        --no-pause the loop previously re-asserted speed only at tick
        boundaries, so a slow model left the game frozen for its entire
        deliberation window (minutes on kimi/qwen in the v0.3.0 spread) —
        frozen footage and wildly non-uniform game-time per tick. Setting
        the speed is idempotent, so this just fires every few seconds for
        the whole run. Cancelled by run().
        """
        while True:
            await asyncio.sleep(self._speed_keepalive_s)
            try:
                await self._client.unpause_game()
            except Exception:
                logger.debug("Speed keepalive failed", exc_info=True)

    async def run(self, max_ticks: int | None = None) -> list[TickResult]:
        """Run the game loop for N ticks or until stopped."""
        await self._ensure_setup()
        self._running = True
        if not await self._client.window_endpoints_available():
            logger.warning(
                "RIMAPI build lacks /api/v1/ui/window endpoints (404) — "
                "auto-dismiss of force-pause dialogs is INERT this run. "
                "Rebuild and deploy the rle-testing DLL (PR #77), or expect "
                "the colony-name dialog and dev debug log to need manual "
                "dismissal.",
            )
        keepalive: asyncio.Task[None] | None = None
        if self._no_pause:
            await self._client.unpause_game()
            if self._speed_keepalive_s > 0:
                keepalive = asyncio.create_task(self._speed_keepalive())
        tick_count = 0
        try:
            with self._harness.run_context():
                while self._running:
                    result = await self.run_tick()
                    tick_count += 1
                    score_str = ""
                    if result.score:
                        score_str = f" | score={result.score.composite:.3f}"
                    logger.info(
                        "Tick %d (day %d): %d actions, %d executed%s",
                        tick_count,
                        result.day,
                        result.execution.total,
                        result.execution.executed,
                        score_str,
                    )
                    if max_ticks and tick_count >= max_ticks:
                        break
                    await asyncio.sleep(self._config.tick_interval)
        finally:
            if keepalive is not None:
                keepalive.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await keepalive
            await self._harness.teardown()
        return self._tick_results

    def stop(self) -> None:
        """Signal the loop to stop after the current tick."""
        self._running = False

    @property
    def tick_results(self) -> list[TickResult]:
        return list(self._tick_results)

    @property
    def evaluation_result(self) -> EvaluationResult | None:
        return self._evaluation_result

    @property
    def metric_context(self) -> MetricContext:
        return self._metric_context

    @property
    def deliberation_log(self) -> list[dict[str, object]]:
        """Per-tick harness deliberation records (status, actions, reasons, summary).

        Returns a shallow copy. Each entry has keys: tick, agent, status,
        plus status-specific fields (actions, summary, confidence for success;
        raw, reason for parse_failure; reason for provider_error).
        """
        return list(self._harness.deliberation_log)

    @property
    def parse_successes(self) -> int:
        return self._harness.parse_successes

    @property
    def parse_failures(self) -> int:
        return self._harness.parse_failures
