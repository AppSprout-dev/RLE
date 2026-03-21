"""YAML scenario loader and validator."""

from __future__ import annotations

from pathlib import Path

import yaml

from rle.scenarios.schema import ScenarioConfig


def load_scenario(path: str | Path) -> ScenarioConfig:
    """Load and validate a YAML scenario file."""
    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f)
    return ScenarioConfig.model_validate(data)


def list_scenarios(directory: str | Path | None = None) -> list[ScenarioConfig]:
    """Load all YAML scenario files from a directory.

    Defaults to the built-in definitions/ directory.
    """
    if directory is None:
        directory = Path(__file__).parent / "definitions"
    directory = Path(directory)
    scenarios = []
    for path in sorted(directory.glob("*.yaml")):
        scenarios.append(load_scenario(path))
    return scenarios
