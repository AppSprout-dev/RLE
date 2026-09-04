"""Action executor — dispatches agent actions to RIMAPI endpoints."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from rle.agents.actions import (
    Action,
    ActionOutcome,
    ActionPlan,
    ExecutionResult,
    resolve_endpoint,
)
from rle.rimapi.api_catalog import WRITE_CATALOG
from rle.rimapi.client import RimAPIClient, RimAPIResponseError

__all__ = ["ActionExecutor", "ActionOutcome", "ExecutionResult"]

logger = logging.getLogger(__name__)

# Endpoints that require a valid colonist/pawn ID.
_NEEDS_PAWN: frozenset[str] = frozenset({
    "work_priority",
    "draft",
    "move",
    "job_assign",
    "time_assignment",
    "equip",
    "bed_rest",
    "tend",
})


def _extract_rimapi_error(detail: str) -> str:
    """Pull the first error string out of a RIMAPI JSON envelope, else return raw detail."""
    try:
        parsed = json.loads(detail)
    except (json.JSONDecodeError, TypeError):
        return detail
    errors = parsed.get("errors") if isinstance(parsed, dict) else None
    if isinstance(errors, list) and errors:
        return str(errors[0])
    return detail


def _normalize_work_priorities(params: dict[str, Any]) -> dict[str, int]:
    """Accept the parameter shapes models actually emit for work_priority.

    Documented shape is flat ``{"<WorkType>": <1-4>}``, but frontier models
    also emit ``{"work_type": "Research", "priority": 2}`` and
    ``{"work_priorities": {"Growing": 1, ...}}`` (issue #27). Passing those
    through verbatim posted garbage like work="work_type" to RIMAPI.
    """
    nested = params.get("work_priorities")
    if isinstance(nested, dict):
        return {str(work): int(pri) for work, pri in nested.items()}
    if "work_type" in params:
        return {str(params["work_type"]): int(params.get("priority", 1))}
    flat = {
        str(work): int(pri) for work, pri in params.items()
        if isinstance(pri, int) and not isinstance(pri, bool)
    }
    if not flat:
        raise ValueError(
            'work_priority requires {"<WorkType>": <1-4>} parameters '
            "(e.g. {\"Growing\": 1})"
        )
    return flat


class ActionExecutor:
    """Dispatches agent actions to RIMAPI write endpoints.

    Uses specialized handlers for actions that need parameter mapping,
    falls back to generic WRITE_CATALOG dispatch for everything else.
    """

    def __init__(self, client: RimAPIClient) -> None:
        self._client = client
        # Rectangles (x1, z1, x2, z2) of growing zones already created this run.
        # Agents perseverate — they re-issue the same growing zone every tick.
        # Each repeat targets cells already owned by the first zone, which RIMAPI
        # rejects (and historically mislabelled as "Invalid plant definition").
        # We short-circuit overlapping repeats with an explicit error so the
        # agent learns the zone exists instead of burning ticks on doomed calls
        # (issue #33).
        self._created_growing_zones: list[tuple[int, int, int, int]] = []
        # Same guard for stockpiles: RimWorld logs one "overwriting slot group
        # square" error PER CELL when a stockpile overlaps an existing one,
        # which spams the dev log (and pops it over the game when auto-open
        # is enabled).
        self._created_stockpile_zones: list[tuple[int, int, int, int]] = []

    @staticmethod
    def _rects_overlap(
        a: tuple[int, int, int, int], b: tuple[int, int, int, int]
    ) -> bool:
        ax1, az1, ax2, az2 = a
        bx1, bz1, bx2, bz2 = b
        return not (ax2 < bx1 or ax1 > bx2 or az2 < bz1 or az1 > bz2)

    async def execute(self, plan: ActionPlan) -> ExecutionResult:
        """Execute all actions in a plan, return summary + per-action outcomes."""
        executed = 0
        failed = 0
        no_action_count = 0
        outcomes: list[ActionOutcome] = []
        for action in plan.actions:
            endpoint = resolve_endpoint(action.action_type)
            if endpoint == "no_action":
                no_action_count += 1
                continue
            try:
                await self._dispatch(action, endpoint)
                executed += 1
                outcomes.append(ActionOutcome(
                    action_type=action.action_type,
                    endpoint=endpoint,
                    target_colonist_id=action.target_colonist_id,
                    success=True,
                    parameters=action.parameters,
                ))
            except RimAPIResponseError as exc:
                logger.warning("Action %s failed: %s", endpoint, exc.detail)
                failed += 1
                outcomes.append(ActionOutcome(
                    action_type=action.action_type,
                    endpoint=endpoint,
                    target_colonist_id=action.target_colonist_id,
                    success=False,
                    error=_extract_rimapi_error(exc.detail),
                    parameters=action.parameters,
                ))
            except Exception as exc:
                logger.warning("Action %s failed", endpoint, exc_info=True)
                failed += 1
                outcomes.append(ActionOutcome(
                    action_type=action.action_type,
                    endpoint=endpoint,
                    target_colonist_id=action.target_colonist_id,
                    success=False,
                    error=str(exc) or type(exc).__name__,
                    parameters=action.parameters,
                ))
        return ExecutionResult(
            executed=executed,
            failed=failed,
            total=len(plan.actions) - no_action_count,
            outcomes=tuple(outcomes),
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
        await self._client.set_work_priorities(
            cid, _normalize_work_priorities(params),
        )

    async def _h_draft(self, cid: str, params: dict[str, Any]) -> None:
        is_drafted = params.get("is_drafted", True)
        await self._client.draft_colonist(cid, is_drafted)

    async def _h_move(self, cid: str, params: dict[str, Any]) -> None:
        await self._client.move_colonist(cid, params.get("x", 0), params.get("z", 0))

    async def _h_job_assign(self, cid: str, params: dict[str, Any]) -> None:
        # Models emit "job" as often as the documented "job_def" (issue #27);
        # posting an empty JobDef is a guaranteed RIMAPI error.
        job = params.get("job_def") or params.get("job") or ""
        if not job:
            raise ValueError(
                'job_assign requires a "job_def" parameter (e.g. "Sow", "Mine")'
            )
        target_position = params.get("target_position")
        if target_position is None and "x" in params and "z" in params:
            target_position = (int(params["x"]), int(params["z"]))
        await self._client.set_colonist_job(
            cid,
            job=str(job),
            target_thing_id=params.get("target_thing_id"),
            target_position=target_position,
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
        x1 = int(params.get("x1", params.get("x", 0)))
        z1 = int(params.get("z1", params.get("z", 0)))
        x2 = int(params.get("x2", x1 + 5))
        z2 = int(params.get("z2", z1 + 5))
        rect = (min(x1, x2), min(z1, z2), max(x1, x2), max(z1, z2))
        if any(self._rects_overlap(rect, prev) for prev in self._created_growing_zones):
            raise ValueError(
                "A growing zone already covers these cells — it was created "
                "earlier this run. Do NOT recreate it; pick a different, "
                "non-overlapping rectangle or move on to another task."
            )
        await self._client.create_growing_zone(
            map_id=int(params.get("map_id", 0)),
            plant_def=params.get("plant_def", "Plant_Potato"),
            x1=x1,
            z1=z1,
            x2=x2,
            z2=z2,
        )
        self._created_growing_zones.append(rect)

    # RimWorld's StoragePriority is semantic; models reasonably emit the
    # words. Map them instead of crashing in int() (found in the 2026-06-11
    # spread: fable5 sent priority="important").
    _STOCKPILE_PRIORITIES = {
        "unstored": 0, "low": 1, "normal": 2,
        "preferred": 3, "important": 4, "critical": 5,
    }

    @classmethod
    def _parse_stockpile_priority(cls, value: Any) -> int:
        if isinstance(value, str):
            named = cls._STOCKPILE_PRIORITIES.get(value.strip().lower())
            if named is not None:
                return named
        try:
            return int(value)
        except (TypeError, ValueError):
            return 3

    async def _h_stockpile_zone(self, cid: str, params: dict[str, Any]) -> None:
        x1 = int(params.get("x1", params.get("x", 0)))
        z1 = int(params.get("z1", params.get("z", 0)))
        x2 = int(params.get("x2", x1 + 5))
        z2 = int(params.get("z2", z1 + 5))
        rect = (min(x1, x2), min(z1, z2), max(x1, x2), max(z1, z2))
        if any(self._rects_overlap(rect, prev) for prev in self._created_stockpile_zones):
            raise ValueError(
                "A stockpile zone already covers these cells — it was created "
                "earlier this run. Do NOT recreate it; pick a different, "
                "non-overlapping rectangle or move on to another task."
            )
        await self._client.create_stockpile_zone(
            map_id=int(params.get("map_id", 0)),
            x1=x1,
            z1=z1,
            x2=x2,
            z2=z2,
            name=params.get("name", ""),
            priority=self._parse_stockpile_priority(params.get("priority", 3)),
            allowed_item_defs=params.get("allowed_item_defs"),
            allowed_item_categories=params.get("allowed_item_categories"),
        )
        self._created_stockpile_zones.append(rect)

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

    async def _h_equip(self, cid: str, params: dict[str, Any]) -> None:
        thing_id = params.get("thing_id")
        if thing_id is None:
            logger.info("Skipping equip: no thing_id")
            return
        await self._client.equip_item(cid, int(thing_id))

    async def _h_repair_rect(self, cid: str, params: dict[str, Any]) -> None:
        x1 = int(params.get("x1", params.get("x", 0)))
        z1 = int(params.get("z1", params.get("z", 0)))
        x2 = int(params.get("x2", x1))
        z2 = int(params.get("z2", z1))
        await self._client.repair_rect(
            map_id=int(params.get("map_id", 0)),
            x1=x1, z1=z1, x2=x2, z2=z2,
        )

    async def _h_destroy_rect(self, cid: str, params: dict[str, Any]) -> None:
        x1 = int(params.get("x1", params.get("x", 0)))
        z1 = int(params.get("z1", params.get("z", 0)))
        x2 = int(params.get("x2", x1))
        z2 = int(params.get("z2", z1))
        await self._client.destroy_rect(
            map_id=int(params.get("map_id", 0)),
            x1=x1, z1=z1, x2=x2, z2=z2,
        )


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
    "equip": ActionExecutor._h_equip,
    "repair_rect": ActionExecutor._h_repair_rect,
    "destroy_rect": ActionExecutor._h_destroy_rect,
}
