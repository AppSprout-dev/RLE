"""MapAnalyst role agent — spatial reasoning and map analysis."""

from __future__ import annotations

from typing import Any, ClassVar

from rle.agents.base_role import RimWorldRoleAgent
from rle.rimapi.schemas import GameState

# Bootstrap directive for early game (day < 5).
_MAP_ANALYST_BOOTSTRAP = (
    "EARLY GAME BOOTSTRAP: The colony has JUST STARTED. Your analysis is critical "
    "for other agents to place buildings, zones, and designations correctly.\n"
    "You MUST identify:\n"
    "1. Colony center — average position of colonists (near drop pods)\n"
    "2. Nearest FLAT, NON-WATER area for shelter (5x5+ clear ground near center)\n"
    "3. Nearest FERTILE SOIL for farming (look for growing zones or soil tiles)\n"
    "4. Nearest ORE deposits (steel, components) for mining designations\n"
    "5. WATER features and cliffs to AVOID building on\n"
    "6. Recommended stockpile location (near center, on solid ground)\n"
    "Include specific (x, z) coordinates for ALL recommendations.\n\n"
)


class MapAnalyst(RimWorldRoleAgent):
    """Analyzes the colony map for spatial features and provides location recommendations."""

    ROLE_NAME: ClassVar[str] = "map_analyst"
    ALLOWED_ACTIONS: ClassVar[set[str]] = {"no_action"}
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.1, 0.4)

    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        """Extract all spatial data for map analysis."""
        return {
            "colony": {
                "day": state.colony.day,
                "population": state.colony.population,
            },
            "map": {
                "size": state.map.size,
                "biome": state.map.biome,
                "season": state.map.season,
            },
            "colonist_positions": [
                {"colonist_id": c.colonist_id, "name": c.name, "position": c.position}
                for c in state.colonists
            ],
            "structures": [
                {
                    "def_name": s.def_name,
                    "position": s.position,
                }
                for s in state.map.structures
            ],
            "zones": [z.model_dump() for z in state.map.zones],
            "rooms": [r.model_dump() for r in state.map.rooms],
            "ore_deposits": [o.model_dump() for o in state.map.ore_deposits],
            "farm_summary": (
                state.map.farm_summary.model_dump()
                if state.map.farm_summary
                else None
            ),
            "recent_events": self._format_events(
                "letter_received", "map_changed",
            ),
        }

    def _get_task_description(self) -> str:
        return (
            "Analyze the colony map spatial data (zones, rooms, ore deposits, "
            "structures, colonist positions) and produce a detailed spatial "
            "analysis with specific (x, z) coordinates for building, farming, "
            "and mining recommendations. Put your full analysis in the summary field."
        )

    def _get_role_description(self) -> str:
        return (
            "You are the MAP ANALYST. You run FIRST each tick and your output "
            "is read by all other agents to guide their spatial decisions. "
            "You do NOT execute actions — you provide SPATIAL ANALYSIS.\n\n"
            "Your summary MUST include:\n"
            "- Colony center coordinates (average of colonist positions)\n"
            "- Recommended BUILD SITE: (x1,z1)-(x2,z2) on solid ground, "
            "away from water. State what structures should go there.\n"
            "- Recommended FARM AREA: (x1,z1)-(x2,z2) on fertile soil. "
            "If growing zones already exist, note their status.\n"
            "- ORE LOCATIONS: list each ore type with coordinates and count.\n"
            "- ROOM STATUS: list existing rooms (bedroom, kitchen, etc.), "
            "note missing critical rooms.\n"
            "- ZONE STATUS: list existing zones, note gaps (no stockpile? "
            "no growing zone?).\n"
            "- HAZARDS: water features, mountain edges, or areas to avoid.\n\n"
            "Always use specific (x, z) coordinates. Other agents will use "
            "your coordinates for blueprint, growing_zone, stockpile_zone, "
            "and designate_area actions. Your actions list should contain "
            "only no_action."
        )

    def create_position_aware_prompt(
        self, task: "LLMTask",  # noqa: F821
    ) -> tuple[str, str]:
        """Override to inject bootstrap directive for early game."""
        system_prompt, user_prompt = super().create_position_aware_prompt(task)
        day = task.metadata.get("day", 999)
        if day < 5:
            system_prompt = system_prompt + "\n\n" + _MAP_ANALYST_BOOTSTRAP
        return system_prompt, user_prompt
