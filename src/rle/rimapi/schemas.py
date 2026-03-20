"""Pydantic models for RIMAPI game state data."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StructureData(BaseModel):
    """A built structure on the map."""

    model_config = ConfigDict(frozen=True)

    structure_id: str
    def_name: str
    position: tuple[int, int]
    hit_points: float
    max_hit_points: float


class ColonistData(BaseModel):
    """Snapshot of a single colonist's state."""

    model_config = ConfigDict(frozen=True)

    colonist_id: str
    name: str
    health: float
    mood: float
    skills: dict[str, int]
    traits: list[str]
    current_job: str | None
    is_drafted: bool
    needs: dict[str, float]
    injuries: list[str]
    position: tuple[int, int]


class ResourceData(BaseModel):
    """Colony-wide resource stockpile."""

    model_config = ConfigDict(frozen=True)

    food: float
    medicine: int
    steel: int
    wood: int
    components: int
    silver: int
    power_net: float
    items: dict[str, int] = {}


class MapData(BaseModel):
    """Map metadata and structures."""

    model_config = ConfigDict(frozen=True)

    size: tuple[int, int]
    biome: str
    season: str
    temperature: float
    structures: list[StructureData]


class ResearchData(BaseModel):
    """Research progress and available projects."""

    model_config = ConfigDict(frozen=True)

    current_project: str | None
    progress: float
    completed: list[str]
    available: list[str]


class ThreatData(BaseModel):
    """An active or incoming threat."""

    model_config = ConfigDict(frozen=True)

    threat_id: str
    threat_type: str
    faction: str | None
    enemy_count: int
    threat_level: float


class ColonyData(BaseModel):
    """High-level colony summary."""

    model_config = ConfigDict(frozen=True)

    name: str
    wealth: float
    day: int
    tick: int
    population: int
    mood_average: float
    food_days: float


class WeatherData(BaseModel):
    """Current weather conditions."""

    model_config = ConfigDict(frozen=True)

    condition: str
    temperature: float
    outdoor_severity: float


class GameState(BaseModel):
    """Composite snapshot of full colony state for a single tick."""

    model_config = ConfigDict(frozen=True)

    colony: ColonyData
    colonists: list[ColonistData]
    resources: ResourceData
    map: MapData
    research: ResearchData
    threats: list[ThreatData]
    weather: WeatherData
    timestamp: float
