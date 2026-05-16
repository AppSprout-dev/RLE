"""Tests for ActionExecutor."""

from __future__ import annotations

from unittest.mock import AsyncMock

from rle.agents.actions import Action, ActionPlan
from rle.orchestration.action_executor import ActionExecutor


def _make_plan(*actions: Action) -> ActionPlan:
    return ActionPlan(role="test", tick=1, actions=list(actions))


class TestExecute:
    async def test_no_action_excluded_from_totals(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(Action(action_type="no_action"))
        result = await executor.execute(plan)
        assert result.executed == 0
        assert result.failed == 0
        assert result.total == 0

    async def test_not_implemented_counted_as_failed(self) -> None:
        client = AsyncMock()
        client.set_research_target = AsyncMock(side_effect=NotImplementedError)
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="set_research_target",
                parameters={"project": "electricity"},
            )
        )
        result = await executor.execute(plan)
        assert result.executed == 0
        assert result.failed == 1
        assert result.total == 1

    async def test_execution_result_counts_exclude_no_action(self) -> None:
        """NO_ACTION is excluded from totals; only real actions count."""
        client = AsyncMock()
        client.set_research_target = AsyncMock(side_effect=NotImplementedError)
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type="no_action"),
            Action(
                action_type="set_research_target",
                parameters={"project": "electricity"},
            ),
            Action(action_type="no_action"),
        )
        result = await executor.execute(plan)
        assert result.executed == 0
        assert result.failed == 1
        assert result.total == 1

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
        plan = _make_plan(Action(action_type="haul_resource"))
        result = await executor.execute(plan)
        assert result.executed == 1
        assert result.failed == 0


class TestOutcomes:
    """ExecutionResult.outcomes carries per-action success/error so the
    game loop can surface failures back to agents next tick."""

    async def test_success_outcome_recorded(self) -> None:
        from rle.orchestration.action_executor import ActionExecutor
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type="set_work_priority",
                   target_colonist_id="42", parameters={"Growing": 1}),
        )
        result = await executor.execute(plan)
        assert len(result.outcomes) == 1
        outcome = result.outcomes[0]
        assert outcome.success is True
        assert outcome.action_type == "set_work_priority"
        assert outcome.target_colonist_id == "42"
        assert outcome.error is None

    async def test_rimapi_error_extracted_into_outcome(self) -> None:
        """RIMAPI's JSON error envelope is unwrapped to a clean human-readable string."""
        from rle.orchestration.action_executor import ActionExecutor
        from rle.rimapi.client import RimAPIResponseError
        client = AsyncMock()
        client.set_research_target = AsyncMock(side_effect=RimAPIResponseError(
            500,
            '{"success":false,"errors":["Research project \'Electricity\' is already finished."],'
            '"warnings":[],"timestamp":"2026-05-16T06:00:00Z"}',
        ))
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type="set_research_target", parameters={"project": "Electricity"}),
        )
        result = await executor.execute(plan)
        assert result.failed == 1
        assert len(result.outcomes) == 1
        outcome = result.outcomes[0]
        assert outcome.success is False
        assert outcome.error == "Research project 'Electricity' is already finished."

    async def test_generic_exception_message_captured(self) -> None:
        from rle.orchestration.action_executor import ActionExecutor
        client = AsyncMock()
        client.set_research_target = AsyncMock(side_effect=RuntimeError("boom"))
        executor = ActionExecutor(client)
        plan = _make_plan(Action(action_type="set_research_target", parameters={}))
        result = await executor.execute(plan)
        assert result.outcomes[0].success is False
        assert result.outcomes[0].error == "boom"

    async def test_outcomes_preserve_order(self) -> None:
        """no_action is skipped; outcomes only cover dispatched actions in order."""
        from rle.orchestration.action_executor import ActionExecutor
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type="no_action"),
            Action(action_type="draft_colonist", target_colonist_id="1"),
            Action(action_type="draft_colonist", target_colonist_id="2"),
        )
        result = await executor.execute(plan)
        assert [o.target_colonist_id for o in result.outcomes] == ["1", "2"]


class TestDispatch:
    async def test_set_work_priority(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="set_work_priority",
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
            Action(action_type="draft_colonist", target_colonist_id="12345")
        )
        await executor.execute(plan)
        client.draft_colonist.assert_awaited_once_with("12345", True)

    async def test_undraft_colonist(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="undraft_colonist",
                target_colonist_id="12345",
                parameters={"is_drafted": False},
            )
        )
        await executor.execute(plan)
        client.draft_colonist.assert_awaited_once_with("12345", False)

    async def test_place_blueprint(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="place_blueprint",
                parameters={"def_name": "Wall", "x": 10, "z": 20, "map_id": 0},
            )
        )
        await executor.execute(plan)
        client.place_building.assert_awaited_once_with(
            def_name="Wall", x=10, z=20, stuff_def="WoodLog",
            rotation=0, map_id=0,
        )

    async def test_place_blueprint_missing_position_skipped(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="place_blueprint",
                parameters={"def_name": "Wall"},
            )
        )
        await executor.execute(plan)
        client.place_building.assert_not_awaited()

    async def test_move_colonist(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="move_colonist",
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
                action_type="assign_researcher",
                target_colonist_id="12345",
                parameters={"Research": 1},
            )
        )
        await executor.execute(plan)
        client.set_work_priorities.assert_awaited_once_with("12345", {"Research": 1})

    async def test_set_recreation_policy(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="set_recreation_policy",
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
                action_type="set_research_target",
                parameters={"project": "electricity"},
            )
        )
        await executor.execute(plan)
        client.set_research_target.assert_awaited_once_with("electricity", force=False)

    async def test_equip_item(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="equip",
                target_colonist_id="12345",
                parameters={"thing_id": 999},
            )
        )
        await executor.execute(plan)
        client.equip_item.assert_awaited_once_with("12345", 999)

    async def test_equip_missing_thing_id_skipped(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(action_type="equip", target_colonist_id="12345")
        )
        result = await executor.execute(plan)
        client.equip_item.assert_not_awaited()
        assert result.executed == 1  # handler ran without error (skipped)

    async def test_repair_rect(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="repair_rect",
                parameters={"map_id": 0, "x1": 10, "z1": 10, "x2": 20, "z2": 20},
            )
        )
        await executor.execute(plan)
        client.repair_rect.assert_awaited_once_with(
            map_id=0, x1=10, z1=10, x2=20, z2=20,
        )

    async def test_destroy_rect(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        plan = _make_plan(
            Action(
                action_type="destroy_rect",
                parameters={"map_id": 0, "x1": 5, "z1": 5, "x2": 15, "z2": 15},
            )
        )
        await executor.execute(plan)
        client.destroy_rect.assert_awaited_once_with(
            map_id=0, x1=5, z1=5, x2=15, z2=15,
        )
