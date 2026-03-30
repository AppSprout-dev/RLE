"""Action schema models for RLE role agent output."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActionType(str, Enum):
    """All possible action types across all role agents."""

    # Resource
    SET_WORK_PRIORITY = "set_work_priority"
    HAUL_RESOURCE = "haul_resource"
    SET_GROWING_ZONE = "set_growing_zone"
    TOGGLE_POWER = "toggle_power"
    CREATE_STOCKPILE = "create_stockpile"
    JOB_ASSIGN = "job_assign"
    DESIGNATE_AREA = "designate_area"
    # Defense
    DRAFT_COLONIST = "draft_colonist"
    UNDRAFT_COLONIST = "undraft_colonist"
    MOVE_COLONIST = "move_colonist"
    # Research
    SET_RESEARCH_TARGET = "set_research_target"
    ASSIGN_RESEARCHER = "assign_researcher"
    # Social
    SET_RECREATION_POLICY = "set_recreation_policy"
    ASSIGN_SOCIAL_ACTIVITY = "assign_social_activity"
    # Construction
    PLACE_BLUEPRINT = "place_blueprint"
    CANCEL_BLUEPRINT = "cancel_blueprint"
    # Medical
    ASSIGN_BED_REST = "assign_bed_rest"
    ADMINISTER_MEDICINE = "administer_medicine"
    # General
    NO_ACTION = "no_action"


class Action(BaseModel):
    """A single proposed action from a role agent."""

    model_config = ConfigDict(frozen=True)

    action_type: ActionType
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
