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
        """Perform a GET request and return parsed JSON."""
        try:
            resp = await self.client.get(path)
        except httpx.ConnectError as exc:
            raise RimAPIConnectionError(
                f"Cannot connect to RIMAPI at {self._base_url}"
            ) from exc

        if resp.status_code != 200:
            raise RimAPIResponseError(resp.status_code, resp.text)
        return resp.json()

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

    async def get_colonists(self) -> list[ColonistData]:
        data = await self._get("/api/v1/colonists")
        return [ColonistData.model_validate(c) for c in data]

    async def get_colonist(self, colonist_id: str) -> ColonistData:
        data = await self._get(f"/api/v1/colonist?id={colonist_id}")
        return ColonistData.model_validate(data)

    async def get_resources(self) -> ResourceData:
        data = await self._get("/api/v1/resources")
        return ResourceData.model_validate(data)

    async def get_map(self) -> MapData:
        data = await self._get("/api/v1/map")
        return MapData.model_validate(data)

    async def get_research(self) -> ResearchData:
        data = await self._get("/api/v1/research/summary")
        return ResearchData.model_validate(data)

    async def get_threats(self) -> list[ThreatData]:
        data = await self._get("/api/v1/threats")
        return [ThreatData.model_validate(t) for t in data]

    async def get_colony(self) -> ColonyData:
        data = await self._get("/api/v1/game/state")
        return ColonyData.model_validate(data)

    async def get_weather(self) -> WeatherData:
        data = await self._get("/api/v1/map/weather")
        return WeatherData.model_validate(data)

    async def get_game_state(self) -> GameState:
        """Fetch all endpoints and assemble a full GameState snapshot."""
        colony = await self.get_colony()
        colonists = await self.get_colonists()
        resources = await self.get_resources()
        map_data = await self.get_map()
        research = await self.get_research()
        threats = await self.get_threats()
        weather = await self.get_weather()
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

    async def pause_game(self) -> dict:
        return await self._post("/api/v1/game/speed?speed=0")

    async def unpause_game(self) -> dict:
        return await self._post("/api/v1/game/speed?speed=1")

    async def draft_colonist(self, colonist_id: str, draft: bool) -> dict:
        return await self._post(
            "/api/v1/pawn/edit/status",
            json={"PawnId": colonist_id, "IsDrafted": draft},
        )

    async def set_work_priorities(
        self, colonist_id: str, priorities: dict[str, int],
    ) -> dict:
        entries = [
            {"id": colonist_id, "work": work, "priority": pri}
            for work, pri in priorities.items()
        ]
        return await self._post(
            "/api/v1/colonists/work-priority",
            json={"Priorities": entries},
        )

    async def place_blueprint(self, blueprint: dict) -> dict:
        return await self._post("/api/v1/builder/blueprint", json=blueprint)

    async def move_colonist(self, colonist_id: str, x: int, z: int) -> dict:
        return await self._post(
            "/api/v1/pawn/edit/position",
            json={
                "PawnId": colonist_id,
                "Position": {"X": x, "Y": 0, "Z": z},
            },
        )

    async def set_time_assignment(
        self, colonist_id: str, hour: int, assignment: str,
    ) -> dict:
        return await self._post(
            "/api/v1/colonist/time-assignment",
            json={"PawnId": colonist_id, "Hour": hour, "Assignment": assignment},
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
                "MapId": map_id,
                "Type": designation_type,
                "PointA": {"X": x1, "Y": 0, "Z": z1},
                "PointB": {"X": x2, "Y": 0, "Z": z2},
            },
        )

    # ------------------------------------------------------------------
    # Write endpoints — RLE fork (AppSprout-dev/RIMAPI:rle-testing)
    # ------------------------------------------------------------------

    async def set_research_target(self, project: str) -> dict:
        return await self._post(f"/api/v1/research/target?name={project}")

    async def set_colonist_job(
        self,
        colonist_id: str,
        job: str,
        target_thing_id: int | None = None,
        target_position: tuple[int, int] | None = None,
    ) -> dict:
        body: dict = {"PawnId": colonist_id, "JobDef": job}
        if target_thing_id is not None:
            body["TargetThingId"] = target_thing_id
        if target_position is not None:
            body["TargetPosition"] = {"X": target_position[0], "Z": target_position[1]}
        return await self._post("/api/v1/pawn/job", json=body)

    async def toggle_power(self, building_id: int, power_on: bool) -> dict:
        return await self._post(
            f"/api/v1/map/building/power?buildingId={building_id}&powerOn={str(power_on).lower()}",
        )

    async def create_growing_zone(
        self, map_id: int, plant_def: str, cells: list[dict],
    ) -> dict:
        return await self._post(
            "/api/v1/map/zone/growing",
            json={"MapId": map_id, "PlantDef": plant_def, "Cells": cells},
        )

    async def assign_bed_rest(
        self, patient_id: str, bed_building_id: int | None = None,
    ) -> dict:
        body: dict = {"PatientPawnId": patient_id}
        if bed_building_id is not None:
            body["BedBuildingId"] = bed_building_id
        return await self._post("/api/v1/pawn/medical/bed-rest", json=body)

    async def administer_medicine(
        self, patient_id: str, doctor_id: str | None = None,
    ) -> dict:
        body: dict = {"PatientPawnId": patient_id}
        if doctor_id is not None:
            body["DoctorPawnId"] = doctor_id
        return await self._post("/api/v1/pawn/medical/tend", json=body)
