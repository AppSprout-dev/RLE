"""Tests for ActionExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock

from rle.agents.actions import Action, ActionPlan, ActionType
from rle.orchestration.action_executor import ActionExecutor


def _make_plan(*actions: Action) -> ActionPlan:
    return ActionPlan(role="test", tick=1, actions=list(actions))


class TestExecute:
    async def test_no_action_skipped(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(Action(action_type=ActionType.NO_ACTION))
        result = await executor.execute(plan)
        assert result.executed == 1
        assert result.failed == 0
        assert result.total == 1

    async def test_not_implemented_counted_as_failed(self) -> None:
        client = AsyncMock()
        client.set_work_priorities = AsyncMock(side_effect=NotImplementedError)
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.SET_WORK_PRIORITY,
                target_colonist_id="col_01",
                parameters={"skill": "growing", "priority": 1},
            )
        )
        result = await executor.execute(plan)
        assert result.executed == 0
        assert result.failed == 1
        assert result.total == 1

    async def test_execution_result_counts(self) -> None:
        client = AsyncMock()
        # NO_ACTION succeeds, SET_WORK_PRIORITY raises NotImplementedError
        client.set_work_priorities = AsyncMock(side_effect=NotImplementedError)
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type=ActionType.NO_ACTION),
            Action(
                action_type=ActionType.SET_WORK_PRIORITY,
                target_colonist_id="col_01",
                parameters={},
            ),
            Action(action_type=ActionType.NO_ACTION),
        )
        result = await executor.execute(plan)
        assert result.executed == 2
        assert result.failed == 1
        assert result.total == 3

    async def test_empty_plan(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan()
        result = await executor.execute(plan)
        assert result.executed == 0
        assert result.failed == 0
        assert result.total == 0

    async def test_unmapped_action_succeeds(self) -> None:
        """Actions with no RIMAPI endpoint yet just pass through."""
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(Action(action_type=ActionType.HAUL_RESOURCE))
        result = await executor.execute(plan)
        assert result.executed == 1
        assert result.failed == 0
