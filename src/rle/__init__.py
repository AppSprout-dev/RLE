"""RLE — RimWorld Learning Environment.

Multi-agent benchmark where Felix Agent SDK agents play RimWorld.
"""

__version__ = "0.1.0"

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
    "RLEConfig",
    "RimAPIClient",
    "ColonistData",
    "ColonyData",
    "GameState",
    "MapData",
    "ResearchData",
    "ResourceData",
    "StructureData",
    "ThreatData",
    "WeatherData",
]
