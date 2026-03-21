"""Base class for all RLE role-specialized agents."""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from typing import Any, ClassVar, Tuple

from felix_agent_sdk import LLMAgent, LLMResult, LLMTask
from felix_agent_sdk.core import HelixGeometry
from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.providers.types import ChatMessage, CompletionResult, MessageRole
from felix_agent_sdk.tokens.budget import TokenBudget

from rle.agents.actions import Action, ActionPlan, ActionPlanParseError, ActionType
from rle.agents.json_repair import repair_json
from rle.rimapi.schemas import GameState

logger = logging.getLogger(__name__)

# Shared prefix for all 6 role agents. Placed first in the system prompt so
# LM Studio / llama.cpp can reuse the KV cache across agents within a tick.
_SHARED_SYSTEM_PREFIX = (
    "You are one of 6 specialized role agents collaborating to manage a RimWorld colony. "
    "The agents are: ResourceManager, DefenseCommander, ResearchDirector, SocialOverseer, "
    "ConstructionPlanner, and MedicalOfficer. Each agent proposes actions for its domain; "
    "a central resolver merges plans and handles conflicts.\n\n"
    "You MUST respond with a JSON object matching this schema:\n"
    '{"actions": [{"action_type": "<type>", "target_colonist_id": "<id or null>", '
    '"parameters": {}, "priority": <1-10>, "reason": "<why>"}], '
    '"summary": "<brief summary>", "confidence": <0.0-1.0>}\n\n'
    "Respond ONLY with valid JSON. No markdown, no explanation outside the JSON.\n\n"
)


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
        self._provider_kwargs: dict[str, Any] = {}
        self._no_think: bool = False

    def set_provider_kwargs(self, **kwargs: Any) -> None:
        """Set extra kwargs passed to provider.complete() (e.g. extra_body)."""
        self._provider_kwargs = kwargs

    def set_no_think(self, enabled: bool = True) -> None:
        """Enable no-think mode: skips reasoning via </think> assistant prefix."""
        self._no_think = enabled

    def _call_provider(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> CompletionResult:
        """Override to pass extra provider kwargs and no-think prefix."""
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=system_prompt),
            ChatMessage(role=MessageRole.USER, content=user_prompt),
        ]
        if self._no_think:
            messages.append(
                ChatMessage(role=MessageRole.ASSISTANT, content="</think>"),
            )
        return self.provider.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **self._provider_kwargs,
        )

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
        """Build role-specific system and user prompts with helix phase adaptation.

        Prompt structure (optimized for KV cache sharing across agents):
          1. _SHARED_SYSTEM_PREFIX — identical for all 6 agents (multi-agent intro,
             JSON schema, "respond only with JSON")
          2. Phase block — shared within same tick (progress + directive)
          3. Role block — unique per agent (identity, description, allowed actions)
        """
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

        phase_block = (
            f"Progress: {progress_pct}% ({phase} phase).\n"
            f"{phase_directive}\n\n"
        )

        allowed = task.metadata.get("allowed_actions", [])
        allowed_str = ", ".join(allowed) if allowed else "any"

        role_block = (
            f"You are the {self.ROLE_NAME} for this colony. "
            f"{self._get_role_description()}\n\n"
            f"ALLOWED ACTIONS: {allowed_str}"
        )

        system_prompt = _SHARED_SYSTEM_PREFIX + phase_block + role_block

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
        raw = repair_json(result.content.strip())

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ActionPlanParseError(result.content, f"Invalid JSON after repair: {e}") from e

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
            try:
                actions.append(
                    Action(
                        action_type=action_type,
                        target_colonist_id=raw_action.get("target_colonist_id"),
                        parameters=raw_action.get("parameters", {}),
                        priority=raw_action.get("priority", 5),
                        reason=raw_action.get("reason", ""),
                    )
                )
            except (ValueError, TypeError, Exception) as e:
                logger.warning("Skipping action with validation error: %s", e)
                continue

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

        try:
            plan = self.parse_action_plan(result, state.colony.tick)
        except ActionPlanParseError as first_error:
            logger.warning(
                "%s: parse failed, retrying with correction prompt: %s",
                self.ROLE_NAME, first_error.reason,
            )
            retry_result = self._retry_with_correction(result.content, first_error.reason)
            plan = self.parse_action_plan(retry_result, state.colony.tick)

        self._last_action_plan = plan
        return plan

    def _retry_with_correction(self, bad_output: str, error: str) -> LLMResult:
        """Retry with a short correction prompt asking the LLM to fix its JSON."""
        system_prompt = (
            "You previously produced invalid JSON. Fix the error and return ONLY "
            "valid JSON matching the required schema. No explanation, no markdown."
        )
        user_prompt = (
            f"Your previous output had this error: {error}\n\n"
            f"Original output (fix this):\n{bad_output[:2000]}\n\n"
            "Return ONLY the corrected JSON object."
        )
        completion = self._call_provider(
            system_prompt, user_prompt, temperature=0.1, max_tokens=self.max_tokens,
        )
        self.total_tokens_used += completion.total_tokens
        return LLMResult(
            agent_id=self.agent_id,
            task_id="retry",
            content=completion.content,
            position_info=self.get_position_info(),
            completion_result=completion,
            processing_time=0.0,
            confidence=0.0,
            temperature_used=0.1,
            token_budget_used=completion.total_tokens,
        )
