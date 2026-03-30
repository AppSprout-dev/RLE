"""Action schema models for RLE role agent output."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Action(BaseModel):
    """A single proposed action from a role agent.

    action_type maps to a key in WRITE_CATALOG (api_catalog.py).
    Agents can use any RIMAPI write endpoint by name.
    """

    model_config = ConfigDict(frozen=True)

    action_type: str  # Key from WRITE_CATALOG (e.g. "work_priority", "blueprint")
    target_colonist_id: str | None = None
    parameters: dict[str, Any] = {}
    priority: int = 5  # 1 (highest) to 10 (lowest)
    reason: str = ""


class ActionPlan(BaseModel):
    """Complete output from a role agent for one game tick."""

    model_config = ConfigDict(frozen=True)

    role: str
    tick: int
    actions: list[Action]
    summary: str = ""
    confidence: float = 0.5


class ActionPlanParseError(Exception):
    """Raised when LLM output cannot be parsed into an ActionPlan."""

    def __init__(self, raw_content: str, reason: str) -> None:
        self.raw_content = raw_content
        self.reason = reason
        super().__init__(f"Failed to parse action plan: {reason}")


# Legacy ActionType names → WRITE_CATALOG keys for backward compat during transition.
# Agents can use either the old names or the new catalog keys.
ACTION_TYPE_ALIASES: dict[str, str] = {
    "set_work_priority": "work_priority",
    "haul_resource": "work_priority",  # haul = set Hauling priority to 1
    "set_growing_zone": "growing_zone",
    "toggle_power": "toggle_power",
    "create_stockpile": "stockpile_zone",
    "job_assign": "job_assign",
    "designate_area": "designate_area",
    "draft_colonist": "draft",
    "undraft_colonist": "draft",
    "move_colonist": "move",
    "set_research_target": "research_target",
    "assign_researcher": "work_priority",  # assign = set Research priority to 1
    "set_recreation_policy": "time_assignment",
    "assign_social_activity": "time_assignment",
    "place_blueprint": "blueprint",
    "cancel_blueprint": "designate_area",  # cancel = deconstruct designation
    "assign_bed_rest": "bed_rest",
    "administer_medicine": "tend",
    "no_action": "no_action",
}


def resolve_endpoint(action_type: str) -> str:
    """Map an action_type string to a WRITE_CATALOG key."""
    return ACTION_TYPE_ALIASES.get(action_type, action_type)
