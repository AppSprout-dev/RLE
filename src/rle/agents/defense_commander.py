"""DefenseCommander role agent — raids, drafting, positioning, weapons."""

from __future__ import annotations

from typing import Any, ClassVar

from rle.agents.base_role import RimWorldRoleAgent
from rle.rimapi.schemas import GameState


class DefenseCommander(RimWorldRoleAgent):
    """Manages colony defense against external threats."""

    ROLE_NAME: ClassVar[str] = "defense_commander"
    ALLOWED_ACTIONS: ClassVar[set[str]] = {
        "draft_colonist",
        "undraft_colonist",
        "move_colonist",
        "no_action",
    }
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.1, 0.6)

    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        """Extract defense-relevant data from the full game state."""
        combat_skills = {"melee", "shooting"}
        return {
            "colony": {
                "day": state.colony.day,
                "population": state.colony.population,
                "mood_average": state.colony.mood_average,
            },
            "threats": [
                {
                    "threat_id": t.threat_id,
                    "threat_type": t.threat_type,
                    "faction": t.faction,
                    "enemy_count": t.enemy_count,
                    "threat_level": t.threat_level,
                }
                for t in state.threats
            ],
            "colonists": [
                {
                    "colonist_id": c.colonist_id,
                    "name": c.name,
                    "health": c.health,
                    "mood": c.mood,
                    "skills": {k: v for k, v in c.skills.items() if k in combat_skills},
                    "traits": c.traits,
                    "is_drafted": c.is_drafted,
                    "current_job": c.current_job,
                    "position": c.position,
                    "injuries": c.injuries,
                }
                for c in state.colonists
            ],
            "active_threat_count": len(state.threats),
            "highest_threat_level": max(
                (t.threat_level for t in state.threats), default=0.0,
            ),
            "recent_events": self._format_events(
                "letter_received", "message_received", "pawn_entered_map", "pawn_killed",
            ),
        }

    def _get_task_description(self) -> str:
        return (
            "Analyze active threats and propose defensive actions. Draft "
            "combat-capable colonists, position them strategically, and "
            "manage the colony's military response."
        )

    def _get_role_description(self) -> str:
        return (
            "You are the colony's military commander. Your domain is defense "
            "against external threats: raids, infestations, and mechanoid attacks. "
            "You assess threat severity, identify combat-capable pawns, draft and "
            "position them for maximum defense. When a raid is active "
            "(threat_level > 0.5), your actions take priority over other roles."
        )
