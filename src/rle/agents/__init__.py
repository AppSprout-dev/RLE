"""RLE role agents and registration."""

from felix_agent_sdk import AgentFactory

from rle.agents.actions import Action, ActionPlan, ActionPlanParseError, ActionType
from rle.agents.base_role import RimWorldRoleAgent
from rle.agents.resource_manager import ResourceManager

_ROLE_AGENTS: dict[str, type[RimWorldRoleAgent]] = {
    "resource_manager": ResourceManager,
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
    "ResourceManager",
    "RimWorldRoleAgent",
    "register_rle_agents",
]
