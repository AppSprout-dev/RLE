"""Tests for the RimAPIClient async HTTP client."""

from __future__ import annotations

import json

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


def _json_response(data: dict | list, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(data).encode(),
        headers={"content-type": "application/json"},
    )


def _make_transport(routes: dict[str, dict | list]) -> httpx.MockTransport:
    """Create a mock transport that maps URL paths to JSON responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
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
    return {
        "/api/colonists": [sample_colonist_dict],
        "/api/colonists/col_01": sample_colonist_dict,
        "/api/resources": sample_resources_dict,
        "/api/map": sample_map_dict,
        "/api/research": sample_research_dict,
        "/api/threats": [sample_threat_dict],
        "/api/colony": sample_colony_dict,
        "/api/weather": sample_weather_dict,
    }


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
    async def test_get_colonists(
        self, all_routes: dict, sample_colonist_dict: dict,
    ) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_colonists()
        assert len(result) == 1
        assert isinstance(result[0], ColonistData)
        assert result[0].name == "Tynan"

    async def test_get_colonist(
        self, all_routes: dict, sample_colonist_dict: dict,
    ) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_colonist("col_01")
        assert isinstance(result, ColonistData)
        assert result.colonist_id == "col_01"

    async def test_get_resources(self, all_routes: dict) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_resources()
        assert isinstance(result, ResourceData)
        assert result.food == 120.5

    async def test_get_map(self, all_routes: dict) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_map()
        assert isinstance(result, MapData)
        assert result.biome == "temperate_forest"

    async def test_get_research(self, all_routes: dict) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_research()
        assert isinstance(result, ResearchData)

    async def test_get_threats(self, all_routes: dict) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_threats()
        assert len(result) == 1
        assert isinstance(result[0], ThreatData)

    async def test_get_colony(self, all_routes: dict) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_colony()
        assert isinstance(result, ColonyData)
        assert result.name == "New Hope"

    async def test_get_weather(self, all_routes: dict) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_weather()
        assert isinstance(result, WeatherData)

    async def test_get_game_state(self, all_routes: dict) -> None:
        transport = _make_transport(all_routes)
        async with RimAPIClient("http://test") as client:
            client._client = httpx.AsyncClient(transport=transport, base_url="http://test")
            result = await client.get_game_state()
        assert isinstance(result, GameState)
        assert result.colony.name == "New Hope"
        assert len(result.colonists) == 1
        assert result.timestamp > 0


class TestErrorHandling:
    async def test_404_raises_response_error(self) -> None:
        transport = _make_transport({})  # no routes → 404
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


class TestWriteEndpointStubs:
    async def test_write_endpoints_raise_not_implemented(self) -> None:
        async with RimAPIClient() as client:
            with pytest.raises(NotImplementedError):
                await client.set_colonist_job("col_01", "mining")
            with pytest.raises(NotImplementedError):
                await client.draft_colonist("col_01", True)
            with pytest.raises(NotImplementedError):
                await client.set_work_priorities("col_01", {})
            with pytest.raises(NotImplementedError):
                await client.place_blueprint({})
            with pytest.raises(NotImplementedError):
                await client.set_research_target("electricity")
            with pytest.raises(NotImplementedError):
                await client.pause_game()
            with pytest.raises(NotImplementedError):
                await client.unpause_game()
