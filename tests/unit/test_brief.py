"""Harness-neutral scenario brief."""

from __future__ import annotations

from rle.harness.brief import action_catalog, build_brief, build_map_summary
from rle.rimapi.schemas import (
    AreaRect,
    ColonyData,
    GameState,
    MapData,
    ResearchData,
    ResourceData,
    TerrainSummary,
    WeatherData,
)
from rle.rimapi.sse_client import RimAPIEvent
from rle.scenarios.loader import list_scenarios


def _state(with_terrain: bool = True) -> GameState:
    terrain = TerrainSummary(
        colony_center=(50, 50),
        recommended_shelter=AreaRect(x1=40, z1=40, x2=46, z2=46),
        recommended_farm=AreaRect(x1=60, z1=40, x2=67, z2=47),
        recommended_stockpile=AreaRect(x1=48, z1=52, x2=52, z2=56),
        water_areas=[AreaRect(x1=0, z1=0, x2=5, z2=90)],
    ) if with_terrain else None
    return GameState(
        colony=ColonyData(
            name="T", wealth=5000.0, day=3, tick=180000,
            population=3, mood_average=0.6, food_days=4.0,
        ),
        colonists=[],
        resources=ResourceData(
            food=40.0, medicine=2, steel=50, wood=120, components=3, silver=0, power_net=0.0,
        ),
        map=MapData(
            size=(250, 250), biome="temperate_forest", season="spring",
            temperature=15.0, structures=[], terrain=terrain,
        ),
        research=ResearchData(current_project=None, progress=0.0, completed=[], available=["a"]),
        threats=[],
        weather=WeatherData(condition="clear", temperature=15.0, outdoor_severity=0.0),
        timestamp=0.0,
    )


class TestMapSummary:
    def test_none_without_terrain(self) -> None:
        assert build_map_summary(_state(with_terrain=False)) is None

    def test_contains_verified_sites_and_water(self) -> None:
        text = build_map_summary(_state())
        assert text is not None
        assert "SHELTER SITE" in text and "(40,40)-(46,46)" in text
        assert "FARM SITE" in text and "x1=60,z1=40,x2=67,z2=47" in text
        assert "STOCKPILE SITE" in text
        assert "WATER (do NOT build here)" in text
        assert "Zones: NONE" in text and "Rooms: NONE" in text


class TestActionCatalog:
    def test_includes_no_action_and_every_write(self) -> None:
        names = {a["action_type"] for a in action_catalog()}
        assert "no_action" in names
        assert {"work_priority", "draft", "blueprint", "growing_zone"} <= names


class TestBrief:
    def test_brief_carries_goals_state_events_and_actions(self) -> None:
        scenario = list_scenarios()[0]
        events = [RimAPIEvent(event_type="raid", data={"points": 500}, timestamp=1.0)]
        brief = build_brief(
            _state(), tick=2, macro_time=0.1, scenario=scenario, events=events,
        )
        assert brief.tick == 2 and brief.day == 3
        assert brief.goals["name"] == scenario.name
        assert brief.goals["victory"]
        assert brief.state["colony"]["population"] == 3
        assert brief.recent_events[0]["event_type"] == "raid"
        assert brief.map_summary and "SHELTER SITE" in brief.map_summary
        text = brief.to_text()
        assert "## Scenario" in text and "## MAP_SUMMARY" in text
        assert "## Actions available" in text and "- draft:" in text

    def test_brief_without_scenario(self) -> None:
        brief = build_brief(_state(with_terrain=False), tick=0, macro_time=0.0)
        assert brief.goals == {}
        assert brief.map_summary is None
        assert "## Scenario" not in brief.to_text()
