"""SocialOverseer role agent — mood, recreation, mental break prevention."""

from __future__ import annotations

from typing import Any, ClassVar

from rle.agents.actions import ActionType
from rle.agents.base_role import RimWorldRoleAgent
from rle.rimapi.schemas import GameState


class SocialOverseer(RimWorldRoleAgent):
    """Oversees colony social health, morale, and recreation."""

    ROLE_NAME: ClassVar[str] = "social_overseer"
    ALLOWED_ACTIONS: ClassVar[set[ActionType]] = {
        ActionType.SET_RECREATION_POLICY,
        ActionType.ASSIGN_SOCIAL_ACTIVITY,
        ActionType.NO_ACTION,
    }
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.3, 0.7)

    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        """Extract social/mood-relevant data from the full game state."""
        return {
            "colony": {
                "day": state.colony.day,
                "mood_average": state.colony.mood_average,
                "population": state.colony.population,
            },
            "colonists": [
                {
                    "colonist_id": c.colonist_id,
                    "name": c.name,
                    "mood": c.mood,
                    "needs": c.needs,
                    "traits": c.traits,
                    "health": c.health,
                    "is_drafted": c.is_drafted,
                }
                for c in state.colonists
            ],
            "mood_crisis": any(c.mood < 0.3 for c in state.colonists),
            "low_mood_colonists": [
                c.colonist_id for c in state.colonists if c.mood < 0.4
            ],
            "season": state.map.season,
        }

    def _get_task_description(self) -> str:
        return (
            "Analyze colonist moods and needs. Propose recreation policies "
            "and social activities to improve morale and prevent mental breaks."
        )

    def _get_role_description(self) -> str:
        return (
            "You oversee colony social health and morale. Your domain is "
            "recreation, needs fulfillment, and mental health. You track mood "
            "trends, identify at-risk pawns (mood < 0.4), and propose recreation "
            "policies and social activities to keep the colony mentally stable. "
            "Prevent mental breaks through proactive morale management."
        )
