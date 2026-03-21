"""RLE game loop — turn-based orchestrator."""

from __future__ import annotations

import asyncio
import logging

from felix_agent_sdk.communication import CentralPost, MessageType, SpokeManager
from pydantic import BaseModel, ConfigDict

from rle.agents.actions import ActionPlan
from rle.agents.base_role import RimWorldRoleAgent
from rle.config import RLEConfig
from rle.orchestration.action_executor import ActionExecutor, ExecutionResult
from rle.orchestration.action_resolver import ActionResolver
from rle.orchestration.state_manager import GameStateManager
from rle.rimapi.client import RimAPIClient
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
    ) -> None:
        self._config = config
        self._client = client
        self._agents = agents
        self._state_manager = GameStateManager(client, expected_duration_days)
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

        # Hub-spoke communication
        self._hub = CentralPost(max_agents=len(agents))
        self._spoke_manager = SpokeManager(self._hub)
        for agent in agents:
            self._spoke_manager.create_spoke(agent.agent_id, agent=agent)

    async def run_tick(self) -> TickResult:
        """Execute one turn."""
        # 1. Pause
        try:
            await self._client.pause_game()
        except NotImplementedError:
            pass

        # 2. Read state
        state = await self._state_manager.refresh()
        current_time = self._state_manager.macro_time

        # 3. Multi-agent deliberation
        plans: list[ActionPlan] = []
        context_history: list[dict] = []
        for agent in self._agents:
            plan = agent.deliberate(state, current_time, context_history)
            plans.append(plan)
            context_history.append({
                "agent_id": plan.role,
                "content": plan.summary,
                "confidence": plan.confidence,
            })

            spoke = self._spoke_manager.get_spoke(agent.agent_id)
            if spoke and spoke.is_connected:
                spoke.send_message(
                    MessageType.TASK_COMPLETE,
                    {"role": plan.role, "summary": plan.summary},
                )

        self._spoke_manager.process_all_messages()

        # 4. Resolve conflicts across all agent plans
        resolved = self._resolver.resolve(plans, state)

        # 5. Execute merged plan
        exec_result = await self._executor.execute(resolved)

        # 6. Score this tick
        snapshot: ScoreSnapshot | None = None
        if self._scorer:
            snapshot = self._scorer.score(state, self._metric_context)
            if self._recorder:
                self._recorder.record(snapshot)

        # 7. Unpause
        try:
            await self._client.unpause_game()
        except NotImplementedError:
            pass

        result = TickResult(
            tick=state.colony.tick,
            day=state.colony.day,
            macro_time=current_time,
            plan=resolved,
            execution=exec_result,
            score=snapshot,
        )
        self._tick_results.append(result)

        # Update metric context for next tick
        self._metric_context.tick_results.append(result)
        self._metric_context.state_history.append(state)
        for threat in state.threats:
            seen_ids = {t.threat_id for t in self._metric_context.threats_seen}
            if threat.threat_id not in seen_ids:
                self._metric_context.threats_seen.append(threat)

        # 8. Evaluate scenario conditions
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
