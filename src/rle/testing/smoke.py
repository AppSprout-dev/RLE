"""Run any harness plugin through the real loop against the mock RIMAPI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from rle.config import RLEConfig
from rle.harness.protocol import HarnessContext, HarnessPlugin
from rle.harness.registry import get_plugin, validate_options
from rle.orchestration.game_loop import RLEGameLoop, TickResult
from rle.rimapi.client import RimAPIClient
from rle.scoring.composite import CompositeScorer
from rle.scoring.recorder import TimeSeriesRecorder
from rle.testing.mock_rimapi import MockRimAPI


@dataclass
class SmokeReport:
    harness: str
    ticks: list[TickResult]
    posts: list[tuple[str, Any]]
    final_composite: float | None
    describe: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return len(self.ticks) > 0


async def run_harness_smoke(
    plugin: HarnessPlugin | str,
    *,
    options: dict[str, Any] | BaseModel | None = None,
    ticks: int = 3,
    config: RLEConfig | None = None,
    mock: MockRimAPI | None = None,
) -> SmokeReport:
    """Build ``plugin.smoke(...)`` and run it for ``ticks`` ticks.

    This is the contract test every harness package should run in CI: if it
    passes, the plugin loads, validates options, produces ``StepResult``s the
    loop can execute/score, and tears down cleanly.
    """
    if isinstance(plugin, str):
        plugin = get_plugin(plugin)
    cfg = config or RLEConfig(tick_interval=0.0)
    mock = mock or MockRimAPI()
    async with RimAPIClient("http://mock") as client:
        mock.attach(client)
        ctx = HarnessContext(config=cfg, client=client, smoke=True)
        harness = plugin.smoke(ctx, validate_options(plugin, options))
        recorder = TimeSeriesRecorder()
        loop = RLEGameLoop(
            cfg, client, harness=harness, harness_context=ctx,
            scorer=CompositeScorer(), recorder=recorder,
        )
        results = await loop.run(max_ticks=ticks)
    final = recorder.snapshots[-1].composite if recorder.snapshots else None
    return SmokeReport(
        harness=harness.name,
        ticks=results,
        posts=list(mock.posts),
        final_composite=final,
        describe=harness.describe(),
    )
