"""Tests for scenario YAML loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from rle.scenarios.loader import list_scenarios, load_scenario
from rle.scenarios.schema import ScenarioConfig

DEFINITIONS_DIR = Path(__file__).parent.parent.parent / "src" / "rle" / "scenarios" / "definitions"


class TestLoadScenario:
    def test_load_crashlanded(self) -> None:
        path = DEFINITIONS_DIR / "01_crashlanded_survival.yaml"
        scenario = load_scenario(path)
        assert isinstance(scenario, ScenarioConfig)
        assert scenario.name == "Crashlanded Survival"
        assert scenario.difficulty == "easy"
        assert scenario.expected_duration_days == 30
        assert scenario.initial_population == 3
        assert len(scenario.victory_conditions) == 2
        assert len(scenario.failure_conditions) == 1

    def test_load_ship_launch(self) -> None:
        path = DEFINITIONS_DIR / "06_ship_launch.yaml"
        scenario = load_scenario(path)
        assert scenario.name == "Ship Launch"
        assert scenario.difficulty == "extreme"
        assert scenario.expected_duration_days == 120

    def test_scoring_weights_override(self) -> None:
        path = DEFINITIONS_DIR / "04_raid_defense.yaml"
        scenario = load_scenario(path)
        assert scenario.scoring_weights["threat_response"] == 0.24

    def test_invalid_path_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_scenario("/nonexistent/scenario.yaml")


class TestScoringWeights:
    """Verify every scenario YAML's scoring_weights sum to 1.0."""

    @pytest.mark.parametrize(
        "yaml_file",
        sorted(DEFINITIONS_DIR.glob("*.yaml")),
        ids=lambda p: p.stem,
    )
    def test_weights_sum_to_one(self, yaml_file: Path) -> None:
        scenario = load_scenario(yaml_file)
        if scenario.scoring_weights:
            total = sum(scenario.scoring_weights.values())
            assert total == pytest.approx(1.0), (
                f"{scenario.name}: weights sum to {total}, expected 1.0"
            )


class TestListScenarios:
    def test_loads_all_definitions(self) -> None:
        scenarios = list_scenarios(DEFINITIONS_DIR)
        assert len(scenarios) == 6
        names = [s.name for s in scenarios]
        assert "Crashlanded Survival" in names
        assert "Ship Launch" in names

    def test_default_directory(self) -> None:
        scenarios = list_scenarios()
        assert len(scenarios) == 6
