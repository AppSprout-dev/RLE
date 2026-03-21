"""RLE game loop — turn-based orchestrator."""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, ConfigDict

from rle.agents.actions import ActionPlan
from rle.agents.base_role import RimWorldRoleAgent
from rle.config import RLEConfig
from rle.orchestration.action_executor import ActionExecutor, ExecutionResult
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
    """Turn-based game loop: pause → read → deliberate → execute → unpause."""

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
        self._tick_results: list[TickResult] = []
        self._running = False

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

        # 3. Agent deliberation (first agent only for P3)
        plan = self._agents[0].deliberate(state, current_time)

        # 4. Execute actions
        exec_result = await self._executor.execute(plan)

        # 5. Unpause
        try:
            await self._client.unpause_game()
        except NotImplementedError:
            pass

        result = TickResult(
            tick=state.colony.tick,
            day=state.colony.day,
            macro_time=current_time,
            plan=plan,
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
