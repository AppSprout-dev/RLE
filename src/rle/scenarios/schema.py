"""Pydantic models for scenario configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class VictoryCondition(BaseModel):
    """A single win condition checked each tick."""

    model_config = ConfigDict(frozen=True)

    metric: str
    operator: str  # ">=", "<=", "=="
    value: float


class FailureCondition(BaseModel):
    """A single lose condition checked each tick."""

    model_config = ConfigDict(frozen=True)

    metric: str
    operator: str
    value: float


class TriggeredIncident(BaseModel):
    """An incident to fire at a specific tick during a scenario run."""

    model_config = ConfigDict(frozen=True)

    tick_offset: int
    name: str
    map_id: int = 0
    incident_parms: dict[str, Any] = {}


class SetupCommand(BaseModel):
    """A pre-game setup command dispatched before the game loop starts."""

    model_config = ConfigDict(frozen=True)

    type: str  # "spawn_pawn", "spawn_item", "drop_pod", "change_weather"
    params: dict[str, Any] = {}


class ScenarioConfig(BaseModel):
    """Complete scenario definition loaded from YAML."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    difficulty: str
    expected_duration_days: int
    initial_population: int
    victory_conditions: list[VictoryCondition]
    failure_conditions: list[FailureCondition]
    scoring_weights: dict[str, float] = {}
    max_ticks: int | None = None
    save_name: str = ""
    save_sha256: str | None = None
    """Pinned SHA-256 of the docker/saves/<save_name>.rws file. When set, the
    loader compares it against the on-disk save and refuses to start on
    mismatch unless allow_unpinned=True. Generate via scripts/hash_saves.py."""
    triggered_incidents: list[TriggeredIncident] = []
    setup_commands: list[SetupCommand] = []


class BaselinePoint(BaseModel):
    """One sampled point on a baseline score trajectory (loop-tick indexed)."""

    model_config = ConfigDict(frozen=True)

    tick: int
    composite_mean: float
    composite_ci95: tuple[float, float] | None = None
    n_runs: int
    metric_means: dict[str, float] = {}


class BaselineReference(BaseModel):
    """Pinned no-agent calibration for a scenario (Phase B1).

    Persisted as a .baseline.json sidecar next to the scenario YAML and
    treated as an immutable scenario property: recharacterize only when the
    scenario's save_sha256 or SCORING_VERSION changes. Agent runs compute
    lift against this pinned trajectory instead of re-running baselines.
    """

    model_config = ConfigDict(frozen=True)

    scenario_name: str
    n_runs: int
    seeds: tuple[int, ...]
    outcomes: tuple[str, ...]
    """Per-run terminal outcome ("defeat" = natural colony death,
    "victory" possible if the unmanaged colony outlasts the scenario)."""
    time_to_end_days_mean: float
    time_to_end_days_ci95: tuple[float, float] | None = None
    score_trajectory: tuple[BaselinePoint, ...]
    recorded_on: str
    save_sha256: str | None = None
    rimapi_dll_sha256: str | None = None
    rle_commit: str | None = None
    scoring_version: str
