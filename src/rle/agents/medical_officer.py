"""MedicalOfficer role agent — injuries, medicine, hospital management."""

from __future__ import annotations

from typing import Any, ClassVar

from rle.agents.actions import ActionType
from rle.agents.base_role import RimWorldRoleAgent
from rle.rimapi.schemas import GameState


class MedicalOfficer(RimWorldRoleAgent):
    """Manages colony health care, triage, and medicine allocation."""

    ROLE_NAME: ClassVar[str] = "medical_officer"
    ALLOWED_ACTIONS: ClassVar[set[ActionType]] = {
        ActionType.ASSIGN_BED_REST,
        ActionType.ADMINISTER_MEDICINE,
        ActionType.NO_ACTION,
    }
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.1, 0.5)

    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        """Extract medical-relevant data from the full game state."""
        return {
            "colony": {
                "day": state.colony.day,
                "population": state.colony.population,
            },
            "colonists": [
                {
                    "colonist_id": c.colonist_id,
                    "name": c.name,
                    "health": c.health,
                    "mood": c.mood,
                    "injuries": c.injuries,
                    "current_job": c.current_job,
                }
                for c in state.colonists
            ],
            "resources": {
                "medicine": state.resources.medicine,
            },
            "critical_patients": [
                {"colonist_id": c.colonist_id, "name": c.name, "health": c.health}
                for c in state.colonists
                if c.health < 0.5 or len(c.injuries) > 0
            ],
            "disease_active": any(
                t.threat_type == "disease" for t in state.threats
            ),
        }

    def _get_task_description(self) -> str:
        return (
            "Analyze colonist health status and injuries. Propose bed rest "
            "assignments and medicine administration to prevent casualties."
        )

    def _get_role_description(self) -> str:
        return (
            "You are the colony's chief medical officer. Your domain is health "
            "care: treating injuries, managing disease, and preventing deaths. "
            "Triage patients by severity, allocate limited medicine supplies, "
            "and assign bed rest for recovery. During plague or epidemic "
            "(disease threat active), your actions take priority over all other "
            "roles except DefenseCommander during active raids."
        )
