"""RimAPI MCP server: tools execute immediately and land in the tick ledger."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from rle.agents.actions import Action, ActionOutcome
from rle.harness.brief import build_brief
from rle.mcp import McpSession, NoActiveTickError, TickLedger
from rle.orchestration.action_executor import ActionExecutor
from rle.orchestration.state_manager import GameStateManager
from rle.rimapi.client import RimAPIClient
from rle.scenarios.loader import list_scenarios
from rle.testing import MockRimAPI

mcp_server = pytest.importorskip("rle.mcp.server")
mcp_host = pytest.importorskip("rle.mcp.host")
mcp_client = pytest.importorskip("mcp.client.client")


@asynccontextmanager
async def _session() -> AsyncIterator[tuple[McpSession, MockRimAPI]]:
    mock = MockRimAPI()
    async with RimAPIClient("http://mock") as client:
        mock.attach(client)
        ledger = TickLedger(harness_name="test-tool")
        session = McpSession(client=client, executor=ActionExecutor(client), ledger=ledger)
        state = await GameStateManager(client, 30).refresh()
        brief = build_brief(state, tick=0, macro_time=0.0, scenario=list_scenarios()[0])
        session.begin_tick(0, state, brief)
        yield session, mock


def _text(result: object) -> str:
    content = getattr(result, "content", None)
    assert content, f"no content in {result!r}"
    return str(content[0].text)


class TestLedger:
    def test_writes_outside_tick_rejected(self) -> None:
        ledger = TickLedger()
        with pytest.raises(NoActiveTickError):
            ledger.require_active()

    def test_finish_packages_step_result(self) -> None:
        ledger = TickLedger(harness_name="x")
        ledger.begin(3, 1800)
        ledger.record(
            Action(action_type="draft", target_colonist_id="1", parameters={"is_drafted": True}),
            ActionOutcome(action_type="draft", endpoint="draft", target_colonist_id="1",
                          success=True, parameters={"is_drafted": True}),
        )
        ledger.record(
            Action(action_type="blueprint", parameters={}),
            ActionOutcome(action_type="blueprint", endpoint="blueprint", success=False,
                          error="no coords"),
        )
        ledger.end_turn("done")
        step = ledger.finish()
        assert not ledger.active
        assert step.plan.role == "x" and step.plan.tick == 1800
        assert step.plan.summary == "done"
        assert step.execution is not None
        assert (step.execution.executed, step.execution.failed, step.execution.total) == (1, 1, 2)
        assert step.extras["turn_ended"] is True


class TestToolsInMemory:
    async def test_brief_state_actions_and_reads(self) -> None:
        async with _session() as (session, _mock):
            server = mcp_server.build_server(session)
            names = {t.name for t in await server.list_tools()}
            assert {"get_brief", "get_state", "list_actions", "rimapi_read", "end_turn"} <= names
            assert {"work_priority", "draft", "blueprint", "growing_zone"} <= names

            brief = _text(await server.call_tool("get_brief", {}))
            assert "## Scenario" in brief and "## Actions available" in brief
            state = json.loads(_text(await server.call_tool("get_state", {})))
            assert state["colony"]["population"] == 3
            reads = json.loads(_text(await server.call_tool("list_reads", {})))
            assert "colonists" in reads
            colonists = json.loads(_text(await server.call_tool(
                "rimapi_read", {"endpoint": "colonists"},
            )))
            assert isinstance(colonists, list) and colonists[0]["name"] == "Tynan"
            bad = json.loads(_text(await server.call_tool(
                "rimapi_read", {"endpoint": "nope"},
            )))
            assert "Unknown read endpoint" in bad["error"]

    async def test_write_tool_executes_and_records(self) -> None:
        async with _session() as (session, mock):
            server = mcp_server.build_server(session)
            out = json.loads(_text(await server.call_tool(
                "work_priority",
                {"parameters": {"Growing": 1}, "target_colonist_id": "col_01", "reason": "food"},
            )))
            assert out["ok"] is True
            assert any(p.endswith("/colonist/work-priority") for p, _ in mock.posts)
            assert len(session.ledger.actions) == 1
            assert session.ledger.outcomes[0].success

            ended = _text(await server.call_tool("end_turn", {"summary": "ok"}))
            assert "Turn ended after 1 action(s)" in ended
            step = session.ledger.finish()
            assert step.execution is not None and step.execution.executed == 1
            assert step.plan.summary == "ok"

    async def test_write_after_turn_closed_is_rejected(self) -> None:
        async with _session() as (session, _mock):
            server = mcp_server.build_server(session)
            session.ledger.finish()
            out = json.loads(_text(await server.call_tool(
                "draft", {"parameters": {"is_drafted": True}, "target_colonist_id": "col_01"},
            )))
            assert out["ok"] is False and "No tick is in progress" in out["error"]
            assert "No tick is in progress" in _text(await server.call_tool("get_brief", {}))

    async def test_no_action_is_recorded_without_execution(self) -> None:
        async with _session() as (session, mock):
            before = len(mock.posts)
            result = await session.act("no_action", reason="nothing to do")
            assert result["ok"] is True
            assert len(mock.posts) == before
            assert len(session.ledger.actions) == 1 and session.ledger.outcomes == []

    async def test_missing_pawn_id_reports_failure(self) -> None:
        async with _session() as (session, _mock):
            result = await session.act("draft", {"is_drafted": True})
            assert result["ok"] is False
            assert "target_colonist_id is required" in (result["error"] or "")
            assert session.ledger.outcomes[0].success is False


class TestHttpHost:
    async def test_client_over_streamable_http(self) -> None:
        async with _session() as (session, _mock):
            host = mcp_host.McpHost(mcp_server.build_server(session))
            url = await host.start()
            try:
                assert url.endswith("/mcp")
                async with mcp_client.Client(url) as client:
                    tools = await client.list_tools()
                    assert any(t.name == "end_turn" for t in tools.tools)
                    result = await client.call_tool(
                        "research_target", {"parameters": {"project": "Electricity"}},
                    )
                    assert json.loads(_text(result))["ok"] is True
                    assert len(session.ledger.actions) == 1
            finally:
                await host.stop()
            assert not host.running
