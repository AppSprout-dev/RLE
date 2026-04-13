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
    AlertData,
    ColonistData,
    ColonyData,
    FactionData,
    GameState,
    MapData,
    PowerData,
    ResearchData,
    ResourceData,
    ScreenshotResponse,
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
    "/api/v1/jobs/make/equip": {"success": True},
    "/api/v1/map/repair/rect": {"success": True},
    "/api/v1/map/destroy/rect": {"success": True},
    "/api/v1/incident/trigger": {"success": True},
    "/api/v1/pawn/spawn": {"success": True, "data": {"pawn_id": 999, "name": "Val"}},
    "/api/v1/item/spawn": {"success": True},
    "/api/v1/map/droppod": {"success": True},
    "/api/v1/map/weather/change?name=Rain&map_id=0": {"success": True},
    "/api/v1/camera/screenshot": {
        "data": {
            "image": {"data_uri": "data:image/jpeg;base64,/9j/4AAQ..."},
            "metadata": {
                "format": "jpeg", "width": 1920,
                "height": 1080, "size_bytes": 245000,
            },
            "game_context": {"current_tick": 60000},
        },
    },
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
        "/api/v1/resources/stored?map_id=0": {
            "Resources": [
                {"def_name": "WoodLog", "stack_count": 342},
                {"def_name": "WoodLog", "stack_count": 108},
                {"def_name": "Steel", "stack_count": 189},
                {"def_name": "ComponentIndustrial", "stack_count": 12},
                {"def_name": "Silver", "stack_count": 500},
            ],
        },
        "/api/v1/map/power/info?map_id=0": {
            "current_power": 1800.0,
            "total_consumption": 1200.0,
            "currently_stored_power": 400.0,
            "total_power_storage": 1000.0,
        },
        "/api/v1/factions": [
            {
                "name": "Pirate Band", "def_name": "Pirate",
                "goodwill": -100, "relation": "hostile", "is_player": False,
            },
            {
                "name": "New Hope", "def_name": "PlayerColony",
                "goodwill": 0, "relation": "self", "is_player": True,
            },
            {
                "name": "Tribe of Elk", "def_name": "TribeCivil",
                "goodwill": 45, "relation": "neutral", "is_player": False,
            },
        ],
        "/api/v1/ui/alerts?map_id=0": [
            {
                "label": "Starvation",
                "explanation": "A colonist is starving",
                "priority": "Critical",
                "targets": [184],
                "cells": [],
            },
            {
                "label": "Need Beds",
                "explanation": "Colonists need beds",
                "priority": "High",
                "targets": [],
                "cells": ["(120,125)"],
            },
        ],
        "/api/v1/incidents/top?map_id=0": [
            {
                "def_name": "RaidEnemy",
                "label": "Raid",
                "category": "ThreatBig",
                "current_weight": 42.5,
            },
        ],
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
        # Phase 1: real material counts from /resources/stored
        assert result.wood == 450  # 342 + 108
        assert result.steel == 189
        assert result.components == 12

    async def test_get_resources_stored(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_resources_stored()
        assert result["WoodLog"] == 450
        assert result["Steel"] == 189
        assert result["ComponentIndustrial"] == 12
        assert result["Silver"] == 500

    async def test_get_power_info(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_power_info()
        assert result is not None
        assert isinstance(result, PowerData)
        assert result.current_power == 1800.0
        assert result.total_consumption == 1200.0
        assert result.stored_power == 400.0
        assert result.storage_capacity == 1000.0

    async def test_get_resources_includes_power_net(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_resources()
        assert result.power_net == 600.0  # 1800 current - 1200 consumption

    async def test_get_factions(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_factions()
        assert len(result) == 2  # Player faction filtered out
        assert isinstance(result[0], FactionData)
        assert result[0].name == "Pirate Band"
        assert result[0].goodwill == -100
        assert result[0].relation == "hostile"
        assert result[1].name == "Tribe of Elk"
        assert result[1].goodwill == 45

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
        # Phase 1: power and factions included in game state
        assert result.power is not None
        assert result.power.current_power == 1800.0
        assert len(result.factions) == 2
        assert result.factions[0].name == "Pirate Band"


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

    async def test_equip_item(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.equip_item("12345", 999)
        assert result["success"] is True

    async def test_repair_rect(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.repair_rect(0, 10, 10, 20, 20)
        assert result["success"] is True

    async def test_destroy_rect(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.destroy_rect(0, 10, 10, 20, 20)
        assert result["success"] is True

    async def test_trigger_incident(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.trigger_incident(
            "RaidEnemy", map_id=0, points=500,
        )
        assert result["success"] is True

    async def test_take_screenshot(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.take_screenshot()
        assert result is not None
        assert isinstance(result, ScreenshotResponse)
        assert result.width == 1920
        assert result.height == 1080
        assert result.size_bytes == 245000
        assert result.game_tick == 60000
        assert result.data_uri.startswith("data:image/jpeg")


class TestPhase2ReadEndpoints:
    async def test_get_alerts(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.get_alerts()
        assert len(result) == 2
        assert isinstance(result[0], AlertData)
        assert result[0].label == "Starvation"
        assert result[0].priority == "Critical"
        assert result[0].target_ids == [184]
        assert result[1].label == "Need Beds"
        assert result[1].cells == ["(120,125)"]

    async def test_alerts_in_game_state(
        self, mock_client: RimAPIClient,
    ) -> None:
        state = await mock_client.get_game_state()
        assert len(state.alerts) == 2
        assert state.alerts[0].label == "Starvation"

    async def test_get_upcoming_incidents(
        self, mock_client: RimAPIClient,
    ) -> None:
        result = await mock_client.get_upcoming_incidents()
        assert len(result) == 1
        assert result[0]["def_name"] == "RaidEnemy"


class TestSpawnEndpoints:
    async def test_spawn_pawn(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.spawn_pawn(
            first_name="Val", last_name="Kowalski", x=130, z=140,
        )
        assert result["success"] is True

    async def test_spawn_item(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.spawn_item(
            "Steel", x=120, z=130, amount=200,
        )
        assert result["success"] is True

    async def test_spawn_item_with_quality(
        self, mock_client: RimAPIClient,
    ) -> None:
        result = await mock_client.spawn_item(
            "Gun_BoltActionRifle", x=120, z=130,
            stuff_def_name="Steel", quality="Good",
        )
        assert result["success"] is True

    async def test_send_drop_pod(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.send_drop_pod(
            x=125, z=135,
            items=[{"def_name": "Steel", "count": 100}],
        )
        assert result["success"] is True

    async def test_change_weather(self, mock_client: RimAPIClient) -> None:
        result = await mock_client.change_weather("Rain")
        assert result["success"] is True
