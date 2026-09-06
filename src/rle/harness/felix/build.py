"""Construct a fully wired FelixHarness from HarnessContext + FelixOptions."""

from __future__ import annotations

from typing import Any

from felix_agent_sdk.core import HelixGeometry
from felix_agent_sdk.providers.base import BaseProvider
from felix_agent_sdk.visualization import HelixVisualizer
from pydantic import BaseModel

from rle.config import bridge_anthropic_key, bridge_openrouter_key
from rle.harness.felix.agents import AGENT_DISPLAY
from rle.harness.felix.agents.base_role import RimWorldRoleAgent
from rle.harness.felix.agents.construction_planner import ConstructionPlanner
from rle.harness.felix.agents.defense_commander import DefenseCommander
from rle.harness.felix.agents.map_analyst import MapAnalyst
from rle.harness.felix.agents.medical_officer import MedicalOfficer
from rle.harness.felix.agents.research_director import ResearchDirector
from rle.harness.felix.agents.resource_manager import ResourceManager
from rle.harness.felix.agents.social_overseer import SocialOverseer
from rle.harness.felix.harness import FelixHarness
from rle.harness.felix.options import FelixOptions, select_role_ids
from rle.harness.felix.provider_factory import build_helix, build_provider
from rle.harness.felix.smoke import SmokeProvider
from rle.harness.protocol import HarnessContext

# Context extras understood by this builder.
WEAVE_MODULE_EXTRA = "weave_module"

_ROLE_CTORS: dict[str, type[RimWorldRoleAgent]] = {
    "map_analyst": MapAnalyst,
    "resource_manager": ResourceManager,
    "defense_commander": DefenseCommander,
    "research_director": ResearchDirector,
    "social_overseer": SocialOverseer,
    "construction_planner": ConstructionPlanner,
    "medical_officer": MedicalOfficer,
}


def create_agents(
    provider: BaseProvider,
    helix: HelixGeometry,
    *,
    roles: list[str] | None = None,
    exclude_agent: str | list[str] | None = None,
    provider_kwargs: dict[str, Any] | None = None,
    no_think: bool = False,
) -> list[RimWorldRoleAgent]:
    """Instantiate the requested Felix roster (default: all 7 agents)."""
    excluded: list[str] | None
    if isinstance(exclude_agent, str):
        excluded = [exclude_agent]
    else:
        excluded = exclude_agent
    selected = select_role_ids(roles=roles, exclude_agent=excluded)
    agents: list[RimWorldRoleAgent] = [
        _ROLE_CTORS[role](role, provider, helix, spawn_time=0.0, velocity=1.0)
        for role in selected
    ]
    for agent in agents:
        if provider_kwargs:
            agent.set_provider_kwargs(**provider_kwargs)
        if no_think:
            agent.set_no_think(True)
    return agents


def create_visualizer(
    helix: HelixGeometry, agents: list[RimWorldRoleAgent], title: str = "R L E",
) -> HelixVisualizer:
    visualizer = HelixVisualizer(helix, title=title)
    for agent in agents:
        display = AGENT_DISPLAY[agent.agent_id]
        visualizer.register_agent(
            agent.agent_id, label=display["label"], color=display["color"],
        )
    return visualizer


def build_felix_harness(
    ctx: HarnessContext, options: BaseModel, *, smoke: bool = False,
) -> FelixHarness:
    opts = options if isinstance(options, FelixOptions) else FelixOptions.model_validate(
        options.model_dump(),
    )
    provider: BaseProvider
    if smoke or ctx.smoke:
        provider = SmokeProvider()
    else:
        bridge_openrouter_key(ctx.config)
        bridge_anthropic_key(ctx.config)
        provider = build_provider(
            ctx.config.provider, ctx.config.model, ctx.config.provider_base_url,
        )
    helix = build_helix(opts.helix_preset)
    agents = create_agents(
        provider, helix,
        roles=opts.roles,
        exclude_agent=opts.exclude_agent,
        provider_kwargs=opts.provider_kwargs or None,
        no_think=opts.no_think,
    )
    weave_module = ctx.extras.get(WEAVE_MODULE_EXTRA)
    if weave_module is not None:
        for agent in agents:
            agent.enable_weave(weave_module)
    visualizer = create_visualizer(helix, agents) if opts.visualize else None
    return FelixHarness(
        agents,
        parallel=opts.parallel,
        role_timeout_s=opts.role_timeout_s,
        visualizer=visualizer,
    )
