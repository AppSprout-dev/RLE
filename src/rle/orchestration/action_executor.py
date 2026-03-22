"""Action executor — maps ActionPlan actions to RIMAPI write calls."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict

from rle.agents.actions import Action, ActionPlan, ActionType
from rle.rimapi.client import RimAPIClient

logger = logging.getLogger(__name__)

# Action types with no RIMAPI endpoint yet (even on our fork).
_PENDING_UPSTREAM: frozenset[ActionType] = frozenset({
    ActionType.ASSIGN_SOCIAL_ACTIVITY,
    ActionType.CANCEL_BLUEPRINT,
})


class ExecutionResult(BaseModel):
    """Summary of action execution for one tick."""

    model_config = ConfigDict(frozen=True)

    executed: int
    failed: int
    total: int


class ActionExecutor:
    """Routes ActionPlan actions to RIMAPI write endpoints."""

    def __init__(self, client: RimAPIClient) -> None:
        self._client = client

    async def execute(self, plan: ActionPlan) -> ExecutionResult:
        """Execute all actions in a plan, return summary."""
        executed = 0
        failed = 0
        for action in plan.actions:
            try:
                await self._dispatch(action)
                executed += 1
            except NotImplementedError:
                logger.info(
                    "Skipping %s (write endpoint not implemented)",
                    action.action_type.value,
                )
                failed += 1
            except Exception:
                logger.warning(
                    "Action %s failed", action.action_type.value, exc_info=True,
                )
                failed += 1
        return ExecutionResult(
            executed=executed,
            failed=failed,
            total=len(plan.actions),
        )

    # Actions that require a valid colonist/pawn ID to execute.
    _NEEDS_PAWN: frozenset[ActionType] = frozenset({
        ActionType.SET_WORK_PRIORITY,
        ActionType.HAUL_RESOURCE,
        ActionType.DRAFT_COLONIST,
        ActionType.UNDRAFT_COLONIST,
        ActionType.MOVE_COLONIST,
        ActionType.ASSIGN_RESEARCHER,
        ActionType.SET_RECREATION_POLICY,
        ActionType.ASSIGN_BED_REST,
        ActionType.ADMINISTER_MEDICINE,
    })

    async def _dispatch(self, action: Action) -> None:
        """Route action to appropriate RIMAPI call."""
        at = action.action_type
        cid = action.target_colonist_id or ""
        params = action.parameters

        if at == ActionType.NO_ACTION:
            return

        if at in _PENDING_UPSTREAM:
            logger.debug("No RIMAPI endpoint for %s yet (needs upstream PR)", at.value)
            return

        # Skip pawn-targeting actions with no valid colonist ID
        if at in self._NEEDS_PAWN and (not cid or cid == "0"):
            logger.info("Skipping %s: no valid colonist ID", at.value)
            return

        handler = self._handlers.get(at)
        if handler is None:
            logger.debug("No executor mapping for %s", at.value)
            return

        await handler(self, cid, params)

    # -- Individual handlers --------------------------------------------------

    async def _do_set_work_priority(
        self, cid: str, params: dict[str, Any],
    ) -> None:
        await self._client.set_work_priorities(cid, params)

    async def _do_draft(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.draft_colonist(cid, True)

    async def _do_undraft(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.draft_colonist(cid, False)

    async def _do_set_research(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.set_research_target(params.get("project", ""))

    async def _do_place_blueprint(
        self, cid: str, params: dict[str, Any],
    ) -> None:
        await self._client.place_blueprint(params)

    async def _do_move(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.move_colonist(cid, params.get("x", 0), params.get("z", 0))

    async def _do_assign_researcher(
        self, cid: str, params: dict[str, Any],
    ) -> None:
        await self._client.set_work_priorities(
            cid, {"Research": params.get("priority", 1)},
        )

    async def _do_recreation_policy(
        self, cid: str, params: dict[str, Any],
    ) -> None:
        assignment = params.get("assignment", "Joy")
        for hour in params.get("hours", []):
            await self._client.set_time_assignment(cid, hour, assignment)

    async def _do_haul(self, cid: str, params: dict[str, Any]) -> None:
        target_id = params.get("target_thing_id")
        await self._client.set_colonist_job(cid, "HaulToCell", target_thing_id=target_id)

    async def _do_set_growing_zone(self, cid: str, params: dict[str, Any]) -> None:
        cells = params.get("cells", [])
        if not cells:
            logger.info("Skipping set_growing_zone: no cells specified")
            return
        await self._client.create_growing_zone(
            map_id=params.get("map_id", 0),
            plant_def=params.get("plant_def", "PlantPotato"),
            cells=cells,
        )

    async def _do_toggle_power(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.toggle_power(
            building_id=params.get("building_id", 0),
            power_on=params.get("power_on", True),
        )

    async def _do_bed_rest(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.assign_bed_rest(
            cid, bed_building_id=params.get("bed_building_id"),
        )

    async def _do_administer_medicine(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.administer_medicine(
            cid, doctor_id=params.get("doctor_id"),
        )

    _handlers: dict[ActionType, Any] = {
        ActionType.SET_WORK_PRIORITY: _do_set_work_priority,
        ActionType.DRAFT_COLONIST: _do_draft,
        ActionType.UNDRAFT_COLONIST: _do_undraft,
        ActionType.SET_RESEARCH_TARGET: _do_set_research,
        ActionType.PLACE_BLUEPRINT: _do_place_blueprint,
        ActionType.MOVE_COLONIST: _do_move,
        ActionType.ASSIGN_RESEARCHER: _do_assign_researcher,
        ActionType.SET_RECREATION_POLICY: _do_recreation_policy,
        ActionType.HAUL_RESOURCE: _do_haul,
        ActionType.SET_GROWING_ZONE: _do_set_growing_zone,
        ActionType.TOGGLE_POWER: _do_toggle_power,
        ActionType.ASSIGN_BED_REST: _do_bed_rest,
        ActionType.ADMINISTER_MEDICINE: _do_administer_medicine,
    }
