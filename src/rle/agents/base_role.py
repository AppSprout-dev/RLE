"""Base class for all RLE role-specialized agents."""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from typing import Any, ClassVar, Tuple

from felix_agent_sdk import LLMAgent, LLMResult, LLMTask
from felix_agent_sdk.communication import Spoke
from felix_agent_sdk.core import HelixGeometry
from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.providers.types import ChatMessage, CompletionResult, MessageRole
from felix_agent_sdk.tokens.budget import TokenBudget

from rle.agents.actions import Action, ActionPlan, ActionPlanParseError
from rle.agents.json_repair import repair_json
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent

logger = logging.getLogger(__name__)

# Shared prefix for all 6 role agents. Placed first in the system prompt so
# LM Studio / llama.cpp can reuse the KV cache across agents within a tick.
_SHARED_SYSTEM_PREFIX = (
    "You are one of 7 specialized role agents managing a RimWorld colony. "
    "The agents are: MapAnalyst, ResourceManager, DefenseCommander, ResearchDirector, "
    "SocialOverseer, ConstructionPlanner, and MedicalOfficer.\n"
    "The MapAnalyst runs FIRST each tick and provides spatial recommendations "
    "(build locations, farm areas, ore deposits) via inter-agent messages. "
    "Check your inter-agent context for MapAnalyst spatial data before choosing "
    "coordinates for blueprints, zones, or designations.\n\n"
    "You MUST respond with a JSON object:\n"
    '{"actions": [{"action_type": "<endpoint>", "target_colonist_id": "<id or null>", '
    '"parameters": {}, "priority": <1-10>, "reason": "<why>"}], '
    '"summary": "<brief>", "confidence": <0.0-1.0>}\n\n'
    "AVAILABLE ACTIONS (use these as action_type):\n"
    "- work_priority: Set colonist work priority. params: {\"<WorkType>\": <1-4>}. "
    "target_colonist_id required. "
    "VALID WORK TYPES: Firefighter, Patient, Doctor, PatientBedRest, "
    "BasicWorker, Warden, Handling, Cooking, Hunting, Construction, "
    "Growing, Mining, PlantCutting, Smithing, Tailoring, Art, Crafting, "
    "Hauling, Cleaning, Research. Use EXACTLY these names.\n"
    "- blueprint: Place a building. params: {\"def_name\": \"Wall\", \"x\": int, "
    "\"z\": int, \"stuff_def\": \"WoodLog\", \"rotation\": 0}.\n"
    "- growing_zone: Create growing zone. params: {\"plant_def\": \"Plant_Potato\", "
    "\"x1\": int, \"z1\": int, \"x2\": int, \"z2\": int}.\n"
    "- stockpile_zone: Create stockpile. params: {\"x1\": int, \"z1\": int, "
    "\"x2\": int, \"z2\": int, \"name\": \"Supply\"}.\n"
    "- designate_area: Mine/harvest/deconstruct. params: {\"type\": \"Mine\", "
    "\"x1\": int, \"z1\": int, \"x2\": int, \"z2\": int}.\n"
    "- draft: Draft/undraft colonist. params: {\"is_drafted\": true/false}. "
    "target_colonist_id required.\n"
    "- move: Move colonist. params: {\"x\": int, \"z\": int}. "
    "target_colonist_id required.\n"
    "- research_target: Set research. params: {\"project\": \"Electricity\"}.\n"
    "- research_stop: Stop current research. No params.\n"
    "- job_assign: Assign job directly. params: {\"job_def\": \"Sow\"}. "
    "target_colonist_id required.\n"
    "- time_assignment: Set schedule. params: {\"hours\": [18,19,20], "
    "\"assignment\": \"Joy\"}. target_colonist_id required.\n"
    "- bed_rest: Assign bed rest. target_colonist_id required.\n"
    "- tend: Have doctor tend patient. params: {\"doctor_pawn_id\": int}. "
    "target_colonist_id = patient.\n"
    "- toggle_power: Toggle building power. params: {\"building_id\": int, "
    "\"power_on\": true}.\n"
    "- no_action: Do nothing (use when colonists are already productive).\n\n"
    "RULES:\n"
    "- target_colonist_id MUST be a valid colonist_id from the state.\n"
    "- CRITICAL: Propose work_priority actions for EVERY colonist, not just one. "
    "Each colonist needs their own work_priority action with their colonist_id. "
    "If there are 3 colonists, propose at least 3 work_priority actions.\n"
    "- Use colonist SKILLS to assign work: highest Plants→Growing=1, "
    "highest Construction→Construction=1, highest Intellectual→Research=1.\n"
    "- Check current_job: if a colonist is already doing useful work "
    "(Sow, Mine, Haul, Cook, Research), do NOT interrupt them.\n"
    "- Idle colonists (GotoWander, Wait_Wander, Wait_MaintainPosture) NEED "
    "work_priority assignments immediately.\n"
    "- Propose 5-15 actions per tick. Be proactive.\n"
    "- Respond ONLY with valid JSON.\n\n"
)

