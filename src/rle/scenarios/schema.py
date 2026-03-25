"""Pydantic models for scenario configuration."""

from __future__ import annotations

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
