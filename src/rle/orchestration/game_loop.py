"""RLE game loop — turn-based orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from felix_agent_sdk.communication import CentralPost, MessageType, SpokeManager
from felix_agent_sdk.visualization import HelixVisualizer
from pydantic import BaseModel, ConfigDict

from rle.agents.actions import ActionPlan, ActionPlanParseError
from rle.agents.base_role import RimWorldRoleAgent
from rle.config import RLEConfig
from rle.orchestration.action_executor import ActionExecutor, ExecutionResult
from rle.orchestration.action_resolver import ActionResolver
from rle.orchestration.state_manager import GameStateManager
from rle.rimapi.client import RimAPIClient
from rle.rimapi.sse_client import RimAPISSEClient
from rle.scenarios.evaluator import EvaluationResult, ScenarioEvaluator
from rle.scoring.composite import CompositeScorer, ScoreSnapshot
from rle.scoring.metrics import MetricContext
from rle.scoring.recorder import TimeSeriesRecorder

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
    ) -> None:
        self._config = config
        self._client = client
        self._agents = agents
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
        self._deliberation_log: list[dict] = []
        self._parallel = parallel
        self._last_phase: str = ""
        self._dashboard_export_dir = dashboard_export_dir

        self._visualizer = visualizer

        # Hub-spoke communication — agents read messages from their spokes
        self._hub = CentralPost(max_agents=len(agents))
        self._spoke_manager = SpokeManager(self._hub)
        for agent in agents:
            spoke = self._spoke_manager.create_spoke(agent.agent_id, agent=agent)
            agent.attach_spoke(spoke)

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
        """Run all agents concurrently via asyncio.to_thread."""

        async def _run(agent: RimWorldRoleAgent) -> tuple[RimWorldRoleAgent, ActionPlan | None]:
            return await asyncio.to_thread(
                self._deliberate_agent, agent, state, current_time, tick_num,
            )

        return list(await asyncio.gather(*[_run(a) for a in self._agents]))

    def _deliberate_sequential(
        self, state: object, current_time: float, tick_num: int,
    ) -> list[tuple[RimWorldRoleAgent, ActionPlan | None]]:
        """Run agents one at a time. Agents read context from their spokes."""
        results: list[tuple[RimWorldRoleAgent, ActionPlan | None]] = []
        for agent in self._agents:
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
        try:
            plan = agent.deliberate(state, current_time)  # type: ignore[arg-type]
        except ActionPlanParseError as e:
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
            return agent, None
        self._parse_successes += 1
        self._deliberation_log.append({
            "tick": tick_num, "agent": plan.role,
            "status": "success", "confidence": plan.confidence,
            "num_actions": len(plan.actions),
            "actions": [
                {"type": a.action_type.value, "target": a.target_colonist_id,
                 "priority": a.priority, "reason": a.reason[:200]}
                for a in plan.actions
            ],
            "summary": plan.summary[:300],
        })
        return agent, plan

    def _export_tick_json(
        self, plans: list[ActionPlan], resolved: ActionPlan,
        exec_result: ExecutionResult, snapshot: ScoreSnapshot | None,
        tick: int, day: int, macro_time: float,
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
                            "action_type": a.action_type.value,
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
                        "action_type": a.action_type.value,
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
        }
        (self._dashboard_export_dir / "latest_tick.json").write_text(
            json.dumps(data, indent=2),
        )

    def _update_metric_context(self, result: TickResult, state: object) -> None:
        """Append tick data to metric context for scoring history."""
        self._metric_context.tick_results.append(result)
        self._metric_context.state_history.append(state)
        for threat in state.threats:  # type: ignore[attr-defined]
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

    async def run_tick(self) -> TickResult:
        """Execute one turn."""
        # 1. Pause
        await self._client.pause_game()

        # 2. Read state
        state = await self._state_manager.refresh()
        current_time = self._state_manager.macro_time

        # 3. Route previous tick's messages to agent spokes + broadcast phase changes
        self._spoke_manager.process_all_messages()
        self._broadcast_phase_if_changed(current_time)

        # 4. Inject SSE events into agents for this tick
        pending_events = self._state_manager.pending_events
        for agent in self._agents:
            agent.set_pending_events(pending_events)

        # 5. Multi-agent deliberation (agents read spoke messages internally)
        tick_num = len(self._tick_results)
        if self._parallel:
            results = await self._deliberate_parallel(state, current_time, tick_num)
        else:
            results = self._deliberate_sequential(state, current_time, tick_num)

        # 5. Collect plans, update visualizer, send results via CentralPost
        plans: list[ActionPlan] = []
        for agent, plan in results:
            if plan is None:
                continue
            plans.append(plan)
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
                        "action_types": [a.action_type.value for a in plan.actions],
                    },
                )

        # 6. Resolve conflicts across all agent plans
        resolved = self._resolver.resolve(plans, state)

        # 7. Execute merged plan
        exec_result = await self._executor.execute(resolved)

        # 8. Score this tick
        snapshot: ScoreSnapshot | None = None
        if self._scorer:
            snapshot = self._scorer.score(state, self._metric_context)
            if self._recorder:
                self._recorder.record(snapshot)

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

        # 11. Export tick data for dashboard
        self._export_tick_json(
            plans, resolved, exec_result, snapshot,
            state.colony.tick, state.colony.day, current_time,
        )

        # 12. Unpause
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
