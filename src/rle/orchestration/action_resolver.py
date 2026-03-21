"""Conflict resolution for multi-agent action plans."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from rle.agents.actions import Action, ActionPlan
from rle.rimapi.schemas import GameState

logger = logging.getLogger(__name__)

# Default role priorities (lower number = higher priority).
_DEFAULT_ROLE_PRIORITY: dict[str, int] = {
    "resource_manager": 3,
    "defense_commander": 3,
    "research_director": 5,
    "social_overseer": 5,
    "construction_planner": 5,
    "medical_officer": 4,
}

RAID_THREAT_THRESHOLD = 0.5
MEDICAL_HEALTH_THRESHOLD = 0.5


class CrisisState(BaseModel):
    """Snapshot of emergency conditions detected from game state."""

    model_config = ConfigDict(frozen=True)

    max_threat_level: float
    disease_active: bool
    avg_health: float
    raid_active: bool
    medical_emergency: bool


@dataclass
class _TaggedAction:
    """Internal wrapper pairing an action with its source metadata."""

    action: Action
    role: str
    role_priority: int
    plan_confidence: float


class ActionResolver:
    """Merges multiple ActionPlans into a single conflict-free plan."""

    def resolve(self, plans: list[ActionPlan], state: GameState) -> ActionPlan:
        """Apply priority rules and return a merged ActionPlan."""
        if not plans:
            return ActionPlan(role="orchestrator", tick=state.colony.tick, actions=[])

        crisis = self._detect_crisis(state)
        tagged = self._tag_actions(plans, crisis)

        # Separate colony-level (no target) from pawn-level actions
        colony_actions: list[_TaggedAction] = []
        pawn_actions: list[_TaggedAction] = []
        for ta in tagged:
            if ta.action.target_colonist_id is None:
                colony_actions.append(ta)
            else:
                pawn_actions.append(ta)

        resolved: list[Action] = []
        resolved.extend(self._resolve_colony_actions(colony_actions))
        resolved.extend(self._resolve_pawn_conflicts(pawn_actions))

        avg_confidence = (
            sum(p.confidence for p in plans) / len(plans) if plans else 0.5
        )

        return ActionPlan(
            role="orchestrator",
            tick=state.colony.tick,
            actions=resolved,
            summary=f"Merged {len(plans)} agent plans ({len(resolved)} actions)",
            confidence=round(avg_confidence, 3),
        )

    # ------------------------------------------------------------------
    # Crisis detection
    # ------------------------------------------------------------------

    def _detect_crisis(self, state: GameState) -> CrisisState:
        max_threat = max(
            (t.threat_level for t in state.threats), default=0.0,
        )
        disease_active = any(t.threat_type == "disease" for t in state.threats)
        avg_health = (
            sum(c.health for c in state.colonists) / len(state.colonists)
            if state.colonists
            else 1.0
        )
        return CrisisState(
            max_threat_level=max_threat,
            disease_active=disease_active,
            avg_health=avg_health,
            raid_active=max_threat > RAID_THREAT_THRESHOLD,
            medical_emergency=disease_active or avg_health < MEDICAL_HEALTH_THRESHOLD,
        )

    # ------------------------------------------------------------------
    # Action tagging
    # ------------------------------------------------------------------

    def _get_role_priority(self, role: str, crisis: CrisisState) -> int:
        base = _DEFAULT_ROLE_PRIORITY.get(role, 5)
        if crisis.raid_active and role == "defense_commander":
            return 1
        if crisis.medical_emergency and role == "medical_officer":
            return 1
        return base

    def _tag_actions(
        self, plans: list[ActionPlan], crisis: CrisisState,
    ) -> list[_TaggedAction]:
        tagged: list[_TaggedAction] = []
        for plan in plans:
            rp = self._get_role_priority(plan.role, crisis)
            for action in plan.actions:
                tagged.append(
                    _TaggedAction(
                        action=action,
                        role=plan.role,
                        role_priority=rp,
                        plan_confidence=plan.confidence,
                    )
                )
        return tagged

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------

    def _resolve_pawn_conflicts(self, actions: list[_TaggedAction]) -> list[Action]:
        """Group by colonist, keep best action per pawn."""
        by_pawn: dict[str, list[_TaggedAction]] = {}
        for ta in actions:
            cid = ta.action.target_colonist_id or ""
            by_pawn.setdefault(cid, []).append(ta)

        resolved: list[Action] = []
        for cid, candidates in by_pawn.items():
            winner = min(
                candidates,
                key=lambda ta: (
                    ta.action.priority,   # Rule 2: lower priority number wins
                    ta.role_priority,     # Rule 1/3: role priority
                    -ta.plan_confidence,  # Rule 4: higher confidence wins (negate)
                ),
            )
            if len(candidates) > 1:
                losers = [
                    f"{ta.role}:{ta.action.action_type.value}" for ta in candidates
                    if ta is not winner
                ]
                logger.info(
                    "Pawn %s conflict: %s wins over %s",
                    cid, f"{winner.role}:{winner.action.action_type.value}",
                    ", ".join(losers),
                )
            resolved.append(winner.action)
        return resolved

    def _resolve_colony_actions(self, actions: list[_TaggedAction]) -> list[Action]:
        """Deduplicate colony-level actions by type, highest role priority wins."""
        by_type: dict[str, list[_TaggedAction]] = {}
        for ta in actions:
            by_type.setdefault(ta.action.action_type.value, []).append(ta)

        resolved: list[Action] = []
        for action_type, candidates in by_type.items():
            winner = min(
                candidates,
                key=lambda ta: (ta.role_priority, -ta.plan_confidence),
            )
            resolved.append(winner.action)
        return resolved
