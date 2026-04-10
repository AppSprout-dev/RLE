"""Action executor — dispatches agent actions to RIMAPI endpoints."""

from __future__ import annotations

import logging
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from rle.agents.actions import Action, ActionPlan, resolve_endpoint
from rle.rimapi.api_catalog import WRITE_CATALOG
from rle.rimapi.client import RimAPIClient

logger = logging.getLogger(__name__)

# Endpoints that require a valid colonist/pawn ID.
_NEEDS_PAWN: frozenset[str] = frozenset(
    {
        "work_priority",
        "draft",
        "move",
        "job_assign",
        "time_assignment",
        "equip",
        "bed_rest",
        "tend",
    }
)


class ExecutionResult(BaseModel):
    """Summary of action execution for one tick."""

    model_config = ConfigDict(frozen=True)

    executed: int
    failed: int
    total: int


class ActionExecutor:
    """Dispatches agent actions to RIMAPI write endpoints.

    Uses specialized handlers for actions that need parameter mapping,
    falls back to generic WRITE_CATALOG dispatch for everything else.
    """

    def __init__(self, client: RimAPIClient) -> None:
        self._client = client

    async def execute(self, plan: ActionPlan) -> ExecutionResult:
        """Execute all actions in a plan, return summary."""
        executed = 0
        failed = 0
        no_action_count = 0
        for action in plan.actions:
            endpoint = resolve_endpoint(action.action_type)
            if endpoint == "no_action":
                no_action_count += 1
                continue
            try:
                await self._dispatch(action, endpoint)
                executed += 1
            except Exception:
                logger.warning("Action %s failed", endpoint, exc_info=True)
                failed += 1
        return ExecutionResult(
            executed=executed,
            failed=failed,
            total=len(plan.actions) - no_action_count,
        )

    async def _dispatch(self, action: Action, endpoint: str) -> None:
        """Route action to RIMAPI. Specialized handlers first, then generic."""
        cid = action.target_colonist_id or ""
        params = action.parameters

        # Skip pawn-targeting actions with no valid colonist ID
        if endpoint in _NEEDS_PAWN and (not cid or cid == "0"):
            logger.info("Skipping %s: no valid colonist ID", endpoint)
            return

        # Try specialized handler first (handles parameter mapping)
        handler = _SPECIALIZED_HANDLERS.get(endpoint)
        if handler is not None:
            await handler(self, cid, params)
            return

        # Generic fallback: look up in WRITE_CATALOG and call directly
        catalog_entry = WRITE_CATALOG.get(endpoint)
        if catalog_entry is None:
            logger.debug("Unknown endpoint: %s", endpoint)
            return

        entry = cast(dict[str, str], catalog_entry)
        await self._client.call(entry["method"], entry["path"], json=params)

    # -- Specialized handlers (parameter mapping for complex DTOs) -----------

    async def _h_work_priority(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.set_work_priorities(cid, params)

    async def _h_draft(self, cid: str, params: dict[str, Any]) -> None:
        is_drafted = params.get("is_drafted", True)
        await self._client.draft_colonist(cid, is_drafted)

    async def _h_move(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.move_colonist(cid, params.get("x", 0), params.get("z", 0))

    async def _h_job_assign(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.set_colonist_job(
            cid,
            job=params.get("job_def", ""),
            target_thing_id=params.get("target_thing_id"),
            target_position=params.get("target_position"),
        )

    async def _h_time_assignment(self, cid: str, params: dict[str, Any]) -> None:
        assignment = params.get("assignment", "Joy")
        for hour in params.get("hours", []):
            await self._client.set_time_assignment(cid, hour, assignment)

    async def _h_bed_rest(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.assign_bed_rest(cid, bed_building_id=params.get("bed_building_id"))

    async def _h_tend(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.administer_medicine(cid, doctor_id=params.get("doctor_id"))

    async def _h_blueprint(self, cid: str, params: dict[str, Any]) -> None:
        if "x" not in params or "z" not in params:
            logger.info("Skipping blueprint: no x, z coordinates")
            return
        await self._client.place_building(
            def_name=params.get("def_name", "Wall"),
            x=int(params["x"]),
            z=int(params["z"]),
            stuff_def=params.get("stuff_def", "WoodLog"),
            rotation=int(params.get("rotation", 0)),
            map_id=int(params.get("map_id", 0)),
        )

    async def _h_growing_zone(self, cid: str, params: dict[str, Any]) -> None:
        x1 = params.get("x1", params.get("x", 0))
        z1 = params.get("z1", params.get("z", 0))
        x2 = params.get("x2", x1 + 5)
        z2 = params.get("z2", z1 + 5)
        await self._client.create_growing_zone(
            map_id=int(params.get("map_id", 0)),
            plant_def=params.get("plant_def", "Plant_Potato"),
            x1=x1,
            z1=z1,
            x2=x2,
            z2=z2,
        )

    async def _h_stockpile_zone(self, cid: str, params: dict[str, Any]) -> None:
        x1 = params.get("x1", params.get("x", 0))
        z1 = params.get("z1", params.get("z", 0))
        x2 = params.get("x2", x1 + 5)
        z2 = params.get("z2", z1 + 5)
        await self._client.create_stockpile_zone(
            map_id=int(params.get("map_id", 0)),
            x1=x1,
            z1=z1,
            x2=x2,
            z2=z2,
            name=params.get("name", ""),
            priority=int(params.get("priority", 3)),
            allowed_item_defs=params.get("allowed_item_defs"),
            allowed_item_categories=params.get("allowed_item_categories"),
        )

    async def _h_designate_area(self, cid: str, params: dict[str, Any]) -> None:
        x1 = params.get("x1", params.get("x", 0))
        z1 = params.get("z1", params.get("z", 0))
        x2 = params.get("x2", x1)
        z2 = params.get("z2", z1)
        await self._client.designate_area(
            map_id=int(params.get("map_id", 0)),
            designation_type=params.get("type", params.get("designation_type", "Mine")),
            x1=x1,
            z1=z1,
            x2=x2,
            z2=z2,
        )

    async def _h_toggle_power(self, cid: str, params: dict[str, Any]) -> None:
        building_id = params.get("building_id")
        if not building_id:
            logger.info("Skipping toggle_power: no building_id")
            return
        await self._client.toggle_power(
            building_id=int(building_id), power_on=params.get("power_on", True)
        )

    async def _h_research_target(self, cid: str, params: dict[str, Any]) -> None:
        project = params.get("project", params.get("name", ""))
        await self._client.set_research_target(project, force=params.get("force", False))

    async def _h_research_stop(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.stop_research()


# String-keyed handler map (matches WRITE_CATALOG keys).
_SPECIALIZED_HANDLERS: dict[str, Any] = {
    "work_priority": ActionExecutor._h_work_priority,
    "draft": ActionExecutor._h_draft,
    "move": ActionExecutor._h_move,
    "job_assign": ActionExecutor._h_job_assign,
    "time_assignment": ActionExecutor._h_time_assignment,
    "bed_rest": ActionExecutor._h_bed_rest,
    "tend": ActionExecutor._h_tend,
    "blueprint": ActionExecutor._h_blueprint,
    "growing_zone": ActionExecutor._h_growing_zone,
    "stockpile_zone": ActionExecutor._h_stockpile_zone,
    "designate_area": ActionExecutor._h_designate_area,
    "toggle_power": ActionExecutor._h_toggle_power,
    "research_target": ActionExecutor._h_research_target,
    "research_stop": ActionExecutor._h_research_stop,
}
