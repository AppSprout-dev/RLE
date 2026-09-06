"""Conflict resolution for multi-agent action plans.

Arbitration is general (role × action type), not scenario-specific.

Pawn-targeted writes are grouped by ``(colonist_id, canonical action_type)``
after ``resolve_endpoint`` so complementary types on the same pawn coexist
(``work_priority`` and ``time_assignment`` are not the same write). Within a
group the winner is deterministic:

1. lower ``Action.priority`` number
2. role-priority table (crisis promotion for defense / medical)
3. higher plan confidence
4. last-writer (later plan, then later action in that plan)

``work_priority`` is merged across roles: each work type keeps the winning
role's value so Growing=1 from ResourceManager and Construction=1 from
ConstructionPlanner both survive, while Growing=1 vs Growing=4 is a
same-type conflict.

``no_action`` never vetoes another role's real write. Timed-out or failed
deliberations must not be passed in — callers hand only successful plans.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from rle.agents.actions import Action, ActionPlan, resolve_endpoint
from rle.rimapi.schemas import GameState

logger = logging.getLogger(__name__)

# Default role priorities (lower number = higher priority).
# Crisis promotion (raid → defense_commander, medical → medical_officer)
# overrides these to 1. Documented so ablation / custom rosters stay stable.
ROLE_PRIORITY: dict[str, int] = {
    "map_analyst": 10,
    "resource_manager": 3,
    "defense_commander": 3,
    "research_director": 5,
    "social_overseer": 5,
    "construction_planner": 5,
    "medical_officer": 4,
}
_DEFAULT_ROLE_PRIORITY = ROLE_PRIORITY

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
    seq: int


@dataclass(frozen=True)
class ResolverStats:
    """Conflict statistics from a single resolve() call."""

    conflicts_total: int
    conflicts_resolved: int


def _winner_key(ta: _TaggedAction) -> tuple[int, int, float, int]:
    """Sort key for ``min``: lower wins. Last-writer is ``-seq``."""
    return (ta.action.priority, ta.role_priority, -ta.plan_confidence, -ta.seq)


def _work_priorities(params: dict[str, Any]) -> dict[str, int]:
    """Accepted work_priority shapes, tolerant of garbage."""
    nested = params.get("work_priorities")
    if isinstance(nested, dict):
        return {str(work): int(pri) for work, pri in nested.items() if isinstance(pri, int)}
    if "work_type" in params:
        pri = params.get("priority", 1)
        return {str(params["work_type"]): int(pri)} if isinstance(pri, int) else {}
    return {
        str(work): pri for work, pri in params.items()
        if isinstance(pri, int) and not isinstance(pri, bool)
    }


def _merge_work_priority(candidates: list[_TaggedAction]) -> Action:
    """Keep the winning priority per work type; emit one action."""
    by_type: dict[str, _TaggedAction] = {}
    for ta in candidates:
        for work in _work_priorities(ta.action.parameters):
            prev = by_type.get(work)
            if prev is None or _winner_key(ta) < _winner_key(prev):
                by_type[work] = ta
    base = min(candidates, key=_winner_key).action
    if not by_type:
        return base
    parameters = {
        work: _work_priorities(ta.action.parameters)[work]
        for work, ta in by_type.items()
    }
    return Action(
        action_type=base.action_type,
        target_colonist_id=base.target_colonist_id,
        parameters=parameters,
        priority=base.priority,
        reason=base.reason,
    )


class ActionResolver:
    """Merges multiple ActionPlans into a single conflict-free plan."""

    def resolve(
        self, plans: list[ActionPlan], state: GameState,
    ) -> tuple[ActionPlan, ResolverStats]:
        """Apply priority rules and return a merged ActionPlan with conflict stats."""
        # Callers must omit timed-out / parse-failed deliberations. Empty
        # plans contribute no writes.
        if not plans:
            return (
                ActionPlan(role="orchestrator", tick=state.colony.tick, actions=[]),
                ResolverStats(conflicts_total=0, conflicts_resolved=0),
            )

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

        resolved_colony, col_detected, col_resolved = self._resolve_colony_actions(
            colony_actions,
        )
        resolved_pawn, pawn_detected, pawn_resolved = self._resolve_pawn_conflicts(
            pawn_actions,
        )

        resolved: list[Action] = []
        resolved.extend(resolved_colony)
        resolved.extend(resolved_pawn)

        avg_confidence = sum(p.confidence for p in plans) / len(plans)

        plan = ActionPlan(
            role="orchestrator",
            tick=state.colony.tick,
            actions=resolved,
            summary=f"Merged {len(plans)} agent plans ({len(resolved)} actions)",
            confidence=round(avg_confidence, 3),
        )
        stats = ResolverStats(
            conflicts_total=col_detected + pawn_detected,
            conflicts_resolved=col_resolved + pawn_resolved,
        )
        return plan, stats

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
        base = ROLE_PRIORITY.get(role, 5)
        if crisis.raid_active and role == "defense_commander":
            return 1
        if crisis.medical_emergency and role == "medical_officer":
            return 1
        return base

    def _tag_actions(
        self, plans: list[ActionPlan], crisis: CrisisState,
    ) -> list[_TaggedAction]:
        tagged: list[_TaggedAction] = []
        seq = 0
        for plan in plans:
            rp = self._get_role_priority(plan.role, crisis)
            for action in plan.actions:
                tagged.append(
                    _TaggedAction(
                        action=action,
                        role=plan.role,
                        role_priority=rp,
                        plan_confidence=plan.confidence,
                        seq=seq,
                    )
                )
                seq += 1
        return tagged

    # ------------------------------------------------------------------
    # Conflict resolution
    # ------------------------------------------------------------------

    def _resolve_pawn_conflicts(
        self, actions: list[_TaggedAction],
    ) -> tuple[list[Action], int, int]:
        """One winner (or merged work_priority) per pawn × action type.

        Complementary types on the same pawn are kept. ``no_action`` is
        dropped when any other write targets that pawn.

        Returns (resolved_actions, conflicts_detected, conflicts_resolved).
        """
        by_key: dict[tuple[str, str], list[_TaggedAction]] = {}
        for ta in actions:
            cid = ta.action.target_colonist_id or ""
            kind = resolve_endpoint(ta.action.action_type)
            by_key.setdefault((cid, kind), []).append(ta)

        kept: list[tuple[str, Action]] = []
        detected = 0
        resolved_count = 0
        for (cid, kind), candidates in by_key.items():
            if len(candidates) > 1:
                detected += 1
                resolved_count += 1
                losers = [
                    f"{ta.role}:{ta.action.action_type}" for ta in candidates
                ]
                logger.info(
                    "Pawn %s %s conflict among %s",
                    cid, kind, ", ".join(losers),
                )
            if kind == "work_priority":
                kept.append((cid, _merge_work_priority(candidates)))
            else:
                winner = min(candidates, key=_winner_key)
                kept.append((cid, winner.action))

        real_pawns = {
            cid for cid, action in kept
            if resolve_endpoint(action.action_type) != "no_action"
        }
        resolved = [
            action for cid, action in kept
            if resolve_endpoint(action.action_type) != "no_action" or cid not in real_pawns
        ]
        return resolved, detected, resolved_count

    def _resolve_colony_actions(
        self, actions: list[_TaggedAction],
    ) -> tuple[list[Action], int, int]:
        """Deduplicate colony-level actions by canonical type.

        Returns (resolved_actions, conflicts_detected, conflicts_resolved).
        """
        by_type: dict[str, list[_TaggedAction]] = {}
        for ta in actions:
            kind = resolve_endpoint(ta.action.action_type)
            by_type.setdefault(kind, []).append(ta)

        resolved: list[Action] = []
        detected = 0
        resolved_count = 0
        for _action_type, candidates in by_type.items():
            if len(candidates) > 1:
                detected += 1
                resolved_count += 1
            winner = min(candidates, key=_winner_key)
            resolved.append(winner.action)
        return resolved, detected, resolved_count
