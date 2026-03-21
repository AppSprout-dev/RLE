"""RLE role agents and registration."""

from felix_agent_sdk import AgentFactory

from rle.agents.actions import Action, ActionPlan, ActionPlanParseError, ActionType
from rle.agents.base_role import RimWorldRoleAgent
from rle.agents.construction_planner import ConstructionPlanner
from rle.agents.defense_commander import DefenseCommander
from rle.agents.medical_officer import MedicalOfficer
from rle.agents.research_director import ResearchDirector
from rle.agents.resource_manager import ResourceManager
from rle.agents.social_overseer import SocialOverseer

_ROLE_AGENTS: dict[str, type[RimWorldRoleAgent]] = {
    "resource_manager": ResourceManager,
    "defense_commander": DefenseCommander,
    "research_director": ResearchDirector,
    "social_overseer": SocialOverseer,
    "construction_planner": ConstructionPlanner,
    "medical_officer": MedicalOfficer,
}


def register_rle_agents() -> None:
    """Register all RLE role agent types with the Felix AgentFactory."""
    for name, cls in _ROLE_AGENTS.items():
        AgentFactory.register_agent_type(name, cls)


__all__ = [
    "Action",
    "ActionPlan",
    "ActionPlanParseError",
    "ActionType",
    "ConstructionPlanner",
    "DefenseCommander",
    "MedicalOfficer",
    "ResearchDirector",
    "ResourceManager",
    "RimWorldRoleAgent",
    "SocialOverseer",
    "register_rle_agents",
]
