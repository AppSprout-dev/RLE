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


class ZoneData(BaseModel):
    """A zone on the map (growing, stockpile, dumping, etc.)."""

    model_config = ConfigDict(frozen=True)

    zone_id: str
    zone_type: str
    label: str
    cell_count: int
    plant_def: str | None = None


class RoomData(BaseModel):
    """A room detected on the map."""

    model_config = ConfigDict(frozen=True)

    room_id: str
    role: str
    size: int
    temperature: float
    impressiveness: float = 0.0
    bed_count: int = 0


class OreDeposit(BaseModel):
    """An ore deposit cluster on the map."""

    model_config = ConfigDict(frozen=True)

    def_name: str
    count: int
    positions: list[tuple[int, int]] = []


class FarmSummary(BaseModel):
    """Summary of farming activity on the map."""

    model_config = ConfigDict(frozen=True)

    total_growing_zones: int
    planted_cells: int
    harvestable_cells: int
    crops: dict[str, int] = {}


class AreaRect(BaseModel):
    """A rectangular area on the map."""

    model_config = ConfigDict(frozen=True)

    x1: int
    z1: int
    x2: int
    z2: int
    label: str = ""


class TerrainSummary(BaseModel):
    """Deterministic spatial analysis computed from terrain data."""

    model_config = ConfigDict(frozen=True)

    colony_center: tuple[int, int] = (125, 125)
    build_areas: list[AreaRect] = []
    farm_areas: list[AreaRect] = []
    water_areas: list[AreaRect] = []
    rock_areas: list[AreaRect] = []
    recommended_stockpile: AreaRect | None = None
    recommended_shelter: AreaRect | None = None
    recommended_farm: AreaRect | None = None


class MapData(BaseModel):
    """Map metadata and structures."""

    model_config = ConfigDict(frozen=True)

    size: tuple[int, int]
    biome: str
    season: str
    temperature: float
    structures: list[StructureData]
    zones: list[ZoneData] = []
    rooms: list[RoomData] = []
    ore_deposits: list[OreDeposit] = []
    farm_summary: FarmSummary | None = None
    terrain: TerrainSummary | None = None


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


class PowerData(BaseModel):
    """Power grid state from /api/v1/map/power/info."""

    model_config = ConfigDict(frozen=True)

    current_power: float
    total_consumption: float
    stored_power: float
    storage_capacity: float


class FactionData(BaseModel):
    """A faction and its relation to the player colony."""

    model_config = ConfigDict(frozen=True)

    name: str
    def_name: str
    goodwill: int
    relation: str


class AlertData(BaseModel):
    """An active in-game alert from /api/v1/ui/alerts."""

    model_config = ConfigDict(frozen=True)

    label: str
    explanation: str
    priority: str
    target_ids: list[int] = []
    cells: list[str] = []


class ScreenshotResponse(BaseModel):
    """Map screenshot response from /api/v1/camera/screenshot."""

    model_config = ConfigDict(frozen=True)

    data_uri: str
    width: int
    height: int
    size_bytes: int
    game_tick: int


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
    power: PowerData | None = None
    factions: list[FactionData] = []
    alerts: list[AlertData] = []
