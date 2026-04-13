"""RLE game loop — turn-based orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from pathlib import Path

from felix_agent_sdk.communication import CentralPost, MessageType, SpokeManager
from felix_agent_sdk.providers import ProviderError
from felix_agent_sdk.visualization import HelixVisualizer
from pydantic import BaseModel, ConfigDict

from rle.agents.actions import ActionPlan, ActionPlanParseError
from rle.agents.base_role import RimWorldRoleAgent
from rle.config import RLEConfig
from rle.orchestration.action_executor import ActionExecutor, ExecutionResult
from rle.orchestration.action_resolver import ActionResolver
from rle.orchestration.state_manager import GameStateManager
from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPISSEClient
from rle.scenarios.evaluator import EvaluationResult, ScenarioEvaluator
from rle.scenarios.schema import TriggeredIncident
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


class RLEGameLoop:
    """Turn-based game loop: pause → read → deliberate → resolve → execute → score → unpause."""

    def __init__(
        self,
        config: RLEConfig,
        client: RimAPIClient,
        agents: list[RimWorldRoleAgent],
        expected_duration_days: int = 60,
        scorer: CompositeScorer | None = None,
        recorder: TimeSeriesRecorder | None = None,
        evaluator: ScenarioEvaluator | None = None,
        initial_population: int = 3,
        initial_wealth: float = 0.0,
        visualizer: HelixVisualizer | None = None,
        parallel: bool = True,
        sse_client: RimAPISSEClient | None = None,
        dashboard_export_dir: Path | None = None,
        no_agent: bool = False,
        no_pause: bool = False,
        event_log: EventLog | None = None,
        cost_tracker: CostTracker | None = None,
        triggered_incidents: list[TriggeredIncident] | None = None,
        screenshots_enabled: bool = False,
    ) -> None:
        self._config = config
        self._client = client
        self._agents = agents
        # Separate MapAnalyst (runs first) from role agents (run in parallel)
        self._map_analyst: RimWorldRoleAgent | None = None
        self._role_agents: list[RimWorldRoleAgent] = []
        for agent in agents:
            if agent.ROLE_NAME == "map_analyst":
                self._map_analyst = agent
            else:
                self._role_agents.append(agent)
        self._no_agent = no_agent
        self._no_pause = no_pause
        self._state_manager = GameStateManager(client, expected_duration_days, sse_client)
        self._executor = ActionExecutor(client)
        self._resolver = ActionResolver()
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
        self._parse_successes = 0
        self._parse_failures = 0
        self._log_dir: Path | None = None
        self._deliberation_log: list[dict[str, object]] = []
        self._parallel = parallel
        self._last_phase: str = ""
        self._dashboard_export_dir = dashboard_export_dir

        self._visualizer = visualizer
        self._event_log = event_log
        self._cost_tracker = cost_tracker
        self._triggered_incidents = triggered_incidents or []
        self._screenshots_enabled = screenshots_enabled

        # Hub-spoke communication — agents read messages from their spokes
        self._hub = CentralPost(max_agents=len(agents))
        self._spoke_manager = SpokeManager(self._hub)
        for agent in agents:
            spoke = self._spoke_manager.create_spoke(agent.agent_id, agent=agent)
            agent.attach_spoke(spoke)

    def _emit(
        self, event_type: EventType, tick: int,
        agent: str | None = None, **data: object,
    ) -> None:
        """Emit an event if EventLog is configured. Thread-safe."""
        if self._event_log is not None:
            self._event_log.emit(event_type, tick, agent=agent, **data)

    @property
    def cost_tracker(self) -> CostTracker | None:
        return self._cost_tracker

    def _update_visualizer_agent(
        self, agent: RimWorldRoleAgent, plan: ActionPlan, macro_time: float,
    ) -> None:
        """Push one agent's post-deliberation state to the visualizer."""
        if not self._visualizer:
            return
        self._visualizer.update(
            agent.agent_id,
            progress=macro_time,
            confidence=plan.confidence,
            phase=agent.position.phase,
            status=f"{len(plan.actions)} actions",
        )

    def _render_visualizer(
        self, tick: int, day: int, exec_result: ExecutionResult,
        snapshot: ScoreSnapshot | None,
    ) -> None:
        """Render the helix visualization for this tick."""
        if not self._visualizer:
            return
        extra: dict[str, str] = {
            "actions": f"{exec_result.executed}/{exec_result.total}",
        }
        if snapshot:
            extra["score"] = f"{snapshot.composite:.3f}"
        self._visualizer.render(tick=tick, day=day, extra_info=extra)

    async def _deliberate_parallel(
        self, state: object, current_time: float, tick_num: int,
    ) -> list[tuple[RimWorldRoleAgent, ActionPlan | None]]:
        """Run role agents concurrently via asyncio.to_thread."""

        async def _run(agent: RimWorldRoleAgent) -> tuple[RimWorldRoleAgent, ActionPlan | None]:
            return await asyncio.to_thread(
                self._deliberate_agent, agent, state, current_time, tick_num,
            )

        return list(await asyncio.gather(*[_run(a) for a in self._role_agents]))

    def _deliberate_sequential(
        self, state: object, current_time: float, tick_num: int,
    ) -> list[tuple[RimWorldRoleAgent, ActionPlan | None]]:
        """Run role agents one at a time. Agents read context from their spokes."""
        results: list[tuple[RimWorldRoleAgent, ActionPlan | None]] = []
        for agent in self._role_agents:
            agent_result, plan = self._deliberate_agent(
                agent, state, current_time, tick_num,
            )
            results.append((agent_result, plan))
        return results

    def _deliberate_agent(
        self, agent: RimWorldRoleAgent, state: object,
        current_time: float, tick_num: int,
    ) -> tuple[RimWorldRoleAgent, ActionPlan | None]:
        """Run one agent's deliberation. Thread-safe for parallel execution.

        Agents read inter-agent context from their CentralPost spoke internally.
        """
        t0 = _time.monotonic()
        try:
            plan = agent.deliberate(state, current_time)  # type: ignore[arg-type]
        except ActionPlanParseError as e:
            latency_ms = round((_time.monotonic() - t0) * 1000, 1)
            logger.warning(
                "Agent %s parse failure (tick %d): %s",
                agent.ROLE_NAME, tick_num, e.reason,
            )
            self._parse_failures += 1
            self._deliberation_log.append({
                "tick": tick_num, "agent": agent.ROLE_NAME,
                "status": "parse_failure", "reason": e.reason,
                "raw": e.raw_content[:500] if e.raw_content else None,
            })
            self._emit(
                EventType.ERROR, tick_num, agent=agent.ROLE_NAME,
                error_type="parse_failure", reason=e.reason, latency_ms=latency_ms,
            )
            return agent, None
        except ProviderError as e:
            latency_ms = round((_time.monotonic() - t0) * 1000, 1)
            logger.warning(
                "Agent %s provider error (tick %d): %s",
                agent.ROLE_NAME, tick_num, e,
            )
            self._parse_failures += 1
            self._deliberation_log.append({
                "tick": tick_num, "agent": agent.ROLE_NAME,
                "status": "provider_error", "reason": str(e),
            })
            self._emit(
                EventType.ERROR, tick_num, agent=agent.ROLE_NAME,
                error_type="provider_error", reason=str(e), latency_ms=latency_ms,
            )
            return agent, None

        latency_ms = round((_time.monotonic() - t0) * 1000, 1)
        self._parse_successes += 1
        self._deliberation_log.append({
            "tick": tick_num, "agent": plan.role,
            "status": "success", "confidence": plan.confidence,
            "num_actions": len(plan.actions),
            "actions": [
                {"type": a.action_type, "target": a.target_colonist_id,
                 "priority": a.priority, "reason": a.reason[:200]}
                for a in plan.actions
            ],
            "summary": plan.summary[:300],
        })
        self._emit(
            EventType.DELIBERATION, tick_num, agent=plan.role,
            latency_ms=latency_ms, confidence=plan.confidence,
            num_actions=len(plan.actions),
        )

        # Record token usage for cost tracking and event log
        usage = agent._last_usage
        if usage and isinstance(usage, dict):
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            if isinstance(pt, int) and isinstance(ct, int):
                if self._cost_tracker:
                    self._cost_tracker.record_raw(pt, ct)
                self._emit(
                    EventType.PROVIDER_CALL, tick_num, agent=plan.role,
                    prompt_tokens=pt, completion_tokens=ct,
                )

        return agent, plan

    def _export_tick_json(
        self, plans: list[ActionPlan], resolved: ActionPlan,
        exec_result: ExecutionResult, snapshot: ScoreSnapshot | None,
        tick: int, day: int, macro_time: float,
        screenshot_data_uri: str | None = None,
    ) -> None:
        """Write tick data as JSON for the rimapi-dashboard to consume."""
        if not self._dashboard_export_dir:
            return
        self._dashboard_export_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "tick": tick,
            "day": day,
            "macro_time": macro_time,
            "phase": self._last_phase,
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
                for p in plans
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
        }
        (self._dashboard_export_dir / "latest_tick.json").write_text(
            json.dumps(data, indent=2),
        )

    def _update_metric_context(self, result: TickResult, state: GameState) -> None:
        """Append tick data to metric context for scoring history."""
        self._metric_context.tick_results.append(result)
        self._metric_context.state_history.append(state)
        for threat in state.threats:
            seen_ids = {t.threat_id for t in self._metric_context.threats_seen}
            if threat.threat_id not in seen_ids:
                self._metric_context.threats_seen.append(threat)

    def _broadcast_phase_if_changed(self, current_time: float) -> None:
        """Broadcast PHASE_ANNOUNCE when macro_time crosses a phase boundary."""
        if current_time < 0.4:
            phase = "exploration"
        elif current_time < 0.7:
            phase = "analysis"
        else:
            phase = "synthesis"
        if phase != self._last_phase:
            self._spoke_manager.broadcast_message(
                MessageType.PHASE_ANNOUNCE,
                {"phase": phase, "depth_ratio": current_time},
                sender_id="hub",
            )
            self._last_phase = phase

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

    async def run_tick(self) -> TickResult:
        """Execute one turn.

        In pause mode (default): pause → read → deliberate → execute → unpause.
        In no-pause mode: read → fire deliberation + sleep concurrently → execute.
        """
        tick_num = len(self._tick_results)

        # 1. Pause (skip in no-pause mode — game keeps running)
        if not self._no_pause:
            await self._client.pause_game()

        self._emit(EventType.TICK_START, tick_num)

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

        # 3. Route previous tick's messages to agent spokes + broadcast phase changes
        messages_before = self._hub.total_messages_processed
        self._spoke_manager.process_all_messages()
        self._broadcast_phase_if_changed(current_time)

        # 4-6. Agent deliberation + conflict resolution (skipped in no-agent mode)
        plans: list[ActionPlan] = []
        if self._no_agent:
            # Baseline mode: no deliberation, no actions. Colony runs unmanaged.
            resolved = ActionPlan(
                role="baseline", tick=state.colony.tick, actions=[], summary="No agents",
            )
        else:
            # Inject SSE events into all agents (including MapAnalyst)
            pending_events = self._state_manager.pending_events
            for agent in self._agents:
                agent.set_pending_events(pending_events)
            for evt in pending_events:
                self._emit(
                    EventType.SSE_EVENT, tick_num,
                    sse_type=evt.event_type, sse_data=str(evt.data)[:200],
                )

            # 4a. MapAnalyst deliberates FIRST (sequential)
            if self._map_analyst:
                ma_agent, ma_plan = self._deliberate_agent(
                    self._map_analyst, state, current_time, tick_num,
                )
                if ma_plan is not None:
                    plans.append(ma_plan)
                    self._update_visualizer_agent(ma_agent, ma_plan, current_time)
                    spoke = self._spoke_manager.get_spoke(ma_agent.agent_id)
                    if spoke and spoke.is_connected:
                        spoke.send_message(
                            MessageType.TASK_COMPLETE,
                            {
                                "role": ma_plan.role,
                                "summary": ma_plan.summary,
                                "confidence": ma_plan.confidence,
                                "num_actions": len(ma_plan.actions),
                                "action_types": [
                                    a.action_type for a in ma_plan.actions
                                ],
                            },
                        )
                    # Route MapAnalyst output to role agent spokes immediately
                    self._spoke_manager.process_all_messages()

            # 4b. Role agents deliberate (parallel or sequential)
            # Snapshot which agents have pending spoke messages (for messages_acted_on)
            agents_with_messages: set[str] = set()
            for ra in self._role_agents:
                spoke = self._spoke_manager.get_spoke(ra.agent_id)
                if spoke and spoke.has_pending_messages():
                    agents_with_messages.add(ra.agent_id)

            if self._parallel:
                results = await self._deliberate_parallel(state, current_time, tick_num)
            else:
                results = self._deliberate_sequential(state, current_time, tick_num)

            # Collect plans, update visualizer, send via CentralPost
            for agent, plan in results:
                if plan is None:
                    continue
                plans.append(plan)
                if agent.agent_id in agents_with_messages:
                    self._metric_context.messages_acted_on += 1
                self._update_visualizer_agent(agent, plan, current_time)
                spoke = self._spoke_manager.get_spoke(agent.agent_id)
                if spoke and spoke.is_connected:
                    spoke.send_message(
                        MessageType.TASK_COMPLETE,
                        {
                            "role": plan.role,
                            "summary": plan.summary,
                            "confidence": plan.confidence,
                            "num_actions": len(plan.actions),
                            "action_types": [
                                a.action_type for a in plan.actions
                            ],
                        },
                    )

            # Resolve conflicts
            resolved, resolver_stats = self._resolver.resolve(plans, state)
            self._metric_context.conflicts_total += resolver_stats.conflicts_total
            self._metric_context.conflicts_resolved += resolver_stats.conflicts_resolved
            self._emit(
                EventType.CONFLICT, tick_num,
                input_plans=len(plans),
                output_actions=len(resolved.actions),
                conflicts_detected=resolver_stats.conflicts_total,
                conflicts_resolved=resolver_stats.conflicts_resolved,
            )

            # Track message effectiveness
            messages_after = self._hub.total_messages_processed
            new_messages = messages_after - messages_before
            self._metric_context.messages_sent += new_messages

        # 7. Execute merged plan
        exec_result = await self._executor.execute(resolved)
        for i, action in enumerate(resolved.actions):
            success = i < exec_result.executed
            self._emit(
                EventType.ACTION_EXEC, tick_num,
                action_type=action.action_type,
                target=action.target_colonist_id,
                success=success,
            )

        # 8. Score this tick
        snapshot: ScoreSnapshot | None = None
        if self._scorer:
            snapshot = self._scorer.score(state, self._metric_context)
            if self._recorder:
                self._recorder.record(snapshot)
            if snapshot:
                self._emit(
                    EventType.SCORE, tick_num,
                    composite=snapshot.composite, metrics=snapshot.metrics,
                )

        # 9. Broadcast score to all agents via CentralPost
        if snapshot:
            self._spoke_manager.broadcast_message(
                MessageType.STATUS_UPDATE,
                {
                    "tick": state.colony.tick,
                    "day": state.colony.day,
                    "composite_score": snapshot.composite,
                    "metrics": snapshot.metrics,
                },
                sender_id="hub",
            )

        # 10. Render visualization
        self._render_visualizer(state.colony.tick, state.colony.day, exec_result, snapshot)

        # 11. Capture screenshot (opt-in, before export so it's in the JSON)
        screenshot_uri: str | None = None
        if self._screenshots_enabled:
            ss = await self._client.take_screenshot()
            if ss is not None:
                screenshot_uri = ss.data_uri

        # 12. Export tick data for dashboard
        self._export_tick_json(
            plans, resolved, exec_result, snapshot,
            state.colony.tick, state.colony.day, current_time,
            screenshot_data_uri=screenshot_uri,
        )

        # 13. Unpause (skip in no-pause mode — game was never paused)
        if not self._no_pause:
            await self._client.unpause_game()

        result = TickResult(
            tick=state.colony.tick,
            day=state.colony.day,
            macro_time=current_time,
            plan=resolved,
            execution=exec_result,
            score=snapshot,
        )
        self._tick_results.append(result)

        # 9. Update metric context and evaluate scenario
        self._update_metric_context(result, state)
        if self._evaluator:
            eval_result = self._evaluator.evaluate(
                state, self._metric_context, tick_count=len(self._tick_results),
            )
            if eval_result:
                self._evaluation_result = eval_result
                self._running = False

        return result

    async def run(self, max_ticks: int | None = None) -> list[TickResult]:
        """Run the game loop for N ticks or until stopped."""
        self._running = True
        if self._no_pause:
            await self._client.unpause_game()
        tick_count = 0
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
