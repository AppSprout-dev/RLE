"""ResourceManager role agent — food, materials, power, hauling."""

from __future__ import annotations

from typing import Any, ClassVar

from rle.agents.actions import ActionType
from rle.agents.base_role import RimWorldRoleAgent
from rle.rimapi.schemas import GameState


class ResourceManager(RimWorldRoleAgent):
    """Manages the colony's economy: food, raw materials, power, and hauling."""

    ROLE_NAME: ClassVar[str] = "resource_manager"
    ALLOWED_ACTIONS: ClassVar[set[ActionType]] = {
        ActionType.SET_WORK_PRIORITY,
        ActionType.HAUL_RESOURCE,
        ActionType.SET_GROWING_ZONE,
        ActionType.TOGGLE_POWER,
        ActionType.NO_ACTION,
    }
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.2, 0.7)

    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        """Extract resource-relevant data from the full game state."""
        resource_skills = {"growing", "cooking", "mining", "construction", "crafting"}
        return {
            "colony": {
                "name": state.colony.name,
                "day": state.colony.day,
                "population": state.colony.population,
                "food_days": state.colony.food_days,
            },
            "resources": state.resources.model_dump(),
            "colonists": [
                {
                    "colonist_id": c.colonist_id,
                    "name": c.name,
                    "skills": {
                        k: v for k, v in c.skills.items() if k in resource_skills
                    },
                    "current_job": c.current_job,
                    "health": c.health,
                }
                for c in state.colonists
            ],
            "weather": {
                "condition": state.weather.condition,
                "temperature": state.weather.temperature,
            },
            "season": state.map.season,
            "active_threats": len(state.threats),
        }

    def _get_task_description(self) -> str:
        return (
            "Analyze colony resource levels and propose actions to optimize "
            "food production, raw material gathering, and power management. "
            "Assign colonists to work priorities based on their skills and "
            "current colony needs."
        )

    def _get_role_description(self) -> str:
        return (
            "You manage the colony's economy: food (growing, hunting, cooking), "
            "raw materials (mining, woodcutting), power grid, and hauling logistics. "
            "Your goal is to prevent starvation, maintain material stockpiles for "
            "construction and crafting, and keep the power grid stable. Prioritize "
            "food security above all else when food_days drops below 3."
        )
