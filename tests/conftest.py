"""Shared test fixtures for RLE."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from felix_agent_sdk.core import HelixConfig, HelixGeometry
from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.providers.types import CompletionResult
from rle.config import RLEConfig
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

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------


@pytest.fixture
def mock_config() -> RLEConfig:
    return RLEConfig(
        rimapi_url="http://localhost:8765",
        provider="anthropic",
        model="claude-sonnet-4-5",
        tick_interval=0.5,
        helix_preset="default",
        max_agents=7,
        log_level="DEBUG",
    )


# ------------------------------------------------------------------
# Schema fixtures
# ------------------------------------------------------------------


@pytest.fixture
def sample_colonist() -> ColonistData:
    return ColonistData(
        colonist_id="col_01",
        name="Tynan",
        health=0.95,
        mood=0.72,
        skills={"shooting": 8, "construction": 5, "cooking": 3, "mining": 6},
        traits=["industrious", "tough"],
        current_job="mining",
        is_drafted=False,
        needs={"food": 0.6, "rest": 0.8, "recreation": 0.4},
        injuries=[],
        position=(42, 18),
    )


@pytest.fixture
def sample_colonist_dict() -> dict:
    return {
        "colonist_id": "col_01",
        "name": "Tynan",
        "health": 0.95,
        "mood": 0.72,
        "skills": {"shooting": 8, "construction": 5, "cooking": 3, "mining": 6},
        "traits": ["industrious", "tough"],
        "current_job": "mining",
        "is_drafted": False,
        "needs": {"food": 0.6, "rest": 0.8, "recreation": 0.4},
        "injuries": [],
        "position": [42, 18],
    }


@pytest.fixture
def sample_resources() -> ResourceData:
    return ResourceData(
        food=120.5,
        medicine=8,
        steel=300,
        wood=450,
        components=12,
        silver=1500,
        power_net=200.0,
    )


@pytest.fixture
def sample_resources_dict() -> dict:
    return {
        "food": 120.5,
        "medicine": 8,
        "steel": 300,
        "wood": 450,
        "components": 12,
        "silver": 1500,
        "power_net": 200.0,
        "items": {},
    }


@pytest.fixture
def sample_structure() -> StructureData:
    return StructureData(
        structure_id="s_01",
        def_name="Wall",
        position=(10, 10),
        hit_points=300.0,
        max_hit_points=300.0,
    )


@pytest.fixture
def sample_map(sample_structure: StructureData) -> MapData:
    return MapData(
        size=(250, 250),
        biome="temperate_forest",
        season="summer",
        temperature=22.0,
        structures=[sample_structure],
    )


@pytest.fixture
def sample_map_dict() -> dict:
    return {
        "size": [250, 250],
        "biome": "temperate_forest",
        "season": "summer",
        "temperature": 22.0,
        "structures": [
            {
                "structure_id": "s_01",
                "def_name": "Wall",
                "position": [10, 10],
                "hit_points": 300.0,
                "max_hit_points": 300.0,
            }
        ],
    }


@pytest.fixture
def sample_research() -> ResearchData:
    return ResearchData(
        current_project="electricity",
        progress=0.45,
        completed=["stonecutting"],
        available=["electricity", "battery", "smithing"],
    )


@pytest.fixture
def sample_research_dict() -> dict:
    return {
        "current_project": "electricity",
        "progress": 0.45,
        "completed": ["stonecutting"],
        "available": ["electricity", "battery", "smithing"],
    }


@pytest.fixture
def sample_threat() -> ThreatData:
    return ThreatData(
        threat_id="t_01",
        threat_type="raid",
        faction="pirate",
        enemy_count=5,
        threat_level=0.4,
    )


@pytest.fixture
def sample_threat_dict() -> dict:
    return {
        "id": "t_01",
        "def_name": "raid",
        "faction": "pirate",
        "enemy_count": 5,
        "threat_level": 0.4,
    }


@pytest.fixture
def sample_colony() -> ColonyData:
    return ColonyData(
        name="New Hope",
        wealth=15000.0,
        day=12,
        tick=720000,
        population=3,
        mood_average=0.68,
        food_days=8.5,
    )


@pytest.fixture
def sample_colony_dict() -> dict:
    return {
        "name": "New Hope",
        "wealth": 15000.0,
        "day": 12,
        "tick": 720000,
        "population": 3,
        "mood_average": 0.68,
        "food_days": 8.5,
    }


@pytest.fixture
def sample_weather() -> WeatherData:
    return WeatherData(
        condition="clear",
        temperature=22.0,
        outdoor_severity=0.0,
    )


@pytest.fixture
def sample_weather_dict() -> dict:
    return {
        "condition": "clear",
        "temperature": 22.0,
        "outdoor_severity": 0.0,
    }


@pytest.fixture
def sample_game_state(
    sample_colony: ColonyData,
    sample_colonist: ColonistData,
    sample_resources: ResourceData,
    sample_map: MapData,
    sample_research: ResearchData,
    sample_threat: ThreatData,
    sample_weather: WeatherData,
) -> GameState:
    return GameState(
        colony=sample_colony,
        colonists=[sample_colonist],
        resources=sample_resources,
        map=sample_map,
        research=sample_research,
        threats=[sample_threat],
        weather=sample_weather,
        timestamp=1700000000.0,
    )


# ------------------------------------------------------------------
# Agent fixtures
# ------------------------------------------------------------------

SAMPLE_ACTION_PLAN_JSON = json.dumps(
    {
        "actions": [
            {
                "action_type": "set_work_priority",
                "target_colonist_id": "col_01",
                "parameters": {"skill": "growing", "priority": 1},
                "priority": 2,
                "reason": "Food days below 3, need immediate growing focus",
            },
        ],
        "summary": "Prioritizing food production due to low food_days.",
        "confidence": 0.75,
    }
)


@pytest.fixture
def sample_action_plan_json() -> str:
    return SAMPLE_ACTION_PLAN_JSON


@pytest.fixture
def helix() -> HelixGeometry:
    return HelixConfig.default().to_geometry()


@pytest.fixture
def mock_provider() -> MagicMock:
    """Provider mock that returns a valid JSON action plan."""
    provider = MagicMock(spec=BaseProvider)
    provider.complete.return_value = CompletionResult(
        content=SAMPLE_ACTION_PLAN_JSON,
        model="mock-model",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    )
    return provider
