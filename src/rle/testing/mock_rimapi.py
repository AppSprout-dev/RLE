"""In-memory stand-in for RIMAPI so harnesses can be exercised without RimWorld.

Used by ``--smoke-test`` in the CLIs and by external harness packages' test
suites (``rle.testing.run_harness_smoke``). State never changes between
ticks — this proves plumbing, not colony management.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from rle.rimapi.client import RimAPIClient

MOCK_ROUTES: dict[str, dict[str, Any] | list[Any]] = {
    "/api/v1/colonists": [
        {
            "colonist_id": "col_01", "name": "Tynan", "health": 0.95,
            "mood": 0.72, "skills": {"shooting": 8, "construction": 5,
            "cooking": 3, "mining": 6, "intellectual": 4},
            "traits": ["industrious"], "current_job": "mining",
            "is_drafted": False, "needs": {"food": 0.6, "rest": 0.8},
            "injuries": [], "position": [42, 18],
        },
        {
            "colonist_id": "col_02", "name": "Cassandra", "health": 0.88,
            "mood": 0.65, "skills": {"shooting": 3, "construction": 7,
            "cooking": 6, "growing": 8, "intellectual": 6},
            "traits": ["kind"], "current_job": "growing",
            "is_drafted": False, "needs": {"food": 0.5, "rest": 0.7},
            "injuries": [], "position": [30, 22],
        },
        {
            "colonist_id": "col_03", "name": "Randy", "health": 0.92,
            "mood": 0.58, "skills": {"shooting": 10, "melee": 7,
            "construction": 3, "cooking": 2},
            "traits": ["tough", "brawler"], "current_job": None,
            "is_drafted": False, "needs": {"food": 0.4, "rest": 0.6},
            "injuries": [], "position": [50, 10],
        },
    ],
    "/api/v1/resources/summary?map_id=0": {
        "total_items": 800, "total_market_value": 8000.0,
        "critical_resources": {
            "food_summary": {"food_total": 85},
            "medicine_total": 5, "weapon_count": 2,
        },
    },
    "/api/v1/map/buildings?map_id=0": [
        {"id": "s_01", "def_name": "Wall", "position": {"x": 10, "y": 0, "z": 10},
         "hit_points": 300.0, "max_hit_points": 300.0},
    ],
    "/api/v1/research/summary": {
        "current_project": "electricity", "progress": 0.45,
        "completed": ["stonecutting"], "available": ["electricity", "battery", "smithing"],
    },
    "/api/v1/incidents?map_id=0": {"incidents": []},
    "/api/v1/game/state": {
        "name": "New Hope", "wealth": 8000.0, "day": 5, "tick": 300000,
        "population": 3, "mood_average": 0.65, "food_days": 7.0,
    },
    "/api/v1/map/weather?map_id=0": {
        "weather": "clear", "temperature": 22.0,
    },
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
    "/api/v1/resources/stored?map_id=0": {
        "Resources": [
            {"def_name": "WoodLog", "stack_count": 200},
            {"def_name": "Steel", "stack_count": 100},
            {"def_name": "ComponentIndustrial", "stack_count": 10},
        ],
    },
    "/api/v1/map/power/info?map_id=0": {
        "current_power": 0.0,
        "total_consumption": 0.0,
        "currently_stored_power": 0.0,
        "total_power_storage": 0.0,
    },
    "/api/v1/factions": [],
    "/api/v1/ui/alerts?map_id=0": [],
}

_POST_OK = b'{"success": true, "errors": [], "warnings": []}'


class MockRimAPI:
    """Records every POST so tests can assert what a harness wrote."""

    def __init__(self, routes: dict[str, dict[str, Any] | list[Any]] | None = None) -> None:
        self.routes = dict(MOCK_ROUTES if routes is None else routes)
        self.posts: list[tuple[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        raw = request.url.raw_path.decode()
        if request.method == "POST":
            body: Any = None
            if request.content:
                try:
                    body = json.loads(request.content)
                except json.JSONDecodeError:
                    body = request.content.decode(errors="replace")
            self.posts.append((raw.split("?")[0], body))
            return httpx.Response(
                200, content=_POST_OK, headers={"content-type": "application/json"},
            )
        for key in (raw, raw.split("?")[0]):
            if key in self.routes:
                return httpx.Response(
                    200, content=json.dumps(self.routes[key]).encode(),
                    headers={"content-type": "application/json"},
                )
        return httpx.Response(404, content=b"Not found")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def attach(self, client: RimAPIClient, base_url: str = "http://mock") -> RimAPIClient:
        """Point an (entered) RimAPIClient at this mock."""
        client._client = httpx.AsyncClient(transport=self.transport(), base_url=base_url)
        return client


def make_mock_transport() -> httpx.MockTransport:
    return MockRimAPI().transport()
