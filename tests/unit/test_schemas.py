"""Tests for RIMAPI Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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


class TestColonistData:
    def test_valid_construction(self, sample_colonist: ColonistData) -> None:
        assert sample_colonist.colonist_id == "col_01"
        assert sample_colonist.name == "Tynan"
        assert sample_colonist.health == 0.95
        assert sample_colonist.mood == 0.72
        assert sample_colonist.skills["shooting"] == 8
        assert "industrious" in sample_colonist.traits
        assert sample_colonist.current_job == "mining"
        assert sample_colonist.is_drafted is False
        assert sample_colonist.position == (42, 18)

    def test_from_dict(self, sample_colonist_dict: dict) -> None:
        colonist = ColonistData.model_validate(sample_colonist_dict)
        assert colonist.colonist_id == "col_01"
        assert colonist.position == (42, 18)

    def test_frozen(self, sample_colonist: ColonistData) -> None:
        with pytest.raises(ValidationError):
            sample_colonist.name = "Changed"  # type: ignore[misc]

    def test_null_job(self) -> None:
        colonist = ColonistData(
            colonist_id="col_02",
            name="Cassandra",
            health=1.0,
            mood=0.5,
            skills={},
            traits=[],
            current_job=None,
            is_drafted=False,
            needs={},
            injuries=[],
            position=(0, 0),
        )
        assert colonist.current_job is None

    def test_missing_required_field(self) -> None:
        with pytest.raises(ValidationError):
            ColonistData(
                colonist_id="col_03",
                name="Missing",
                # health is missing
            )  # type: ignore[call-arg]


class TestResourceData:
    def test_valid_construction(self, sample_resources: ResourceData) -> None:
        assert sample_resources.food == 120.5
        assert sample_resources.steel == 300
        assert sample_resources.power_net == 200.0
        assert sample_resources.items == {}

    def test_from_dict(self, sample_resources_dict: dict) -> None:
        res = ResourceData.model_validate(sample_resources_dict)
        assert res.food == 120.5

    def test_frozen(self, sample_resources: ResourceData) -> None:
        with pytest.raises(ValidationError):
            sample_resources.food = 0.0  # type: ignore[misc]

    def test_default_items(self) -> None:
        res = ResourceData(
            food=10.0, medicine=0, steel=0, wood=0,
            components=0, silver=0, power_net=0.0,
        )
        assert res.items == {}


class TestStructureData:
    def test_valid_construction(self, sample_structure: StructureData) -> None:
        assert sample_structure.def_name == "Wall"
        assert sample_structure.hit_points == 300.0


class TestMapData:
    def test_valid_construction(self, sample_map: MapData) -> None:
        assert sample_map.size == (250, 250)
        assert sample_map.biome == "temperate_forest"
        assert len(sample_map.structures) == 1

    def test_from_dict(self, sample_map_dict: dict) -> None:
        m = MapData.model_validate(sample_map_dict)
        assert m.biome == "temperate_forest"
        assert m.structures[0].def_name == "Wall"


class TestResearchData:
    def test_valid_construction(self, sample_research: ResearchData) -> None:
        assert sample_research.current_project == "electricity"
        assert sample_research.progress == 0.45
        assert "stonecutting" in sample_research.completed

    def test_no_current_project(self) -> None:
        r = ResearchData(
            current_project=None, progress=0.0, completed=[], available=["electricity"],
        )
        assert r.current_project is None


class TestThreatData:
    def test_valid_construction(self, sample_threat: ThreatData) -> None:
        assert sample_threat.threat_type == "raid"
        assert sample_threat.enemy_count == 5

    def test_no_faction(self) -> None:
        t = ThreatData(
            threat_id="t_02", threat_type="manhunter",
            faction=None, enemy_count=12, threat_level=0.6,
        )
        assert t.faction is None


class TestColonyData:
    def test_valid_construction(self, sample_colony: ColonyData) -> None:
        assert sample_colony.name == "New Hope"
        assert sample_colony.day == 12
        assert sample_colony.food_days == 8.5


class TestWeatherData:
    def test_valid_construction(self, sample_weather: WeatherData) -> None:
        assert sample_weather.condition == "clear"
        assert sample_weather.outdoor_severity == 0.0


class TestGameState:
    def test_composite_construction(self, sample_game_state: GameState) -> None:
        assert sample_game_state.colony.name == "New Hope"
        assert len(sample_game_state.colonists) == 1
        assert sample_game_state.colonists[0].name == "Tynan"
        assert sample_game_state.resources.food == 120.5
        assert sample_game_state.map.biome == "temperate_forest"
        assert sample_game_state.research.current_project == "electricity"
        assert len(sample_game_state.threats) == 1
        assert sample_game_state.weather.condition == "clear"
        assert sample_game_state.timestamp == 1700000000.0

    def test_frozen(self, sample_game_state: GameState) -> None:
        with pytest.raises(ValidationError):
            sample_game_state.timestamp = 0.0  # type: ignore[misc]
