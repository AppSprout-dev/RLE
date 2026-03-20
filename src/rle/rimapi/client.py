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
    # ------------------------------------------------------------------

    async def get_colonists(self) -> list[ColonistData]:
        data = await self._get("/api/colonists")
        return [ColonistData.model_validate(c) for c in data]

    async def get_colonist(self, colonist_id: str) -> ColonistData:
        data = await self._get(f"/api/colonists/{colonist_id}")
        return ColonistData.model_validate(data)

    async def get_resources(self) -> ResourceData:
        data = await self._get("/api/resources")
        return ResourceData.model_validate(data)

    async def get_map(self) -> MapData:
        data = await self._get("/api/map")
        return MapData.model_validate(data)

    async def get_research(self) -> ResearchData:
        data = await self._get("/api/research")
        return ResearchData.model_validate(data)

    async def get_threats(self) -> list[ThreatData]:
        data = await self._get("/api/threats")
        return [ThreatData.model_validate(t) for t in data]

    async def get_colony(self) -> ColonyData:
        data = await self._get("/api/colony")
        return ColonyData.model_validate(data)

    async def get_weather(self) -> WeatherData:
        data = await self._get("/api/weather")
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
    # Write endpoints (stubs — require RIMAPI fork with write support)
    # ------------------------------------------------------------------

    async def set_colonist_job(self, colonist_id: str, job: str) -> dict:
        raise NotImplementedError("Write endpoints require RIMAPI fork")

    async def draft_colonist(self, colonist_id: str, draft: bool) -> dict:
        raise NotImplementedError("Write endpoints require RIMAPI fork")

    async def set_work_priorities(
        self, colonist_id: str, priorities: dict[str, int]
    ) -> dict:
        raise NotImplementedError("Write endpoints require RIMAPI fork")

    async def place_blueprint(self, blueprint: dict) -> dict:
        raise NotImplementedError("Write endpoints require RIMAPI fork")

    async def set_research_target(self, project: str) -> dict:
        raise NotImplementedError("Write endpoints require RIMAPI fork")

    async def pause_game(self) -> dict:
        raise NotImplementedError("Write endpoints require RIMAPI fork")

    async def unpause_game(self) -> dict:
        raise NotImplementedError("Write endpoints require RIMAPI fork")
