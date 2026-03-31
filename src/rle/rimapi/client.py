"""Async HTTP client for the RIMAPI RimWorld mod."""

from __future__ import annotations

import time
from types import TracebackType

import httpx

from rle.rimapi.schemas import (
    AreaRect,
    ColonistData,
    ColonyData,
    FarmSummary,
    GameState,
    MapData,
    OreDeposit,
    ResearchData,
    ResourceData,
    RoomData,
    StructureData,
    TerrainSummary,
    ThreatData,
    WeatherData,
    ZoneData,
)


class RimAPIError(Exception):
    """Base exception for RIMAPI errors."""


class RimAPIConnectionError(RimAPIError):
    """Failed to connect to the RIMAPI server."""


class RimAPIResponseError(RimAPIError):
    """RIMAPI returned an unexpected response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"RIMAPI {status_code}: {detail}")


class RimAPIClient:
    """Async client for reading/writing RimWorld game state via RIMAPI.

    Usage::

        async with RimAPIClient("http://localhost:8765") as client:
            colonists = await client.get_colonists()
    """

    def __init__(self, base_url: str = "http://localhost:8765") -> None:
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> RimAPIClient:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=10.0)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("RimAPIClient must be used as an async context manager")
        return self._client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str) -> dict:
        """Perform a GET request, unwrap RIMAPI envelope, return data payload."""
        try:
            resp = await self.client.get(path)
        except httpx.ConnectError as exc:
            raise RimAPIConnectionError(
                f"Cannot connect to RIMAPI at {self._base_url}"
            ) from exc

        if resp.status_code != 200:
            raise RimAPIResponseError(resp.status_code, resp.text)
        body = resp.json()
        # RIMAPI wraps all responses in {"success": bool, "data": ...}
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    async def call(self, method: str, path: str, json: dict | None = None) -> dict:
        """Generic endpoint call — used by the dynamic action dispatcher."""
        if method.upper() == "GET":
            return await self._get(path)
        return await self._post(path, json=json)

    async def _post(self, path: str, json: dict | None = None) -> dict:
        """Perform a POST request and return parsed JSON."""
        try:
            resp = await self.client.post(path, json=json or {})
        except httpx.ConnectError as exc:
            raise RimAPIConnectionError(
                f"Cannot connect to RIMAPI at {self._base_url}"
            ) from exc

        if resp.status_code not in (200, 201, 204):
            raise RimAPIResponseError(resp.status_code, resp.text)
        if resp.status_code == 204:
            return {}
        return resp.json()

    # ------------------------------------------------------------------
    # Read endpoints
    # Paths use upstream RIMAPI /api/v1/ convention.
    # NOTE: Upstream response shapes differ from our Pydantic models;
    # adapters will be needed when connecting to the live game.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Adapters: upstream response shapes → RLE Pydantic models
    # ------------------------------------------------------------------

    @staticmethod
    def _adapt_colonist(raw: dict) -> dict:
        """Map upstream detailed PawnDto → ColonistData fields.

        Handles three formats:
        - Detailed upstream: {colonist: {id, ...}, colonist_work_info: {skills, ...}, ...}
        - Basic upstream: {id, name, health, mood, hunger, position}
        - Mock/test: {colonist_id, name, skills, ...}
        """
        # Already in our schema format — pass through
        if "colonist_id" in raw:
            return raw

        # Detailed endpoint: {colonist: {...}, colonist_work_info: {...}, ...}
        pawn = raw.get("colonist", raw)
        work_info = raw.get("colonist_work_info", {})
        medical = raw.get("colonist_medical_info", {})

        pos = pawn.get("position", {})
        if isinstance(pos, dict):
            position = (pos.get("x", 0), pos.get("z", 0))
        elif isinstance(pos, (list, tuple)):
            position = (pos[0], pos[1]) if len(pos) >= 2 else (0, 0)
        else:
            position = (0, 0)

        # Map skills list → {name: level} dict
        skills_list = work_info.get("skills", [])
        if isinstance(skills_list, list):
            skills = {s["name"]: s["level"] for s in skills_list if isinstance(s, dict)}
        else:
            skills = skills_list if isinstance(skills_list, dict) else {}

        # Map traits list → [name, ...] list
        traits_list = work_info.get("traits", [])
        if isinstance(traits_list, list) and traits_list and isinstance(traits_list[0], dict):
            traits = [t["name"] for t in traits_list]
        else:
            traits = traits_list if isinstance(traits_list, list) else []

        # Map needs from root-level fields
        needs = {
            "food": pawn.get("hunger", raw.get("hunger", 0.5)),
            "rest": raw.get("sleep", 0.5),
            "joy": raw.get("joy", 0.5),
            "comfort": raw.get("comfort", 0.5),
        }

        # Hediffs as injuries
        hediffs = medical.get("hediffs", [])
        injuries = [h.get("label", str(h)) for h in hediffs] if hediffs else []

        return {
            "colonist_id": str(pawn.get("id", "")),
            "name": pawn.get("name", "Unknown"),
            "health": pawn.get("health", 1.0),
            "mood": pawn.get("mood", 0.5),
            "skills": skills,
            "traits": traits,
            "current_job": work_info.get("current_job") or None,
            "is_drafted": pawn.get("is_drafted", False),
            "needs": needs,
            "injuries": injuries,
            "position": position,
        }

    @staticmethod
    def _adapt_colony(raw: dict) -> dict:
        """Map upstream GameStateDto → ColonyData fields.

        Handles both upstream (game_tick, colony_wealth, colonist_count)
        and mock/test format (name, wealth, day, tick, population).
        """
        if "name" in raw:
            return raw
        return {
            "name": "Colony",
            "wealth": raw.get("colony_wealth", 0.0),
            "day": raw.get("game_tick", 0) // 60000,
            "tick": raw.get("game_tick", 0),
            "population": raw.get("colonist_count", 0),
            "mood_average": 0.5,
            "food_days": 5.0,
        }

    @staticmethod
    def _adapt_research(raw: dict) -> dict:
        """Map upstream ResearchSummaryDto → ResearchData fields."""
        if "current_project" in raw:
            return raw
        completed = []
        available = []
        for _level, cat in raw.get("by_tech_level", {}).items():
            for proj in cat.get("projects", []):
                if cat.get("finished", 0) > 0:
                    completed.append(proj)
                else:
                    available.append(proj)
        return {
            "current_project": None,
            "progress": 0.0,
            "completed": completed[:raw.get("finished_projects_count", 0)],
            "available": available,
        }

    # ------------------------------------------------------------------
    # Read endpoints
    # ------------------------------------------------------------------

    async def get_colonists(self) -> list[ColonistData]:
        try:
            data = await self._get("/api/v1/colonists/detailed")
        except (RimAPIResponseError, RimAPIConnectionError):
            # Fall back to basic endpoint if detailed isn't available
            data = await self._get("/api/v1/colonists")
        return [ColonistData.model_validate(self._adapt_colonist(c)) for c in data]

    async def get_colonist(self, colonist_id: str) -> ColonistData:
        data = await self._get(f"/api/v1/colonist?id={colonist_id}")
        return ColonistData.model_validate(self._adapt_colonist(data))

    async def get_resources(self) -> ResourceData:
        try:
            data = await self._get("/api/v1/resources/summary?map_id=0")
            crit = data.get("critical_resources", {})
            food_summary = crit.get("food_summary", {})
            return ResourceData(
                food=float(food_summary.get("food_total", 0)),
                medicine=int(crit.get("medicine_total", 0)),
                steel=0,  # Not exposed by RIMAPI
                wood=0,   # Not exposed by RIMAPI
                components=0,  # Not exposed by RIMAPI
                silver=round(data.get("total_market_value", 0.0)),
                power_net=0.0,  # Not exposed by RIMAPI
                items={"total": data.get("total_items", 0)},
            )
        except (RimAPIResponseError, RimAPIConnectionError):
            return ResourceData(
                food=50.0, medicine=5, steel=100, wood=200,
                components=10, silver=300, power_net=0.0,
            )

    async def get_map(self) -> MapData:
        try:
            buildings = await self._get("/api/v1/map/buildings?map_id=0")
        except (RimAPIResponseError, RimAPIConnectionError):
            buildings = []
        try:
            weather = await self._get("/api/v1/map/weather?map_id=0")
            temperature = weather.get("temperature", 15.0)
        except (RimAPIResponseError, RimAPIConnectionError):
            temperature = 15.0
        structures = []
        for b in buildings[:50]:
            pos = b.get("position", [0, 0])
            if isinstance(pos, dict):
                pos = (pos.get("x", 0), pos.get("z", 0))
            elif isinstance(pos, list) and len(pos) >= 2:
                pos = (pos[0], pos[1])
            else:
                pos = (0, 0)
            structures.append(StructureData(
                structure_id=str(b.get("id", b.get("thing_id", ""))),
                def_name=b.get("def_name", b.get("label", "Unknown")),
                position=pos,
                hit_points=float(b.get("hit_points", 100)),
                max_hit_points=float(b.get("max_hit_points", 100)),
            ))
        zones = await self.get_zones()
        rooms = await self.get_rooms()
        ore_deposits = await self.get_ore()
        farm_summary = await self.get_farm_summary()
        return MapData(
            size=(250, 250),
            biome="temperate_forest",
            season="spring",
            temperature=temperature,
            structures=structures,
            zones=zones,
            rooms=rooms,
            ore_deposits=ore_deposits,
            farm_summary=farm_summary,
        )

    async def get_zones(self, map_id: int = 0) -> list[ZoneData]:
        """Fetch all zones (growing, stockpile, dumping) from the map.

        RIMAPI returns: {zones: [...], areas: [...]}
        Zones are player-created (growing, stockpile). Areas are system (Home, NoRoof).
        We return both merged, with type distinguishing them.
        """
        try:
            data = await self._get(f"/api/v1/map/zones?map_id={map_id}")
            if not isinstance(data, dict):
                return []
            result: list[ZoneData] = []
            for z in data.get("zones", []):
                result.append(ZoneData(
                    zone_id=str(z.get("id", "")),
                    zone_type=z.get("zone_type", z.get("type", "unknown")),
                    label=z.get("label", ""),
                    cell_count=int(z.get("cells_count", z.get("cell_count", 0))),
                    plant_def=z.get("plant_def"),
                ))
            for a in data.get("areas", []):
                cells = int(a.get("cells_count", 0))
                if cells == 0:
                    continue  # Skip empty system areas
                result.append(ZoneData(
                    zone_id=str(a.get("id", "")),
                    zone_type=a.get("type", "area"),
                    label=a.get("label", ""),
                    cell_count=cells,
                ))
            return result
        except (RimAPIResponseError, RimAPIConnectionError):
            return []

    async def get_rooms(self, map_id: int = 0) -> list[RoomData]:
        """Fetch all rooms detected on the map.

        RIMAPI returns: {rooms: [{id, role_label, temperature, cells_count,
        touches_map_edge, is_prison_cell, is_doorway, open_roof_count,
        contained_beds_ids}, ...]}
        Skip the outdoor "room" (touches_map_edge=true) and doorways.
        """
        try:
            data = await self._get(f"/api/v1/map/rooms?map_id={map_id}")
            rooms_list = data.get("rooms", []) if isinstance(data, dict) else data
            result: list[RoomData] = []
            for r in rooms_list:
                if r.get("touches_map_edge") or r.get("is_doorway"):
                    continue  # Skip outdoor and doorway "rooms"
                beds = r.get("contained_beds_ids", [])
                result.append(RoomData(
                    room_id=str(r.get("id", "")),
                    role=r.get("role_label", r.get("role", "none")),
                    size=int(r.get("cells_count", r.get("cell_count", 0))),
                    temperature=float(r.get("temperature", 15.0)),
                    impressiveness=float(r.get("impressiveness", 0.0)),
                    bed_count=len(beds) if isinstance(beds, list) else int(beds),
                ))
            return result
        except (RimAPIResponseError, RimAPIConnectionError):
            return []

    async def get_ore(self, map_id: int = 0) -> list[OreDeposit]:
        """Fetch ore deposit data from the map.

        RIMAPI returns: {ores: {name: {max_hp, cells: [flat_index, ...]}}}
        where flat_index = x + z * map_width.
        """
        try:
            data = await self._get(f"/api/v1/map/ore?map_id={map_id}")
            ores_dict = data.get("ores", {}) if isinstance(data, dict) else {}
            map_width = int(data.get("map_width", 250)) if isinstance(data, dict) else 250
            result: list[OreDeposit] = []
            for ore_name, ore_data in ores_dict.items():
                if not isinstance(ore_data, dict):
                    continue
                cells = ore_data.get("cells", [])
                # Convert flat indices to (x, z) — sample first 10
                positions: list[tuple[int, int]] = []
                for cell in cells[:10]:
                    if isinstance(cell, int):
                        positions.append((cell % map_width, cell // map_width))
                result.append(OreDeposit(
                    def_name=ore_name,
                    count=len(cells),
                    positions=positions,
                ))
            return result
        except (RimAPIResponseError, RimAPIConnectionError):
            return []

    async def get_farm_summary(self, map_id: int = 0) -> FarmSummary | None:
        """Fetch farming production summary from the map.

        RIMAPI returns: {total_growing_zones, total_plants, total_expected_yield,
        total_infected_plants, growth_progress_average, crop_types: [...]}
        """
        try:
            data = await self._get(f"/api/v1/map/farm/summary?map_id={map_id}")
            if not isinstance(data, dict):
                return None
            # crop_types may be a list of dicts or strings
            crops: dict[str, int] = {}
            for crop in data.get("crop_types", []):
                if isinstance(crop, dict):
                    name = crop.get("def_name", crop.get("label", "unknown"))
                    crops[name] = int(crop.get("count", crop.get("total", 1)))
                elif isinstance(crop, str):
                    crops[crop] = crops.get(crop, 0) + 1
            return FarmSummary(
                total_growing_zones=int(data.get("total_growing_zones", 0)),
                planted_cells=int(data.get("total_plants", data.get("planted_cells", 0))),
                harvestable_cells=int(
                    data.get("total_expected_yield", data.get("harvestable_cells", 0)),
                ),
                crops=crops,
            )
        except (RimAPIResponseError, RimAPIConnectionError):
            return None

    async def get_terrain_summary(
        self,
        colonist_positions: list[tuple[int, int]] | None = None,
        map_id: int = 0,
    ) -> TerrainSummary | None:
        """Fetch terrain and compute a deterministic spatial summary.

        Decodes the RLE terrain grid, classifies tiles, and finds the best
        areas for building, farming, and stockpiling near the colony center.
        """
        try:
            data = await self._get(f"/api/v1/map/terrain?map_id={map_id}")
            if not isinstance(data, dict):
                return None
            width = int(data.get("width", 250))
            height = int(data.get("height", 250))
            palette: list[str] = data.get("palette", [])
            rle_grid: list[int] = data.get("grid", [])

            # Classify palette indices
            water_indices: set[int] = set()
            fertile_indices: set[int] = set()
            rock_indices: set[int] = set()
            for i, name in enumerate(palette):
                low = name.lower()
                if "water" in low or "marsh" in low:
                    water_indices.add(i)
                elif "rich" in low or low == "soil":
                    fertile_indices.add(i)
                elif "rough" in low:
                    rock_indices.add(i)

            # Decode RLE into a 2D classification grid
            # 0=other, 1=water, 2=fertile, 3=rock
            flat: list[int] = []
            for i in range(0, len(rle_grid) - 1, 2):
                count = rle_grid[i]
                idx = rle_grid[i + 1]
                if idx in water_indices:
                    flat.extend([1] * count)
                elif idx in fertile_indices:
                    flat.extend([2] * count)
                elif idx in rock_indices:
                    flat.extend([3] * count)
                else:
                    flat.extend([0] * count)

            # Compute colony center from colonist positions
            if colonist_positions and len(colonist_positions) > 0:
                cx = sum(p[0] for p in colonist_positions) // len(colonist_positions)
                cz = sum(p[1] for p in colonist_positions) // len(colonist_positions)
            else:
                cx, cz = width // 2, height // 2

            def _cell(x: int, z: int) -> int:
                if 0 <= x < width and 0 <= z < height:
                    idx = x + z * width
                    return flat[idx] if idx < len(flat) else 0
                return 1  # Out of bounds = water (unbuildable)

            def _is_buildable(x: int, z: int) -> bool:
                return _cell(x, z) in (0, 2)  # Not water, not rock

            def _is_fertile(x: int, z: int) -> bool:
                return _cell(x, z) == 2

            # Find best rectangular areas near colony center using expanding search
            def _find_clear_rect(
                center_x: int, center_z: int, min_size: int, check_fn: callable,
            ) -> AreaRect | None:
                """Search outward from center for a clear rectangle."""
                for radius in range(0, 60, 3):
                    for dx in range(-radius, radius + 1, 3):
                        for dz in range(-radius, radius + 1, 3):
                            x1 = center_x + dx
                            z1 = center_z + dz
                            x2 = x1 + min_size - 1
                            z2 = z1 + min_size - 1
                            if x2 >= width or z2 >= height or x1 < 0 or z1 < 0:
                                continue
                            if all(
                                check_fn(x, z)
                                for x in range(x1, x2 + 1)
                                for z in range(z1, z2 + 1)
                            ):
                                return AreaRect(x1=x1, z1=z1, x2=x2, z2=z2)
                return None

            # Find water areas near center (for avoidance)
            water_areas: list[AreaRect] = []
            scan_range = 40
            water_x_min = water_x_max = water_z_min = water_z_max = None
            for dz in range(-scan_range, scan_range + 1):
                for dx in range(-scan_range, scan_range + 1):
                    x, z = cx + dx, cz + dz
                    if _cell(x, z) == 1:
                        if water_x_min is None:
                            water_x_min = water_x_max = x
                            water_z_min = water_z_max = z
                        else:
                            water_x_min = min(water_x_min, x)
                            water_x_max = max(water_x_max, x)
                            water_z_min = min(water_z_min, z)
                            water_z_max = max(water_z_max, z)
            if water_x_min is not None:
                water_areas.append(AreaRect(
                    x1=water_x_min, z1=water_z_min,
                    x2=water_x_max, z2=water_z_max,
                    label="water",
                ))

            # Find recommended areas
            shelter = _find_clear_rect(cx, cz, 7, _is_buildable)
            farm = _find_clear_rect(cx, cz, 8, _is_fertile)
            # Stockpile: buildable 5x5 near center
            stockpile = _find_clear_rect(cx, cz, 5, _is_buildable)

            return TerrainSummary(
                colony_center=(cx, cz),
                water_areas=water_areas,
                recommended_shelter=shelter,
                recommended_farm=farm,
                recommended_stockpile=stockpile,
            )
        except (RimAPIResponseError, RimAPIConnectionError):
            return None

    async def get_research(self) -> ResearchData:
        data = await self._get("/api/v1/research/summary")
        return ResearchData.model_validate(self._adapt_research(data))

    async def get_threats(self) -> list[ThreatData]:
        try:
            data = await self._get("/api/v1/incidents?map_id=0")
            incidents = data.get("incidents", []) if isinstance(data, dict) else data
            return [
                ThreatData(
                    threat_id=str(inc.get("id", inc.get("def_name", i))),
                    threat_type=inc.get("def_name", "unknown"),
                    faction=inc.get("faction"),
                    enemy_count=inc.get("enemy_count", 0),
                    threat_level=inc.get("threat_level", inc.get("points", 0.0)),
                )
                for i, inc in enumerate(incidents)
            ]
        except (RimAPIResponseError, RimAPIConnectionError):
            return []

    async def get_colony(self) -> ColonyData:
        data = await self._get("/api/v1/game/state")
        return ColonyData.model_validate(self._adapt_colony(data))

    async def get_weather(self) -> WeatherData:
        try:
            data = await self._get("/api/v1/map/weather?map_id=0")
            return WeatherData(
                condition=data.get("weather", "Clear"),
                temperature=data.get("temperature", 15.0),
                outdoor_severity=0.0,
            )
        except (RimAPIResponseError, RimAPIConnectionError):
            return WeatherData(condition="Clear", temperature=15.0, outdoor_severity=0.0)

    async def get_game_state(self) -> GameState:
        """Fetch all endpoints and assemble a full GameState snapshot."""
        colony = await self.get_colony()
        colonists = await self.get_colonists()
        resources = await self.get_resources()
        map_data = await self.get_map()
        # Compute terrain summary using colonist positions for colony center
        col_positions = [(c.position[0], c.position[1]) for c in colonists]
        terrain = await self.get_terrain_summary(col_positions)
        if terrain is not None:
            map_data = MapData(
                size=map_data.size, biome=map_data.biome, season=map_data.season,
                temperature=map_data.temperature, structures=map_data.structures,
                zones=map_data.zones, rooms=map_data.rooms,
                ore_deposits=map_data.ore_deposits, farm_summary=map_data.farm_summary,
                terrain=terrain,
            )
        research = await self.get_research()
        threats = await self.get_threats()
        weather = await self.get_weather()

        # Compute dynamic colony metrics from real data
        if colonists:
            avg_mood = sum(c.mood for c in colonists) / len(colonists)
            colony = ColonyData(
                name=colony.name, wealth=colony.wealth, day=colony.day,
                tick=colony.tick, population=colony.population,
                mood_average=round(avg_mood, 3),
                food_days=round(resources.food / max(len(colonists) * 2, 1), 1),
            )

        return GameState(
            colony=colony,
            colonists=colonists,
            resources=resources,
            map=map_data,
            research=research,
            threats=threats,
            weather=weather,
            timestamp=time.time(),
        )

    async def unforbid_all_items(self, map_id: int = 0) -> int:
        """Unforbid all forbidden items on the map. Returns count unforbidden."""
        try:
            data = await self._get(f"/api/v1/map/things?map_id={map_id}")
            things = data if isinstance(data, list) else []
            forbidden_ids = [
                t["thing_id"] for t in things
                if t.get("is_forbidden", False)
            ]
            if not forbidden_ids:
                return 0
            await self._post(
                "/api/v1/things/set-forbidden",
                json={"thing_ids": forbidden_ids, "map_id": map_id, "forbidden": False},
            )
            return len(forbidden_ids)
        except (RimAPIResponseError, RimAPIConnectionError):
            return 0

    # ------------------------------------------------------------------
    # Write endpoints — upstream RIMAPI v1.8.2+
    # ------------------------------------------------------------------

    @staticmethod
    def _int_id(colonist_id: str) -> int:
        """Convert string colonist ID to int for RIMAPI DTOs."""
        try:
            return int(colonist_id)
        except (ValueError, TypeError):
            return 0

    async def save_game(self, name: str) -> dict:
        """Save the current game state for benchmark reproducibility."""
        return await self._post("/api/v1/game/save", json={"file_name": name})

    async def load_game(
        self, name: str, check_version: bool = False, skip_mod_mismatch: bool = True,
    ) -> dict:
        """Load a previously saved game state."""
        return await self._post("/api/v1/game/load", json={
            "file_name": name,
            "check_version": check_version,
            "skip_mod_mismatch": skip_mod_mismatch,
        })

    async def pause_game(self) -> dict:
        return await self._post("/api/v1/game/speed?speed=0")

    async def unpause_game(self, speed: int = 3) -> dict:
        """Unpause at given speed (1=normal, 2=fast, 3=very fast)."""
        return await self._post(f"/api/v1/game/speed?speed={speed}")

    async def draft_colonist(self, colonist_id: str, draft: bool) -> dict:
        return await self._post(
            "/api/v1/pawn/edit/status",
            json={"pawn_id": self._int_id(colonist_id), "is_drafted": draft},
        )

    async def set_work_priorities(
        self, colonist_id: str, priorities: dict[str, int],
    ) -> dict:
        """Set work priorities one at a time via the singular endpoint.

        The bulk endpoint (/api/v1/colonists/work-priority) has a
        deserialization bug where Priorities list is always null.
        Use the singular endpoint which has explicit [JsonProperty] attrs.
        """
        pid = self._int_id(colonist_id)
        last_result: dict = {}
        for work, pri in priorities.items():
            last_result = await self._post(
                "/api/v1/colonist/work-priority",
                json={"id": pid, "work": work, "priority": pri},
            )
        return last_result

    async def place_blueprint(self, blueprint: dict) -> dict:
        """Place a blueprint using the full PasteAreaRequestDto format.

        The blueprint dict must contain: map_id, position, blueprint (with
        width, height, and buildings list). Use place_building() for simple
        single-building placement.
        """
        return await self._post("/api/v1/builder/blueprint", json=blueprint)

    async def place_building(
        self,
        def_name: str,
        x: int,
        z: int,
        *,
        stuff_def: str = "WoodLog",
        rotation: int = 0,
        map_id: int = 0,
    ) -> dict:
        """Place a single building blueprint at (x, z).

        Wraps the PasteAreaRequestDto with a 1x1 blueprint grid.
        """
        return await self.place_blueprint({
            "map_id": map_id,
            "position": {"x": x, "y": 0, "z": z},
            "blueprint": {
                "width": 1,
                "height": 1,
                "floors": [],
                "buildings": [
                    {
                        "def_name": def_name,
                        "stuff_def_name": stuff_def,
                        "rel_x": 0,
                        "rel_z": 0,
                        "rotation": rotation,
                    },
                ],
            },
            "clear_obstacles": True,
        })

    async def move_colonist(self, colonist_id: str, x: int, z: int) -> dict:
        return await self._post(
            "/api/v1/pawn/edit/position",
            json={
                "pawn_id": self._int_id(colonist_id),
                "position": {"x": x, "y": 0, "z": z},
            },
        )

    async def set_time_assignment(
        self, colonist_id: str, hour: int, assignment: str,
    ) -> dict:
        return await self._post(
            "/api/v1/colonist/time-assignment",
            json={"pawn_id": self._int_id(colonist_id), "hour": hour, "assignment": assignment},
        )

    async def designate_area(
        self,
        map_id: int,
        designation_type: str,
        x1: int,
        z1: int,
        x2: int,
        z2: int,
    ) -> dict:
        return await self._post(
            "/api/v1/order/designate/area",
            json={
                "map_id": map_id,
                "type": designation_type,
                "point_a": {"x": x1, "y": 0, "z": z1},
                "point_b": {"x": x2, "y": 0, "z": z2},
            },
        )

    # ------------------------------------------------------------------
    # Write endpoints — RLE fork (AppSprout-dev/RIMAPI:rle-testing)
    # ------------------------------------------------------------------

    async def set_research_target(self, project: str, force: bool = False) -> dict:
        if not project:
            return {"success": False, "skipped": "empty project name"}
        url = f"/api/v1/research/target?name={project}"
        if force:
            url += "&force=true"
        return await self._post(url)

    async def stop_research(self) -> dict:
        return await self._post("/api/v1/research/stop")

    async def get_endpoints(self) -> list[dict]:
        """Discover all registered API routes from RIMAPI."""
        try:
            return await self._get("/api/v1/dev/endpoints")
        except (RimAPIResponseError, RimAPIConnectionError):
            return []

    async def set_colonist_job(
        self,
        colonist_id: str,
        job: str,
        target_thing_id: int | None = None,
        target_position: tuple[int, int] | None = None,
    ) -> dict:
        body: dict = {"pawn_id": self._int_id(colonist_id), "job_def": job}
        if target_thing_id is not None:
            body["target_thing_id"] = target_thing_id
        if target_position is not None:
            body["target_position"] = {"x": target_position[0], "y": 0, "z": target_position[1]}
        return await self._post("/api/v1/pawn/job", json=body)

    async def toggle_power(self, building_id: int, power_on: bool) -> dict:
        return await self._post(
            f"/api/v1/map/building/power?buildingId={building_id}"
            f"&powerOn={str(power_on).lower()}",
        )

    @staticmethod
    def _normalize_plant_def(plant_def: str) -> str:
        """Normalize agent plant names to RimWorld defNames."""
        if plant_def.startswith("Plant_"):
            return plant_def
        # "PlantPotato" → "Plant_Potato", "potato" → "Plant_Potato"
        name = plant_def.removeprefix("Plant").strip("_")
        if not name:
            name = "Potato"
        return f"Plant_{name[0].upper()}{name[1:]}"

    async def create_growing_zone(
        self,
        map_id: int,
        plant_def: str,
        x1: int,
        z1: int,
        x2: int,
        z2: int,
    ) -> dict:
        return await self._post(
            "/api/v1/map/zone/growing",
            json={
                "map_id": map_id,
                "plant_def": self._normalize_plant_def(plant_def),
                "point_a": {"x": x1, "y": 0, "z": z1},
                "point_b": {"x": x2, "y": 0, "z": z2},
            },
        )

    async def create_stockpile_zone(
        self,
        map_id: int,
        x1: int,
        z1: int,
        x2: int,
        z2: int,
        name: str = "",
        priority: int = 3,
        allowed_item_defs: list[str] | None = None,
        allowed_item_categories: list[str] | None = None,
    ) -> dict:
        """Create a stockpile zone with optional item filtering."""
        body: dict = {
            "map_id": map_id,
            "point_a": {"x": x1, "y": 0, "z": z1},
            "point_b": {"x": x2, "y": 0, "z": z2},
        }
        if name:
            body["name"] = name
        if priority != 3:
            body["priority"] = priority
        if allowed_item_defs:
            body["allowed_item_defs"] = allowed_item_defs
        if allowed_item_categories:
            body["allowed_item_categories"] = allowed_item_categories
        return await self._post("/api/v1/map/zone/stockpile", json=body)

    async def assign_bed_rest(
        self, patient_id: str, bed_building_id: int | None = None,
    ) -> dict:
        body: dict = {"patient_pawn_id": self._int_id(patient_id)}
        if bed_building_id is not None:
            body["bed_building_id"] = bed_building_id
        return await self._post("/api/v1/pawn/medical/bed-rest", json=body)

    async def administer_medicine(
        self, patient_id: str, doctor_id: str | None = None,
    ) -> dict:
        body: dict = {"patient_pawn_id": self._int_id(patient_id)}
        if doctor_id is not None:
            body["doctor_pawn_id"] = self._int_id(doctor_id)
        return await self._post("/api/v1/pawn/medical/tend", json=body)
