"""Options accepted by the Felix harness (``--harness-opt key=value``)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FelixOptions(BaseModel):
    """Knobs that only make sense for the Felix multi-agent harness.

    These used to be top-level CLI flags / ``RLEConfig`` fields. They live
    here now so the environment and other harnesses never see them.
    """

    model_config = ConfigDict(extra="forbid")

    parallel: bool = Field(
        default=True,
        description="Deliberate the six role agents concurrently (MapAnalyst always first).",
    )
    no_think: bool = Field(
        default=False,
        description="Inject a </think> assistant prefill so thinking models skip reasoning.",
    )
    helix_preset: str = Field(
        default="default",
        description="HelixConfig preset: default | research_heavy | fast_convergence.",
    )
    role_timeout_s: float = Field(
        default=60.0,
        description=(
            "Max wall-clock seconds for a single agent's deliberation. Hung LLM calls "
            "beyond this fire a deliberation_timeout ERROR event and the agent "
            "contributes no actions for the tick."
        ),
    )
    exclude_agent: str | None = Field(
        default=None,
        description="Drop one role agent by id (ablation runs).",
    )
    provider_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra kwargs forwarded to provider.complete() (e.g. extra_body).",
    )
    visualize: bool = Field(
        default=False,
        description="Render the terminal helix visualiser.",
    )
