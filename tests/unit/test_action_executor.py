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
        client.set_research_target = AsyncMock(side_effect=NotImplementedError)
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.SET_RESEARCH_TARGET,
                parameters={"project": "electricity"},
            )
        )
        result = await executor.execute(plan)
        assert result.executed == 0
        assert result.failed == 1
        assert result.total == 1

    async def test_execution_result_counts(self) -> None:
        client = AsyncMock()
        client.set_research_target = AsyncMock(side_effect=NotImplementedError)
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type=ActionType.NO_ACTION),
            Action(
                action_type=ActionType.SET_RESEARCH_TARGET,
                parameters={"project": "electricity"},
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

    async def test_pending_upstream_action_succeeds(self) -> None:
        """Actions pending upstream PRs pass through without error."""
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(Action(action_type=ActionType.HAUL_RESOURCE))
        result = await executor.execute(plan)
        assert result.executed == 1
        assert result.failed == 0


class TestDispatch:
    async def test_set_work_priority(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.SET_WORK_PRIORITY,
                target_colonist_id="12345",
                parameters={"Growing": 1},
            )
        )
        await executor.execute(plan)
        client.set_work_priorities.assert_awaited_once_with("12345", {"Growing": 1})

    async def test_draft_colonist(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type=ActionType.DRAFT_COLONIST, target_colonist_id="12345")
        )
        await executor.execute(plan)
        client.draft_colonist.assert_awaited_once_with("12345", True)

    async def test_undraft_colonist(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type=ActionType.UNDRAFT_COLONIST, target_colonist_id="12345")
        )
        await executor.execute(plan)
        client.draft_colonist.assert_awaited_once_with("12345", False)

    async def test_place_blueprint(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.PLACE_BLUEPRINT,
                parameters={"def_name": "Wall", "x": 10, "z": 20, "map_id": 0},
            )
        )
        await executor.execute(plan)
        client.designate_area.assert_awaited_once_with(
            map_id=0, designation_type="Wall", x1=10, z1=20, x2=10, z2=20,
        )

    async def test_place_blueprint_missing_position_skipped(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.PLACE_BLUEPRINT,
                parameters={"def_name": "Wall"},
            )
        )
        result = await executor.execute(plan)
        client.designate_area.assert_not_awaited()
        assert result.executed == 0

    async def test_move_colonist(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.MOVE_COLONIST,
                target_colonist_id="12345",
                parameters={"x": 10, "z": 20},
            )
        )
        await executor.execute(plan)
        client.move_colonist.assert_awaited_once_with("12345", 10, 20)

    async def test_assign_researcher(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.ASSIGN_RESEARCHER,
                target_colonist_id="12345",
                parameters={"priority": 1},
            )
        )
        await executor.execute(plan)
        client.set_work_priorities.assert_awaited_once_with("12345", {"Research": 1})

    async def test_set_recreation_policy(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.SET_RECREATION_POLICY,
                target_colonist_id="12345",
                parameters={"hours": [18, 19, 20], "assignment": "Joy"},
            )
        )
        await executor.execute(plan)
        assert client.set_time_assignment.await_count == 3
        client.set_time_assignment.assert_any_await("12345", 18, "Joy")
        client.set_time_assignment.assert_any_await("12345", 19, "Joy")
        client.set_time_assignment.assert_any_await("12345", 20, "Joy")

    async def test_set_research_target(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type=ActionType.SET_RESEARCH_TARGET,
                parameters={"project": "electricity"},
            )
        )
        await executor.execute(plan)
        client.set_research_target.assert_awaited_once_with("electricity")
