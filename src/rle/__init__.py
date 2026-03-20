"""RLE — RimWorld Learning Environment.

Multi-agent benchmark where Felix Agent SDK agents play RimWorld.
"""

__version__ = "0.1.0"

from rle.agents import (
    Action,
    ActionPlan,
    ActionPlanParseError,
    ActionType,
    ResourceManager,
    RimWorldRoleAgent,
    register_rle_agents,
)
from rle.config import RLEConfig
from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import (
    ColonistData,
    ColonyData,
    GameState,
    MapData,
    ResearchData,
    ResourceData,
    StructureData,
    ThreatData,
    WeatherData,
)

__all__ = [
    "Action",
    "ActionPlan",
    "ActionPlanParseError",
    "ActionType",
    "ColonistData",
    "ColonyData",
    "GameState",
    "MapData",
    "RLEConfig",
    "ResearchData",
    "ResourceData",
    "ResourceManager",
    "RimAPIClient",
    "RimWorldRoleAgent",
    "StructureData",
    "ThreatData",
    "WeatherData",
    "register_rle_agents",
]
