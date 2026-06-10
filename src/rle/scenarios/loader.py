"""YAML scenario loader and validator."""

from __future__ import annotations

from pathlib import Path

import yaml

from rle.scenarios.schema import BaselineReference, ScenarioConfig
from rle.tracking.metadata import SCORING_VERSION, file_sha256

# Canonical save mirror (the same files that get baked into the Docker image).
# Resolves to <repo_root>/docker/saves/. Live game runs may use a save in
# RimWorld's AppData that diverges — that divergence is the bug the pinned
# save_sha256 is meant to surface, not silently absorb.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CANONICAL_SAVES_DIR = _REPO_ROOT / "docker" / "saves"


class ScenarioSaveMismatchError(RuntimeError):
    """Raised when a scenario's pinned save_sha256 doesn't match the on-disk
    save file. Bypass with allow_unpinned=True (intentional override only)."""


def canonical_save_path(save_name: str) -> Path:
    """The pinned, repo-mirrored .rws file path for a given save name."""
    return _CANONICAL_SAVES_DIR / f"{save_name}.rws"


def load_scenario(
    path: str | Path, *, allow_unpinned: bool = False,
) -> ScenarioConfig:
    """Load and validate a YAML scenario file.

    If the scenario has a pinned save_sha256 and the corresponding
    docker/saves/<save_name>.rws file exists, verify the hash matches.
    Mismatches raise ScenarioSaveMismatchError unless allow_unpinned=True.
    """
    path = Path(path)
    with open(path) as f:
        data = yaml.safe_load(f)
    scenario = ScenarioConfig.model_validate(data)

    if scenario.save_sha256 and scenario.save_name and not allow_unpinned:
        save_path = canonical_save_path(scenario.save_name)
        actual = file_sha256(save_path)
        if actual is not None and actual != scenario.save_sha256:
            raise ScenarioSaveMismatchError(
                f"Scenario {scenario.name!r} pins save_sha256="
                f"{scenario.save_sha256} but {save_path} hashes to {actual}. "
                f"Either re-pin via scripts/hash_saves.py or pass "
                f"allow_unpinned=True to bypass.",
            )

    return scenario


class BaselineMismatchError(RuntimeError):
    """Raised when a scenario's .baseline.json was calibrated against a
    different save or scoring version than the scenario currently pins —
    the baseline must be recharacterized (scripts/calibrate_baseline.py)."""


def baseline_path(scenario_path: str | Path) -> Path:
    """Sidecar .baseline.json path for a scenario YAML path."""
    return Path(scenario_path).with_suffix(".baseline.json")


def load_baseline(
    scenario_path: str | Path, scenario: ScenarioConfig,
) -> BaselineReference | None:
    """Load a scenario's pinned baseline sidecar, if one exists.

    Returns None when no sidecar is present. Fails fast (rather than
    silently comparing against a stale reference) when the baseline was
    calibrated against a different save_sha256 or SCORING_VERSION.
    """
    path = baseline_path(scenario_path)
    if not path.is_file():
        return None
    ref = BaselineReference.model_validate_json(path.read_text(encoding="utf-8"))
    if (
        scenario.save_sha256
        and ref.save_sha256
        and ref.save_sha256 != scenario.save_sha256
    ):
        raise BaselineMismatchError(
            f"Baseline {path} was calibrated against save_sha256="
            f"{ref.save_sha256} but scenario {scenario.name!r} now pins "
            f"{scenario.save_sha256}. Recharacterize via "
            f"scripts/calibrate_baseline.py.",
        )
    if ref.scoring_version != SCORING_VERSION:
        raise BaselineMismatchError(
            f"Baseline {path} was recorded at scoring_version="
            f"{ref.scoring_version} but the current version is "
            f"{SCORING_VERSION}. Recharacterize via "
            f"scripts/calibrate_baseline.py.",
        )
    return ref


def list_scenarios(
    directory: str | Path | None = None, *, allow_unpinned: bool = False,
) -> list[ScenarioConfig]:
    """Load all YAML scenario files from a directory.

    Defaults to the built-in definitions/ directory.
    """
    if directory is None:
        directory = Path(__file__).parent / "definitions"
    directory = Path(directory)
    scenarios = []
    for path in sorted(directory.glob("*.yaml")):
        scenarios.append(load_scenario(path, allow_unpinned=allow_unpinned))
    return scenarios
