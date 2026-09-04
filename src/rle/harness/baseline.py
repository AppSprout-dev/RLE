"""Unmanaged baseline harness — the colony runs on RimWorld's own AI."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from rle.agents.actions import ActionPlan
from rle.harness.protocol import (
    Availability,
    BaseHarness,
    EmptyOptions,
    HarnessContext,
    StepResult,
)
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent


class BaselineHarness(BaseHarness):
    """Proposes nothing every tick. Paired against every other harness."""

    name: ClassVar[str] = "baseline"

    async def step(
        self, state: GameState, tick: int, macro_time: float,
        events: list[RimAPIEvent],
    ) -> StepResult:
        return StepResult(
            plan=ActionPlan(
                role="baseline", tick=state.colony.tick, actions=[],
                summary="No agents",
            ),
        )


class BaselinePlugin:
    name = "baseline"
    description = "Unmanaged colony (RimWorld built-in AI). The paired control for every run."

    def available(self) -> Availability:
        return Availability.available()

    def option_schema(self) -> type[BaseModel]:
        return EmptyOptions

    def create(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        return BaselineHarness()

    def smoke(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        return BaselineHarness()

    def describe(self) -> dict[str, str]:
        return {"harness": self.name}


PLUGIN = BaselinePlugin()
