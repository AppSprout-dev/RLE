"""ConstructionPlanner role agent — base layout, blueprints, repairs."""

from __future__ import annotations

from typing import Any, ClassVar

from rle.agents.base_role import RimWorldRoleAgent
from rle.rimapi.schemas import GameState


class ConstructionPlanner(RimWorldRoleAgent):
    """Plans colony infrastructure, buildings, and repairs."""

    ROLE_NAME: ClassVar[str] = "construction_planner"
    ALLOWED_ACTIONS: ClassVar[set[str]] = {
        "place_blueprint",
        "cancel_blueprint",
        "designate_area",
        "no_action",
    }
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.2, 0.6)

    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        """Extract construction-relevant data from the full game state."""
        return {
            "colony": {
                "day": state.colony.day,
                "wealth": state.colony.wealth,
            },
            "resources": {
                "steel": state.resources.steel,
                "wood": state.resources.wood,
                "components": state.resources.components,
            },
            "map": {
                "size": state.map.size,
                "structures": [
                    {
                        "structure_id": s.structure_id,
                        "def_name": s.def_name,
                        "position": s.position,
                        "hit_points": s.hit_points,
                        "max_hit_points": s.max_hit_points,
                    }
                    for s in state.map.structures
                ],
            },
            "colonists": [
                {
                    "colonist_id": c.colonist_id,
                    "name": c.name,
                    "skills": {
                        k: v for k, v in c.skills.items() if k == "construction"
                    },
                    "current_job": c.current_job,
                }
                for c in state.colonists
            ],
            "damaged_structures": sum(
                1
                for s in state.map.structures
                if s.hit_points < s.max_hit_points * 0.5
            ),
            "recent_events": self._format_events(
                "letter_received", "pawn_killed",
            ),
        }

    def _get_task_description(self) -> str:
        return (
            "Analyze structures, available materials, and construction needs. "
            "Propose blueprints for expansion, fortification, or critical repairs."
        )

    def _get_role_description(self) -> str:
        return (
            "You manage colony infrastructure and expansion. Your domain is "
            "construction: proposing new buildings, defensive walls, storage "
            "rooms, and repairs. Balance resource constraints (steel, wood, "
            "components) against structural needs, prioritizing critical repairs "
            "and strategic expansions."
        )
