"""Unit tests for the five harness-agnostic dispatch preflight gates."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rle.agents.actions import Action, ActionPlan
from rle.harness.brief import action_catalog
from rle.orchestration.action_executor import ActionExecutor
from rle.orchestration.preflight import (
    extract_work_priorities,
    growing_zone_already_covers,
    is_already_covered_error,
    is_quarantined_write,
    normalize_work_priorities,
    research_target_status,
    resolve_tend_pair,
)
from rle.rimapi.client import RimAPIResponseError
from rle.rimapi.schemas import (
    ColonistData,
    ColonyData,
    GameState,
    MapData,
    ResearchData,
    ResourceData,
    WeatherData,
)


def _colonist(cid: str, *, health: float = 0.9) -> ColonistData:
    return ColonistData(
        colonist_id=cid,
        name=cid,
        health=health,
        mood=0.6,
        skills={},
        traits=[],
        current_job=None,
        is_drafted=False,
        needs={},
        injuries=[],
        position=(0, 0),
    )


def _state(
    *,
    colonists: list[ColonistData] | None = None,
    research: ResearchData | None = None,
) -> GameState:
    return GameState(
        colony=ColonyData(
            name="T", wealth=1.0, day=1, tick=100, population=2,
            mood_average=0.5, food_days=3.0,
        ),
        colonists=colonists or [_colonist("181"), _colonist("184")],
        resources=ResourceData(
            food=10, medicine=1, steel=1, wood=1, components=0, silver=0, power_net=0.0,
        ),
        map=MapData(size=(250, 250), biome="t", season="spring", temperature=10.0, structures=[]),
        research=research or ResearchData(
            current_project="Electricity",
            progress=0.2,
            completed=["Stonecutting"],
            available=["Electricity", "Smithing"],
        ),
        threats=[],
        weather=WeatherData(condition="clear", temperature=10.0, outdoor_severity=0.0),
        timestamp=0.0,
    )


def _plan(*actions: Action) -> ActionPlan:
    return ActionPlan(role="test", tick=1, actions=list(actions))


# -- 1. Farm / growing zone already-satisfied --------------------------------


class TestGrowingZoneAlreadySatisfied:
    def test_check_zone_issues_zones_is_covered(self) -> None:
        assert growing_zone_already_covers({
            "can_build": False,
            "issues": {"zones": [{"x": 132, "z": 137, "zone_type": "Growing"}]},
        })

    def test_check_zone_occupied_cells_shape(self) -> None:
        assert growing_zone_already_covers({"occupied_cells": 6, "free_cells": 0})
        assert not growing_zone_already_covers({"occupied_cells": 0, "free_cells": 36})

    def test_empty_or_garbage_is_not_covered(self) -> None:
        assert not growing_zone_already_covers({})
        assert not growing_zone_already_covers(None)
        assert not growing_zone_already_covers("ok")

    def test_engine_message_detected(self) -> None:
        assert is_already_covered_error("A growing zone already covers these cells")
        assert not is_already_covered_error("Invalid plant definition: Plant_Rice")

    async def test_in_memory_overlap_is_success_not_failure(self) -> None:
        client = AsyncMock()
        client.check_zone = AsyncMock(return_value={"occupied_cells": 0})
        executor = ActionExecutor(client)
        zone = Action(
            action_type="growing_zone",
            parameters={"x1": 132, "z1": 137, "x2": 139, "z2": 144, "plant_def": "Plant_Rice"},
        )
        first = await executor.execute(_plan(zone))
        assert first.executed == 1
        repeat = await executor.execute(_plan(zone))
        assert repeat.executed == 1
        assert repeat.failed == 0
        client.create_growing_zone.assert_awaited_once()

    async def test_check_zone_occupied_skips_recreate(self) -> None:
        client = AsyncMock()
        client.check_zone = AsyncMock(return_value={
            "issues": {"zones": [{"zone_type": "Growing", "x": 60, "z": 40}]},
        })
        executor = ActionExecutor(client)
        result = await executor.execute(_plan(Action(
            action_type="growing_zone",
            parameters={"x1": 60, "z1": 40, "x2": 67, "z2": 47},
        )))
        assert result.executed == 1
        assert result.failed == 0
        client.create_growing_zone.assert_not_awaited()

    async def test_engine_already_covered_error_is_success(self) -> None:
        client = AsyncMock()
        client.check_zone = AsyncMock(return_value={"occupied_cells": 0})
        client.create_growing_zone = AsyncMock(side_effect=RimAPIResponseError(
            500,
            '{"success":false,"errors":["A growing zone already covers these cells"]}',
        ))
        executor = ActionExecutor(client)
        result = await executor.execute(_plan(Action(
            action_type="growing_zone",
            parameters={"x1": 10, "z1": 10, "x2": 15, "z2": 15},
        )))
        assert result.executed == 1
        assert result.failed == 0


# -- 2. Work-priority schema -------------------------------------------------


class TestWorkPrioritySchema:
    def test_id_priority_dto_is_not_treated_as_work_types(self) -> None:
        pairs = extract_work_priorities({"id": 184, "work": "Growing", "priority": 1})
        assert pairs == {"Growing": 1}

    def test_flat_map_drops_reserved_keys(self) -> None:
        pairs = extract_work_priorities({"Growing": 1, "id": 184, "priority": 2})
        assert pairs == {"Growing": 1}

    def test_id_priority_only_has_no_work_type(self) -> None:
        with pytest.raises(ValueError, match="Do not send id/priority"):
            normalize_work_priorities({"id": 184, "priority": 1})

    def test_unknown_work_type_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown WorkTypeDef"):
            normalize_work_priorities({"NotAJob": 1})

    def test_valid_work_type_normalized(self) -> None:
        assert normalize_work_priorities({"growing": 1}) == {"Growing": 1}

    def test_skill_alias_maps_to_work_type(self) -> None:
        assert normalize_work_priorities({"skill": "growing", "priority": 1}) == {"Growing": 1}

    def test_priority_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            normalize_work_priorities({"Growing": 9})

    async def test_executor_rejects_id_priority_payload(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        result = await executor.execute(_plan(Action(
            action_type="work_priority",
            target_colonist_id="184",
            parameters={"id": 184, "priority": 1},
        )))
        assert result.failed == 1
        assert "WorkType" in (result.outcomes[0].error or "")
        client.set_work_priorities.assert_not_awaited()

    async def test_executor_accepts_work_plus_priority(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        result = await executor.execute(_plan(Action(
            action_type="work_priority",
            target_colonist_id="184",
            parameters={"work": "Growing", "priority": 1, "id": 184},
        )))
        assert result.executed == 1
        client.set_work_priorities.assert_awaited_once_with("184", {"Growing": 1})


# -- 3. Research availability ------------------------------------------------


class TestResearchAvailability:
    def test_available_current_finished_locked(self) -> None:
        research = ResearchData(
            current_project="Electricity",
            progress=0.2,
            completed=["Stonecutting"],
            available=["Electricity", "Smithing"],
        )
        assert research_target_status("Smithing", research) == "available"
        assert research_target_status("electricity", research) == "current"
        assert research_target_status("Stonecutting", research) == "finished"
        assert research_target_status("Fabrication", research) == "locked"

    async def test_locked_research_fails_without_write(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        result = await executor.execute(
            _plan(Action(action_type="research_target", parameters={"project": "Fabrication"})),
            state=_state(),
        )
        assert result.failed == 1
        assert "not currently available" in (result.outcomes[0].error or "")
        client.set_research_target.assert_not_awaited()

    async def test_available_research_is_queued(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        result = await executor.execute(
            _plan(Action(action_type="research_target", parameters={"project": "Smithing"})),
            state=_state(),
        )
        assert result.executed == 1
        client.set_research_target.assert_awaited_once_with("Smithing", force=False)

    async def test_current_project_is_still_queued(self) -> None:
        """Re-targeting the current project is allowed; it is available."""
        client = AsyncMock()
        executor = ActionExecutor(client)
        result = await executor.execute(
            _plan(Action(action_type="research_target", parameters={"project": "Electricity"})),
            state=_state(),
        )
        assert result.executed == 1
        client.set_research_target.assert_awaited_once_with("Electricity", force=False)


# -- 4. Doctor + patient preflight -------------------------------------------


class TestTendPair:
    def test_missing_doctor_rejected(self) -> None:
        with pytest.raises(ValueError, match="doctor"):
            resolve_tend_pair("181", {}, None)

    def test_dead_doctor_rejected(self) -> None:
        state = _state(colonists=[_colonist("181"), _colonist("184", health=0.0)])
        with pytest.raises(ValueError, match="doctor"):
            resolve_tend_pair("181", {"doctor_pawn_id": "184"}, state)

    def test_dead_patient_rejected(self) -> None:
        state = _state(colonists=[_colonist("181", health=0.0), _colonist("184")])
        with pytest.raises(ValueError, match="patient"):
            resolve_tend_pair("181", {"doctor_pawn_id": "184"}, state)

    def test_valid_pair_returned(self) -> None:
        state = _state()
        assert resolve_tend_pair("181", {"doctor_pawn_id": "184"}, state) == ("184", "181")

    async def test_executor_blocks_tend_without_doctor(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        result = await executor.execute(
            _plan(Action(action_type="tend", target_colonist_id="181")),
            state=_state(),
        )
        assert result.failed == 1
        assert "doctor" in (result.outcomes[0].error or "")
        client.administer_medicine.assert_not_awaited()

    async def test_executor_sends_living_pair(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        result = await executor.execute(
            _plan(Action(
                action_type="tend",
                target_colonist_id="181",
                parameters={"doctor_pawn_id": "184"},
            )),
            state=_state(),
        )
        assert result.executed == 1
        client.administer_medicine.assert_awaited_once_with("181", doctor_id="184")


# -- 5. Stockpile-delete quarantine ------------------------------------------


class TestStockpileDeleteQuarantine:
    def test_endpoint_is_quarantined(self) -> None:
        assert is_quarantined_write("stockpile_delete")
        assert not is_quarantined_write("stockpile_zone")

    def test_not_advertised_in_brief(self) -> None:
        names = {entry["action_type"] for entry in action_catalog()}
        assert "stockpile_delete" not in names
        assert "stockpile_zone" in names

    def test_work_priority_catalog_does_not_advertise_id_priority(self) -> None:
        work = next(a for a in action_catalog() if a["action_type"] == "work_priority")
        params = work["params"]
        assert "id" not in params
        assert "priority" not in params

    async def test_executor_refuses_without_http(self) -> None:
        client = AsyncMock()
        executor = ActionExecutor(client)
        result = await executor.execute(_plan(Action(
            action_type="stockpile_delete",
            parameters={"zone_id": 3},
        )))
        assert result.failed == 1
        assert "quarantined" in (result.outcomes[0].error or "")
        client.call.assert_not_awaited()
