"""Contract tests for the Crashlanded seed (research bench + gzip sibling)."""

from __future__ import annotations

import gzip
from pathlib import Path

from rle.scenarios.loader import canonical_save_path, load_scenario

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = REPO_ROOT / "src" / "rle" / "scenarios" / "definitions"
GZ_SAVE = REPO_ROOT / "saves" / "rle_crashlanded_v1.rws.gz"


def test_crashlanded_save_has_simple_research_bench() -> None:
    path = canonical_save_path("rle_crashlanded_v1")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    assert "<def>SimpleResearchBench</def>" in text
    assert 'Class="Building_ResearchBench"' in text
    assert "<currentProj>Smithing</currentProj>" in text
    assert "<pos>(128, 0, 136)</pos>" in text
    assert "ResearchBench" in text


def test_crashlanded_gzip_round_trips_canonical_rws() -> None:
    raw = canonical_save_path("rle_crashlanded_v1").read_bytes()
    assert GZ_SAVE.is_file()
    assert gzip.decompress(GZ_SAVE.read_bytes()) == raw


def test_crashlanded_yaml_pin_matches_canonical_save() -> None:
    scenario = load_scenario(DEFINITIONS / "01_crashlanded_survival.yaml")
    assert scenario.save_name == "rle_crashlanded_v1"
    assert scenario.save_sha256
    assert len(scenario.save_sha256) == 64
