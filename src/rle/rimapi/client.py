"""Async HTTP client for the RIMAPI RimWorld mod."""

from __future__ import annotations

import time
from types import TracebackType

import httpx

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
        return MapData(
            size=(250, 250),
            biome="temperate_forest",
            season="spring",
            temperature=temperature,
            structures=structures,
        )

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
        return await self._post(f"/api/v1/game/save?name={name}")

    async def load_game(self, name: str) -> dict:
        """Load a previously saved game state."""
        return await self._post(f"/api/v1/game/load?name={name}")

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
        return await self._post("/api/v1/builder/blueprint", json=blueprint)

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

    async def set_research_target(self, project: str) -> dict:
        if not project:
            return {"success": False, "skipped": "empty project name"}
        return await self._post(f"/api/v1/research/target?name={project}")

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
