"""HeadlessCliHarness driven by the scripted MCP agent through the real loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, ClassVar

import pytest

from rle.config import RLEConfig
from rle.harness import HarnessContext, HarnessStepError
from rle.orchestration.game_loop import RLEGameLoop
from rle.rimapi.client import RimAPIClient
from rle.scoring.composite import CompositeScorer
from rle.testing import MockRimAPI
from rle.tracking.event_log import EventLog, EventType

cli_base = pytest.importorskip("rle.harness.cli_base")
scripted = pytest.importorskip("rle.testing.scripted_agent")


@asynccontextmanager
async def _env() -> AsyncIterator[tuple[RimAPIClient, MockRimAPI]]:
    mock = MockRimAPI()
    async with RimAPIClient("http://mock") as client:
        mock.attach(client)
        yield client, mock


class TestScriptedMcpHarness:
    async def test_full_round_trip_through_loop(self, tmp_path: Path) -> None:
        log = EventLog(tmp_path / "events.jsonl")
        harness = scripted.ScriptedMcpHarness()
        async with _env() as (client, mock):
            config = RLEConfig(tick_interval=0.0)
            ctx = HarnessContext(config=config, client=client, event_log=log)
            loop = RLEGameLoop(
                config, client, harness=harness, harness_context=ctx,
                scorer=CompositeScorer(), event_log=log,
            )
            results = await loop.run(max_ticks=2)

        assert len(results) == 2
        # research_target went to RIMAPI via the MCP tool, once per tick
        research_posts = [p for p, _ in mock.posts if "research" in p]
        assert len(research_posts) == 2
        # Ledger reported the execution; the loop did not re-execute
        assert results[0].execution.executed == 1
        assert results[0].plan.role == "scripted-mcp"
        assert results[0].plan.summary == "scripted smoke turn"
        assert results[0].extras["status"] == "success"
        assert results[0].extras["turn_ended"] is True
        assert harness.parse_successes == 2
        assert len(harness.turns) == 2 and "get_brief" in harness.turns[0]
        kinds = {e.event_type for e in log.events}
        assert {EventType.DELIBERATION, EventType.ACTION_EXEC, EventType.PROVIDER_CALL} <= kinds
        # MCP host torn down with the loop
        assert not harness._host.running  # type: ignore[union-attr]

    async def test_describe_includes_agent_versions(self) -> None:
        harness = scripted.ScriptedMcpHarness(
            cli_base.HeadlessCliOptions(model="some/model"), name="my-tool",
        )
        async with _env() as (client, _mock):
            ctx = HarnessContext(config=RLEConfig(tick_interval=0.0), client=client)
            await harness.setup(ctx)
            try:
                info = harness.describe()
            finally:
                await harness.teardown()
        assert info == {"harness": "my-tool", "model": "some/model", "scripted_agent": "1"}

    async def test_setup_hands_agent_advertised_url(self) -> None:
        harness = scripted.ScriptedMcpHarness(
            cli_base.HeadlessCliOptions(
                mcp_bind_host="127.0.0.1",
                mcp_advertise_host="host.docker.internal",
                mcp_port=0,
            ),
        )
        async with _env() as (client, _mock):
            ctx = HarnessContext(config=RLEConfig(tick_interval=0.0), client=client)
            await harness.setup(ctx)
            try:
                assert harness.mcp_url == (
                    f"http://host.docker.internal:{harness._host.port}/mcp"  # type: ignore[union-attr]
                )
                assert harness._url == harness.mcp_url
                assert harness._host.bind_host == "127.0.0.1"  # type: ignore[union-attr]
            finally:
                await harness.teardown()


class _NeverEndsTurn(scripted.ScriptedMcpHarness):  # type: ignore[misc]
    name: ClassVar[str] = "never-ends"

    async def send_turn(self, prompt: str) -> Any:
        await asyncio.sleep(10)
        return cli_base.TurnResult()


class _Crashes(scripted.ScriptedMcpHarness):  # type: ignore[misc]
    name: ClassVar[str] = "crashes"

    async def send_turn(self, prompt: str) -> Any:
        raise HarnessStepError("binary exited 1")


class TestTurnFailures:
    async def test_turn_timeout_scores_empty_tick(self) -> None:
        harness = _NeverEndsTurn(
            cli_base.HeadlessCliOptions(turn_timeout_s=0.2, idle_grace_s=0.05),
        )
        async with _env() as (client, _mock):
            loop = RLEGameLoop(RLEConfig(tick_interval=0.0), client, harness=harness)
            result = await loop.run(max_ticks=1)
        assert result[0].extras["status"] == "turn_timeout"
        assert result[0].execution.total == 0
        assert harness.parse_failures == 1

    async def test_agent_error_scores_empty_tick(self) -> None:
        harness = _Crashes(cli_base.HeadlessCliOptions(idle_grace_s=0.05))
        async with _env() as (client, _mock):
            loop = RLEGameLoop(RLEConfig(tick_interval=0.0), client, harness=harness)
            result = await loop.run(max_ticks=1)
        assert result[0].extras["status"] == "agent_error"
        assert harness.parse_failures == 1
