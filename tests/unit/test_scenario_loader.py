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
        assert scenario.scoring_weights["threat_response"] == 0.3

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


class TestSaveSha256Validation:
    """A6: scenarios pin save_sha256; loader rejects mismatches."""

    def test_all_packaged_scenarios_have_pinned_sha256(self) -> None:
        """Every shipped scenario must carry a save_sha256 so live runs
        verify against the canonical docker/saves/ mirror."""
        for scenario in list_scenarios(DEFINITIONS_DIR):
            assert scenario.save_sha256, (
                f"{scenario.name} is missing save_sha256 — "
                f"re-run scripts/hash_saves.py"
            )
            # Must look like a hex SHA-256
            assert len(scenario.save_sha256) == 64
            int(scenario.save_sha256, 16)

    def test_load_rejects_mismatched_sha256(self, tmp_path: Path) -> None:
        """A pinned hash that doesn't match the canonical save file raises
        unless the caller explicitly bypasses with allow_unpinned=True."""
        from rle.scenarios.loader import ScenarioSaveMismatchError

        # Build a minimal YAML with a known-bad pinned hash pointing at
        # a real on-disk save we know the SHA of.
        yaml_text = (
            "name: Test\ndescription: Test\ndifficulty: easy\n"
            "expected_duration_days: 30\ninitial_population: 3\n"
            "victory_conditions: []\nfailure_conditions: []\n"
            "save_name: rle_crashlanded_v1\n"
            'save_sha256: "' + ("0" * 64) + '"\n'
        )
        bad_path = tmp_path / "bad.yaml"
        bad_path.write_text(yaml_text, encoding="utf-8")

        with pytest.raises(ScenarioSaveMismatchError):
            load_scenario(bad_path)

        # allow_unpinned bypasses the check (intentional override).
        scenario = load_scenario(bad_path, allow_unpinned=True)
        assert scenario.save_sha256 == "0" * 64

    def test_load_skips_check_when_canonical_save_missing(
        self, tmp_path: Path,
    ) -> None:
        """If the canonical save file isn't on disk (e.g. CI without the
        Docker volume mounted), the loader doesn't error — file_sha256 returns
        None and the comparison is short-circuited. Live runs that hit the
        missing-save path are a separate failure mode caught at game-load."""
        yaml_text = (
            "name: NoFile\ndescription: T\ndifficulty: easy\n"
            "expected_duration_days: 30\ninitial_population: 3\n"
            "victory_conditions: []\nfailure_conditions: []\n"
            "save_name: this_save_does_not_exist_anywhere\n"
            'save_sha256: "' + ("a" * 64) + '"\n'
        )
        path = tmp_path / "missing.yaml"
        path.write_text(yaml_text, encoding="utf-8")

        # Should not raise — no on-disk file to compare against.
        scenario = load_scenario(path)
        assert scenario.save_sha256 == "a" * 64
