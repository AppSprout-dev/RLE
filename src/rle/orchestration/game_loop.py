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

logger = logging.getLogger(__name__)


class TickResult(BaseModel):
    """Summary of a single game tick."""

    model_config = ConfigDict(frozen=True)

    tick: int
    day: int
    macro_time: float
    plan: ActionPlan
    execution: ExecutionResult


class RLEGameLoop:
    """Turn-based game loop: pause → read → deliberate → resolve → execute → unpause."""

    def __init__(
        self,
        config: RLEConfig,
        client: RimAPIClient,
        agents: list[RimWorldRoleAgent],
        expected_duration_days: int = 60,
    ) -> None:
        self._config = config
        self._client = client
        self._agents = agents
        self._state_manager = GameStateManager(client, expected_duration_days)
        self._executor = ActionExecutor(client)
        self._resolver = ActionResolver()
        self._tick_results: list[TickResult] = []
        self._running = False

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

            # Broadcast plan summary via hub-spoke
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

        # 6. Unpause
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
        )
        self._tick_results.append(result)
        return result

    async def run(self, max_ticks: int | None = None) -> list[TickResult]:
        """Run the game loop for N ticks or until stopped."""
        self._running = True
        tick_count = 0
        while self._running:
            result = await self.run_tick()
            tick_count += 1
            logger.info(
                "Tick %d (day %d): %d actions, %d executed",
                tick_count,
                result.day,
                result.execution.total,
                result.execution.executed,
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
