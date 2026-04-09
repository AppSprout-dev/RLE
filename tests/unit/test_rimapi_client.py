"""Tests for the RimAPIClient async HTTP client."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import httpx
import pytest

from rle.rimapi.client import (
    RimAPIClient,
    RimAPIConnectionError,
    RimAPIResponseError,
)
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

# ------------------------------------------------------------------
# Transport helpers
# ------------------------------------------------------------------

_WRITE_ROUTES: dict[str, dict] = {
    "/api/v1/game/speed?speed=0": {"success": True},
    "/api/v1/game/speed?speed=1": {"success": True},
    "/api/v1/game/speed?speed=3": {"success": True},
    "/api/v1/pawn/edit/status": {"success": True},
    "/api/v1/pawn/edit/position": {"success": True},
    "/api/v1/colonists/work-priority": {"success": True},
    "/api/v1/colonist/work-priority": {"success": True},
    "/api/v1/builder/blueprint": {"success": True},
    "/api/v1/colonist/time-assignment": {"success": True},
    "/api/v1/order/designate/area": {"success": True},
    "/api/v1/research/target?name=Electricity": {"success": True},
    "/api/v1/pawn/job": {"success": True},
    "/api/v1/map/building/power?buildingId=999&powerOn=false": {"success": True},
    "/api/v1/map/zone/growing": {"success": True},
    "/api/v1/pawn/medical/bed-rest": {"success": True},
    "/api/v1/pawn/medical/tend": {"success": True},
}


def _json_response(data: dict | list, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(data).encode(),
        headers={"content-type": "application/json"},
    )


def _make_transport(
    routes: dict[str, dict | list],
    write_routes: dict[str, dict | list] | None = None,
) -> httpx.MockTransport:
    """Create a mock transport that maps URL paths to JSON responses."""
    _write = write_routes or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        if request.method == "POST" and path in _write:
            return _json_response(_write[path])
        if path in routes:
            return _json_response(routes[path])
        return httpx.Response(status_code=404, content=b"Not found")

    return httpx.MockTransport(handler)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def colonist_payload(sample_colonist_dict: dict) -> dict:
    return sample_colonist_dict


@pytest.fixture
def all_routes(
    sample_colonist_dict: dict,
    sample_resources_dict: dict,
    sample_map_dict: dict,
    sample_research_dict: dict,
    sample_threat_dict: dict,
    sample_colony_dict: dict,
    sample_weather_dict: dict,
) -> dict[str, dict | list]:
    # Resource summary in upstream RIMAPI format
    resources_summary = {
        "total_items": 1644,
        "total_market_value": 9186.0,
        "critical_resources": {
            "food_summary": {"food_total": 120},
            "medicine_total": 8,
            "weapon_count": 5,
        },
    }
    return {
        "/api/v1/colonists": [sample_colonist_dict],
        "/api/v1/colonist?id=col_01": sample_colonist_dict,
        "/api/v1/resources/summary?map_id=0": resources_summary,
        "/api/v1/map/buildings?map_id=0": [],
        "/api/v1/research/summary": sample_research_dict,
        "/api/v1/incidents?map_id=0": {"incidents": [sample_threat_dict]},
        "/api/v1/game/state": sample_colony_dict,
        "/api/v1/map/weather?map_id=0": sample_weather_dict,
        "/api/v1/map/zones?map_id=0": [],
        "/api/v1/map/rooms?map_id=0": [],
        "/api/v1/map/ore?map_id=0": [],
        "/api/v1/map/farm/summary?map_id=0": {
            "total_growing_zones": 0, "planted_cells": 0,
            "harvestable_cells": 0, "crops": {},
        },
        "/api/v1/map/terrain?map_id=0": {
            "width": 10, "height": 10,
            "palette": ["Soil", "WaterMovingShallow", "SoilRich", "Granite_Rough"],
            "grid": [100, 0],
            "floor_palette": [], "floor_grid": [100, 0],
        },
    }


@pytest.fixture
async def mock_client(all_routes: dict) -> AsyncGenerator[RimAPIClient, None]:
    """RimAPIClient wired to mock transport with read + write routes."""
    transport = _make_transport(all_routes, _WRITE_ROUTES)
    async with RimAPIClient("http://test") as client:
        client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
        yield client


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestContextManager:
    async def test_enter_exit(self) -> None:
        client = RimAPIClient()
        async with client as c:
            assert c is client
            assert c._client is not None
        assert client._client is None

    async def test_client_property_raises_outside_context(self) -> None:
        c = RimAPIClient()
        with pytest.raises(RuntimeError, match="async context manager"):
            _ = c.client


class TestReadEndpoints:
    async def test_get_colonists(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_colonists()
        assert len(result) == 1
        assert isinstance(result[0], ColonistData)
        assert result[0].name == "Tynan"

    async def test_get_colonist(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_colonist("col_01")
        assert isinstance(result, ColonistData)
        assert result.colonist_id == "col_01"

    async def test_get_resources(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_resources()
        assert isinstance(result, ResourceData)
        assert result.food == 120.0
        assert result.medicine == 8
        assert result.silver == 9186

    async def test_get_map(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_map()
        assert isinstance(result, MapData)
        assert result.biome == "temperate_forest"

    async def test_get_research(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_research()
        assert isinstance(result, ResearchData)

    async def test_get_threats(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_threats()
        assert len(result) == 1
        assert isinstance(result[0], ThreatData)

    async def test_get_colony(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_colony()
        assert isinstance(result, ColonyData)
        assert result.name == "New Hope"

    async def test_get_weather(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_weather()
        assert isinstance(result, WeatherData)

    async def test_get_game_state(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_game_state()
        assert isinstance(result, GameState)
        assert result.colony.name == "New Hope"
        assert len(result.colonists) == 1
        assert result.timestamp > 0


class TestErrorHandling:
    async def test_404_raises_response_error(self) -> None:
        transport = _make_transport({})
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            with pytest.raises(RimAPIResponseError) as exc_info:
                await client.get_colony()
            assert exc_info.value.status_code == 404

    async def test_connection_error(self) -> None:
        def raise_connect(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = httpx.MockTransport(raise_connect)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            with pytest.raises(RimAPIConnectionError):
                await client.get_colonists()


class TestWriteEndpoints:
    async def test_pause_game(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.pause_game()
        assert result["success"] is True

    async def test_unpause_game(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.unpause_game()
        assert result["success"] is True

    async def test_draft_colonist(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.draft_colonist("12345", True)
        assert result["success"] is True

    async def test_set_work_priorities(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.set_work_priorities("12345", {"Growing": 1})
        assert result["success"] is True

    async def test_place_blueprint(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.place_blueprint({"MapId": 0})
        assert result["success"] is True

    async def test_move_colonist(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.move_colonist("12345", 10, 20)
        assert result["success"] is True

    async def test_set_time_assignment(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.set_time_assignment("12345", 18, "Joy")
        assert result["success"] is True

    async def test_designate_area(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.designate_area(0, "Mine", 10, 10, 20, 20)
        assert result["success"] is True


class TestForkEndpoints:
    async def test_set_research_target(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.set_research_target("Electricity")
        assert result["success"] is True

    async def test_set_colonist_job(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.set_colonist_job("12345", "Haul")
        assert result["success"] is True

    async def test_set_colonist_job_with_target(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.set_colonist_job(
            "12345", "Haul", target_thing_id=456,
        )
        assert result["success"] is True

    async def test_toggle_power(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.toggle_power(999, False)
        assert result["success"] is True

    async def test_create_growing_zone(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.create_growing_zone(
            0, "PlantPotato", x1=115, z1=130, x2=120, z2=135,
        )
        assert result["success"] is True

    async def test_assign_bed_rest(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.assign_bed_rest("12345")
        assert result["success"] is True

    async def test_administer_medicine(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.administer_medicine("12345")
        assert result["success"] is True
