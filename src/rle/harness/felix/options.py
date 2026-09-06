"""Options accepted by the Felix harness (``--harness-opt key=value``).

The Felix SDK is not imported here. Ablation and roster selection are
harness-layer only — they do not change agent prompts or add scenario tips.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Canonical roster order. Default ``roles=None`` instantiates all seven so
# existing runs do not silently change. ``--harness-opt roles=...`` is the
# include list; ``exclude_agent`` subtracts from that (or from the full
# roster). Both accept a JSON list or a comma-separated string.
CANONICAL_ROLES: tuple[str, ...] = (
    "map_analyst",
    "resource_manager",
    "defense_commander",
    "research_director",
    "social_overseer",
    "construction_planner",
    "medical_officer",
)


def normalize_role_ids(value: object) -> list[str] | None:
    """Coerce a CLI / JSON role value into a de-duplicated id list."""
    if value is None:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        return parts or None
    if isinstance(value, (list, tuple)):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return parts or None
    raise ValueError(f"expected role id list or comma-separated string, got {type(value).__name__}")


def select_role_ids(
    *,
    roles: list[str] | None = None,
    exclude_agent: list[str] | None = None,
) -> list[str]:
    """Resolve the Felix roster from an include list and/or exclusions.

    Unknown ids are rejected. Order is always ``CANONICAL_ROLES`` so ablation
    is deterministic. An empty result raises — a zero-agent Felix run is not
    a valid harness configuration (use ``--harness baseline``).
    """
    wanted = set(roles) if roles is not None else set(CANONICAL_ROLES)
    unknown = sorted(wanted - set(CANONICAL_ROLES))
    if unknown:
        raise ValueError(
            f"unknown Felix role(s) {unknown}; known: {', '.join(CANONICAL_ROLES)}",
        )
    excluded = set(exclude_agent or [])
    unknown_ex = sorted(excluded - set(CANONICAL_ROLES))
    if unknown_ex:
        raise ValueError(
            f"unknown Felix role(s) {unknown_ex}; known: {', '.join(CANONICAL_ROLES)}",
        )
    selected = [role for role in CANONICAL_ROLES if role in wanted and role not in excluded]
    if not selected:
        raise ValueError("Felix roster is empty after applying roles/exclude_agent")
    return selected


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
            "contributes no actions for the tick — the resolver never sees a "
            "partial/timed-out plan. Raise this (e.g. 180) for slow models; the "
            "default stays 60 so existing runs do not silently change."
        ),
    )
    roles: list[str] | None = Field(
        default=None,
        description=(
            "Role ids to instantiate (canonical order). None = all 7. "
            "Comma-separated or JSON list. Combined with exclude_agent."
        ),
    )
    exclude_agent: list[str] | None = Field(
        default=None,
        description=(
            "Drop one or more role agents by id (ablation). Accepts a single "
            "id, a comma-separated string, or a JSON list."
        ),
    )
    provider_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra kwargs forwarded to provider.complete() (e.g. extra_body).",
    )
    visualize: bool = Field(
        default=False,
        description="Render the terminal helix visualiser.",
    )

    @field_validator("roles", "exclude_agent", mode="before")
    @classmethod
    def _coerce_role_list(cls, value: object) -> list[str] | None:
        return normalize_role_ids(value)

    @field_validator("roles", "exclude_agent")
    @classmethod
    def _known_roles(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [role for role in value if role not in CANONICAL_ROLES]
        if unknown:
            raise ValueError(
                f"unknown Felix role(s) {unknown}; known: {', '.join(CANONICAL_ROLES)}",
            )
        seen: set[str] = set()
        out: list[str] = []
        for role in value:
            if role not in seen:
                seen.add(role)
                out.append(role)
        return out
