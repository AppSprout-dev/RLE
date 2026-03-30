"""ResearchDirector role agent — tech tree priorities, researcher assignment."""

from __future__ import annotations

from typing import Any, ClassVar

from rle.agents.base_role import RimWorldRoleAgent
from rle.rimapi.schemas import GameState


class ResearchDirector(RimWorldRoleAgent):
    """Directs colony technology advancement and researcher allocation."""

    ROLE_NAME: ClassVar[str] = "research_director"
    ALLOWED_ACTIONS: ClassVar[set[str]] = {
        "set_research_target",
        "assign_researcher",
        "no_action",
    }
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.3, 0.8)

    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        """Extract research-relevant data from the full game state."""
        return {
            "colony": {
                "day": state.colony.day,
                "wealth": state.colony.wealth,
            },
            "research": {
                "current_project": state.research.current_project,
                "progress": state.research.progress,
                "completed": state.research.completed,
                "available": state.research.available,
            },
            "colonists": [
                {
                    "colonist_id": c.colonist_id,
                    "name": c.name,
                    "skills": {
                        k: v for k, v in c.skills.items() if k == "intellectual"
                    },
                    "current_job": c.current_job,
                    "mood": c.mood,
                }
                for c in state.colonists
            ],
            "recent_events": self._format_events(
                "colonist_crafted", "colonist_bill_work",
            ),
        }

    def _get_task_description(self) -> str:
        return (
            "Analyze available research projects and colonist intellectual "
            "skills. Propose which technology to research next and assign "
            "capable researchers to the bench."
        )

    def _get_role_description(self) -> str:
        return (
            "You direct the colony's technology advancement. Your domain is "
            "research: identifying critical missing technologies, prioritizing "
            "projects based on colony needs (defensive, economic, medical), and "
            "assigning skilled colonists to research benches. Balance immediate "
            "survival needs with long-term advancement."
        )
