"""The Felix harness's role agents (MapAnalyst + 6 domain roles).

Everything here subclasses Felix SDK's ``LLMAgent``; nothing outside
``rle.harness.felix`` may import from this package.
"""

from felix_agent_sdk import AgentFactory

from rle.harness.felix.agents.base_role import RimWorldRoleAgent
from rle.harness.felix.agents.construction_planner import ConstructionPlanner
from rle.harness.felix.agents.defense_commander import DefenseCommander
from rle.harness.felix.agents.map_analyst import MapAnalyst
from rle.harness.felix.agents.medical_officer import MedicalOfficer
from rle.harness.felix.agents.research_director import ResearchDirector
from rle.harness.felix.agents.resource_manager import ResourceManager
from rle.harness.felix.agents.social_overseer import SocialOverseer

AGENT_DISPLAY: dict[str, dict[str, str]] = {
    "map_analyst":          {"label": "MA", "color": "blue"},
    "resource_manager":     {"label": "RM", "color": "green"},
    "defense_commander":    {"label": "DC", "color": "red"},
    "research_director":    {"label": "RD", "color": "cyan"},
    "social_overseer":      {"label": "SO", "color": "yellow"},
    "construction_planner": {"label": "CP", "color": "white"},
    "medical_officer":      {"label": "MO", "color": "magenta"},
}

_ROLE_AGENTS: dict[str, type[RimWorldRoleAgent]] = {
    "map_analyst": MapAnalyst,
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
    "AGENT_DISPLAY",
    "ConstructionPlanner",
    "DefenseCommander",
    "MapAnalyst",
    "MedicalOfficer",
    "ResearchDirector",
    "ResourceManager",
    "RimWorldRoleAgent",
    "SocialOverseer",
    "register_rle_agents",
]