# Early-game directive injected when day < 5.
_EARLY_GAME_DIRECTIVE = (
    "EARLY GAME ALERT: The colony has just started. Colonists wandering or "
    "doing GotoWander/Wait_Wander are IDLE — they need direction NOW.\n"
    "Priority actions for day 0-3:\n"
    "1. Create a stockpile_zone near the drop pods for supplies\n"
    "2. Create a growing_zone for food (Plant_Potato or Plant_Rice)\n"
    "3. Set work_priority: best grower→Growing=1, best builder→Construction=1, "
    "best researcher→Research=1\n"
    "4. Place blueprint for shelter (walls + door = enclosed room)\n"
    "5. Set research_target to a useful early tech\n"
    "6. designate_area for mining steel/components nearby\n"
    "Do NOT propose no_action in early game. The colony needs everything.\n\n"
)


class RimWorldRoleAgent(LLMAgent):
    """Base class for RLE role agents.

    Bridges Felix SDK's LLMAgent with RimWorld-specific structured output:
    1. Injects GameState into LLMTask context (filtered per role)
    2. Overrides prompting with role identity + helix phase directives + JSON schema
    3. Parses LLM output into validated ActionPlan
    """

    ROLE_NAME: ClassVar[str] = "base"
    ALLOWED_ACTIONS: ClassVar[set[str]] = set()
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
        self._spoke: Spoke | None = None
        self._pending_events: list[RimAPIEvent] = []

    def set_provider_kwargs(self, **kwargs: Any) -> None:
        """Set extra kwargs passed to provider.complete() (e.g. extra_body)."""
        self._provider_kwargs = kwargs

    def set_no_think(self, enabled: bool = True) -> None:
        """Enable no-think mode: skips reasoning via </think> assistant prefix."""
        self._no_think = enabled

    def attach_spoke(self, spoke: Spoke) -> None:
        """Attach this agent's CentralPost spoke for inter-agent messaging."""
        self._spoke = spoke

    def set_pending_events(self, events: list[RimAPIEvent]) -> None:
        """Inject SSE events for this tick. Called by game loop before deliberation."""
        self._pending_events = events

    def _format_events(self, *event_types: str) -> list[dict[str, Any]]:
        """Filter and format pending SSE events by type for inclusion in game state."""
        return [
            {"event_type": e.event_type, "data": e.data}
            for e in self._pending_events
            if e.event_type in event_types
        ]

    def _get_spoke_context(self) -> list[dict[str, Any]]:
        """Read pending spoke messages and format as context for deliberation."""
        if not self._spoke or not self._spoke.has_pending_messages():
            return []
        messages = self._spoke.get_pending_messages()
        context = []
        for msg in messages:
            context.append({
                "agent_id": msg.sender_id,
                "message_type": msg.message_type.value,
                "content": msg.content.get("summary", str(msg.content)),
                "confidence": msg.content.get("confidence", 0.0),
            })
        return context

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
                "allowed_actions": sorted(self.ALLOWED_ACTIONS),
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

        # Early game: override passive behavior with bootstrap directive
        day = task.metadata.get("day", 999)
        early_game = _EARLY_GAME_DIRECTIVE if day < 5 else ""

        system_prompt = _SHARED_SYSTEM_PREFIX + early_game + phase_block + role_block

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

        if not isinstance(data, dict):
            raise ActionPlanParseError(
                result.content, f"Expected JSON object, got {type(data).__name__}",
            )

        actions: list[Action] = []
        for raw_action in data.get("actions", []):
            action_type = raw_action.get("action_type", "")
            if not action_type:
                logger.warning("Skipping action with no action_type")
                continue
            if action_type not in self.ALLOWED_ACTIONS:
                logger.warning(
                    "Skipping disallowed action %s for role %s",
                    action_type,
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

        # Spoke messages take priority; fall back to passed context_history
        spoke_context = self._get_spoke_context()
        effective_context = spoke_context if spoke_context else (context_history or [])
        task = self.build_task(state, effective_context)
        result = self.process_task(task)

        try:
            plan = self.parse_action_plan(result, state.colony.tick)
        except ActionPlanParseError as first_error:
            logger.warning(
                "%s: parse failed, retrying with correction prompt: %s",
                self.ROLE_NAME, first_error.reason,
            )
            try:
                retry_result = self._retry_with_correction(result.content, first_error.reason)
                plan = self.parse_action_plan(retry_result, state.colony.tick)
            except (ActionPlanParseError, Exception) as retry_error:
                raise ActionPlanParseError(
                    result.content, f"Retry also failed: {retry_error}",
                ) from retry_error

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
