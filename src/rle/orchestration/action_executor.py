"""Action executor — maps ActionPlan actions to RIMAPI write calls."""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict

from rle.agents.actions import Action, ActionPlan, ActionType
from rle.rimapi.client import RimAPIClient

logger = logging.getLogger(__name__)


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

    async def _dispatch(self, action: Action) -> None:
        """Route action to appropriate RIMAPI call."""
        at = action.action_type
        if at == ActionType.SET_WORK_PRIORITY:
            await self._client.set_work_priorities(
                action.target_colonist_id or "", action.parameters,
            )
        elif at == ActionType.DRAFT_COLONIST:
            await self._client.draft_colonist(
                action.target_colonist_id or "", True,
            )
        elif at == ActionType.UNDRAFT_COLONIST:
            await self._client.draft_colonist(
                action.target_colonist_id or "", False,
            )
        elif at == ActionType.SET_RESEARCH_TARGET:
            await self._client.set_research_target(
                action.parameters.get("project", ""),
            )
        elif at == ActionType.PLACE_BLUEPRINT:
            await self._client.place_blueprint(action.parameters)
        elif at == ActionType.NO_ACTION:
            pass
        elif at in (
            ActionType.HAUL_RESOURCE,
            ActionType.SET_GROWING_ZONE,
            ActionType.TOGGLE_POWER,
            ActionType.MOVE_COLONIST,
            ActionType.ASSIGN_RESEARCHER,
            ActionType.SET_RECREATION_POLICY,
            ActionType.ASSIGN_SOCIAL_ACTIVITY,
            ActionType.CANCEL_BLUEPRINT,
            ActionType.ASSIGN_BED_REST,
            ActionType.ADMINISTER_MEDICINE,
        ):
            logger.debug("No RIMAPI endpoint for %s yet", at.value)
        else:
            logger.debug("No executor mapping for %s", at.value)
