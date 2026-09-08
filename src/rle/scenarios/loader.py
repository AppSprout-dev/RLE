"""YAML scenario loader and validator."""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from rle.scenarios.schema import BaselineReference, ScenarioConfig
from rle.tracking.metadata import SCORING_VERSION, file_sha256

# Canonical save mirror (the same files that get baked into the Docker image).
# Resolves to <repo_root>/docker/saves/. The YAML pin is checked against this
# path. Native (non-docker) ``POST /game/load`` reads RimWorld AppData Saves,
# not docker/saves — ``ensure_live_save()`` copies the canonical file there
# when the live hash ≠ the pin. Docker entrypoint already symlinks /opt/saves.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CANONICAL_SAVES_DIR = _REPO_ROOT / "docker" / "saves"

logger = logging.getLogger(__name__)


class ScenarioSaveMismatchError(RuntimeError):
    """Raised when a scenario's pinned save_sha256 doesn't match the on-disk
    save file. Bypass with allow_unpinned=True (intentional override only)."""


class LiveSavePinError(RuntimeError):
    """Raised when the native AppData save cannot be made to match the pin.

    Fail-closed: missing canonical, unreadable copy, or a post-copy hash that
    still disagrees with ``save_sha256`` all abort rather than load a stale
    file via ``POST /api/v1/game/load``.
    """


@dataclass(frozen=True)
class LiveSaveStatus:
    """Result of staging a pinned save into RimWorld's live Saves folder."""

    save_name: str
    live_path: Path
    live_save_sha256: str
    copied: bool
    pinned_sha256: str


def canonical_save_path(save_name: str) -> Path:
    """The pinned, repo-mirrored .rws file path for a given save name."""
    return _CANONICAL_SAVES_DIR / f"{save_name}.rws"


def default_rimworld_saves_dir() -> Path:
    """RimWorld's OS-specific Saves folder (what ``POST /game/load`` reads).

    Honors ``$RLE_RIMWORLD_SAVES`` when set (tests / nonstandard installs).
    Otherwise: Windows AppData LocalLow, macOS Application Support, or the
    Linux Unity ``~/.config/unity3d/Ludeon Studios/.../Saves`` path.
    """
    override = os.environ.get("RLE_RIMWORLD_SAVES")
    if override:
        return Path(override)
    if sys.platform == "win32":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        return (
            user_profile / "AppData" / "LocalLow" / "Ludeon Studios"
            / "RimWorld by Ludeon Studios" / "Saves"
        )
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support"
            / "RimWorld" / "Saves"
        )
    return (
        Path.home() / ".config" / "unity3d" / "Ludeon Studios"
        / "RimWorld by Ludeon Studios" / "Saves"
    )


def live_save_path(save_name: str, *, live_dir: Path | None = None) -> Path:
    """``<Saves>/<save_name>.rws`` — the file RimWorld loads by name."""
    return (live_dir or default_rimworld_saves_dir()) / f"{save_name}.rws"


def ensure_live_save(
    save_name: str,
    expected_sha256: str,
    *,
    live_dir: Path | None = None,
    canonical_path: Path | None = None,
) -> LiveSaveStatus:
    """Make the live AppData save match the scenario pin before ``game/load``.

    If the live file already hashes to ``expected_sha256``, this is a no-op.
    Otherwise copy ``docker/saves/<name>.rws`` (or ``canonical_path``) into
    the live Saves folder and re-hash. Raises ``LiveSavePinError`` when the
    canonical file is missing or the live file still disagrees after copy.
    """
    if not save_name:
        raise ValueError("save_name is required")
    if not expected_sha256:
        raise ValueError("expected_sha256 is required")

    source = canonical_path if canonical_path is not None else canonical_save_path(save_name)
    canonical_hash = file_sha256(source)
    if canonical_hash is None:
        raise LiveSavePinError(
            f"Canonical save for {save_name!r} is missing at {source}. "
            "Cannot stage a pinned live save; fail closed.",
        )
    if canonical_hash != expected_sha256:
        raise LiveSavePinError(
            f"Canonical save {source} hashes to {canonical_hash} but the "
            f"scenario pins {expected_sha256}. Re-pin via scripts/hash_saves.py "
            "or restore docker/saves/; fail closed.",
        )

    dest = live_save_path(save_name, live_dir=live_dir)
    live_hash = file_sha256(dest)
    if live_hash == expected_sha256:
        logger.info(
            "Live save %s already matches pin sha256=%s (%s)",
            save_name, expected_sha256, dest,
        )
        return LiveSaveStatus(
            save_name=save_name,
            live_path=dest,
            live_save_sha256=live_hash,
            copied=False,
            pinned_sha256=expected_sha256,
        )

    _copy_canonical_to_live(source, dest)
    copied_hash = file_sha256(dest)
    if copied_hash != expected_sha256:
        raise LiveSavePinError(
            f"Copied {source} to {dest} but live hash is {copied_hash}, "
            f"expected pin {expected_sha256}. Fail closed.",
        )
    logger.info(
        "Staged live save %s from %s -> %s sha256=%s (was %s)",
        save_name, source, dest, copied_hash, live_hash,
    )
    return LiveSaveStatus(
        save_name=save_name,
        live_path=dest,
        live_save_sha256=copied_hash,
        copied=True,
        pinned_sha256=expected_sha256,
    )


def _copy_canonical_to_live(source: Path, dest: Path) -> None:
    """Atomically replace the live save with the canonical file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_name(dest.name + ".staging")
    try:
        shutil.copy2(source, tmp_path)
        os.replace(tmp_path, dest)
    except OSError as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise LiveSavePinError(
            f"Failed to copy canonical save {source} to {dest}: {exc}",
        ) from exc


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
