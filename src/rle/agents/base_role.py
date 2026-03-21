"""Base class for all RLE role-specialized agents."""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from typing import Any, ClassVar, Tuple

from felix_agent_sdk import LLMAgent, LLMResult, LLMTask
from felix_agent_sdk.core import HelixGeometry
from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.tokens.budget import TokenBudget

from rle.agents.actions import Action, ActionPlan, ActionPlanParseError, ActionType
from rle.rimapi.schemas import GameState

logger = logging.getLogger(__name__)


class RimWorldRoleAgent(LLMAgent):
    """Base class for RLE role agents.

    Bridges Felix SDK's LLMAgent with RimWorld-specific structured output:
    1. Injects GameState into LLMTask context (filtered per role)
    2. Overrides prompting with role identity + helix phase directives + JSON schema
    3. Parses LLM output into validated ActionPlan
    """

    ROLE_NAME: ClassVar[str] = "base"
    ALLOWED_ACTIONS: ClassVar[set[ActionType]] = set()
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.2, 0.8)

    def __init__(
        self,
        agent_id: str,
        provider: BaseProvider,
        helix: HelixGeometry,
        *,
        spawn_time: float = 0.0,
        velocity: float | None = None,
        temperature_range: tuple[float, float] | None = None,
        max_tokens: int | None = None,
        token_budget: TokenBudget | None = None,
    ) -> None:
        super().__init__(
            agent_id,
            provider,
            helix,
            spawn_time=spawn_time,
            velocity=velocity,
            agent_type=self.ROLE_NAME,
            temperature_range=temperature_range or self.TEMPERATURE_RANGE,
            max_tokens=max_tokens or 4096,
            token_budget=token_budget,
        )
        self._last_action_plan: ActionPlan | None = None

    # ------------------------------------------------------------------
    # Abstract methods — subclasses must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        """Extract the subset of game state relevant to this role."""
        ...

    @abstractmethod
    def _get_task_description(self) -> str:
        """One-liner describing what this role agent should do."""
        ...

    @abstractmethod
    def _get_role_description(self) -> str:
        """Paragraph describing this role's domain and responsibilities."""
        ...

    # ------------------------------------------------------------------
    # Task building
    # ------------------------------------------------------------------

    def build_task(
        self,
        state: GameState,
        context_history: list[dict[str, Any]] | None = None,
    ) -> LLMTask:
        """Construct an LLMTask from filtered game state."""
        filtered = self.filter_game_state(state)
        return LLMTask(
            task_id=f"{self.ROLE_NAME}-tick-{state.colony.tick}",
            description=self._get_task_description(),
            context=json.dumps(filtered, indent=2, default=str),
            metadata={
                "role": self.ROLE_NAME,
                "tick": state.colony.tick,
                "day": state.colony.day,
                "allowed_actions": [a.value for a in self.ALLOWED_ACTIONS],
            },
            context_history=context_history or [],
        )

    # ------------------------------------------------------------------
    # Prompt override
    # ------------------------------------------------------------------

    def create_position_aware_prompt(self, task: LLMTask) -> Tuple[str, str]:
        """Build role-specific system and user prompts with helix phase adaptation."""
        phase = self.position.phase
        progress_pct = int(self._progress * 100)

        if phase == "exploration":
            phase_directive = (
                "You are in the EXPLORATION phase. Survey the colony broadly. "
                "Identify multiple potential issues and opportunities in your domain. "
                "Propose diverse strategies. Breadth over depth."
            )
        elif phase == "analysis":
            phase_directive = (
                "You are in the ANALYSIS phase. Evaluate the most pressing issues "
                "in your domain. Compare trade-offs between actions. Prioritize based "
                "on urgency and resource availability."
            )
        else:
            phase_directive = (
                "You are in the SYNTHESIS phase. Make decisive, precise action "
                "recommendations. Focus on the single most impactful set of actions. "
                "Be concise and confident."
            )

        allowed = task.metadata.get("allowed_actions", [])
        allowed_str = ", ".join(allowed) if allowed else "any"

        system_prompt = (
            f"You are the {self.ROLE_NAME} for a RimWorld colony. "
            f"{self._get_role_description()}\n\n"
            f"Progress: {progress_pct}% ({phase} phase).\n"
            f"{phase_directive}\n\n"
            f"ALLOWED ACTIONS: {allowed_str}\n\n"
            f"You MUST respond with a JSON object matching this schema:\n"
            f'{{"actions": [{{"action_type": "<type>", "target_colonist_id": "<id or null>", '
            f'"parameters": {{}}, "priority": <1-10>, "reason": "<why>"}}], '
            f'"summary": "<brief summary>", "confidence": <0.0-1.0>}}\n\n'
            f"Respond ONLY with valid JSON. No markdown, no explanation outside the JSON."
        )

        parts = []
        # Disable thinking for local models (e.g. Qwen3.5 thinking mode)
        if self.provider.provider_name == "local":
            parts.append("/no_think")
        parts.append(task.description)
        if task.context:
            parts.append(f"\nCurrent colony state:\n{task.context}")
        if task.context_history:
            parts.append("\nOther agents' recent outputs:")
            for entry in task.context_history:
                agent = entry.get("agent_id", "unknown")
                text = entry.get("content", "")
                parts.append(f"  [{agent}]: {text[:300]}")

        user_prompt = "\n".join(parts)
        return system_prompt, user_prompt

    # ------------------------------------------------------------------
    # Action plan parsing
    # ------------------------------------------------------------------

    def parse_action_plan(self, result: LLMResult, tick: int) -> ActionPlan:
        """Parse LLMResult.content into a validated ActionPlan."""
        raw = result.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [line for line in lines[1:] if not line.strip().startswith("```")]
            raw = "\n".join(lines)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ActionPlanParseError(result.content, f"Invalid JSON: {e}") from e

        actions: list[Action] = []
        for raw_action in data.get("actions", []):
            try:
                action_type = ActionType(raw_action["action_type"])
            except (KeyError, ValueError) as e:
                logger.warning("Skipping invalid action: %s", e)
                continue
            if action_type not in self.ALLOWED_ACTIONS:
                logger.warning(
                    "Skipping disallowed action %s for role %s",
                    action_type.value,
                    self.ROLE_NAME,
                )
                continue
            actions.append(
                Action(
                    action_type=action_type,
                    target_colonist_id=raw_action.get("target_colonist_id"),
                    parameters=raw_action.get("parameters", {}),
                    priority=raw_action.get("priority", 5),
                    reason=raw_action.get("reason", ""),
                )
            )

        return ActionPlan(
            role=self.ROLE_NAME,
            tick=tick,
            actions=actions,
            summary=data.get("summary", ""),
            confidence=data.get("confidence", result.confidence),
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def deliberate(
        self,
        state: GameState,
        current_time: float,
        context_history: list[dict[str, Any]] | None = None,
    ) -> ActionPlan:
        """Full pipeline: advance helix → build task → LLM call → parse actions.

        Args:
            state: Current game state snapshot.
            current_time: Macro helix time (0.0-1.0), typically
                ``min(1.0, game_day / expected_duration_days)``.
            context_history: Other agents' recent outputs for inter-agent context.
        """
        # Ensure agent is spawned and positioned
        if not hasattr(self, "_state") or self._state.value == "waiting":
            self.spawn(current_time)
        self.update_position(current_time)

        task = self.build_task(state, context_history)
        result = self.process_task(task)
        plan = self.parse_action_plan(result, state.colony.tick)
        self._last_action_plan = plan
        return plan
