"""RimAPI as an MCP tool server (requires the ``mcp`` extra).

One tool per ``WRITE_CATALOG`` entry (executed immediately through
``ActionExecutor`` and recorded in the tick ledger), a generic read tool over
``READ_CATALOG``, the harness-neutral brief, and ``end_turn``. Any MCP-capable
coding agent can attach and play; the harness packages that do so live in
their own repositories.
"""

from __future__ import annotations

import json
from typing import Any, cast

from mcp.server.mcpserver import MCPServer

from rle.mcp.session import McpSession
from rle.rimapi.api_catalog import READ_CATALOG, WRITE_CATALOG

SERVER_NAME = "rle"
INSTRUCTIONS = (
    "You are managing a RimWorld colony through the RLE benchmark environment. "
    "Each turn: call get_brief to see the scenario, colony state, MAP_SUMMARY and "
    "available actions; issue writes with the action tools (use MAP_SUMMARY "
    "coordinates verbatim, never invent positions; pawn ids are integers); then "
    "call end_turn with a one-line summary. Writes outside a turn are rejected."
)


def _dumps(value: Any) -> str:
    return json.dumps(value, indent=2, default=str)


def build_server(session: McpSession) -> MCPServer:
    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS)

    @server.tool(
        description="Scenario goals, colony state, MAP_SUMMARY and action catalog for this turn.",
    )
    def get_brief() -> str:
        return session.brief_text()

    @server.tool(
        description="Current colony state as JSON (same data as get_brief, machine-readable).",
    )
    def get_state() -> str:
        return _dumps(session.state_json())

    @server.tool(description="List every write action with its parameter shape.")
    def list_actions() -> str:
        return _dumps(session.actions())

    @server.tool(description="List RIMAPI read endpoints available to rimapi_read.")
    def list_reads() -> str:
        return _dumps({
            name: cast(dict[str, Any], entry).get("description", "")
            for name, entry in sorted(READ_CATALOG.items())
        })

    @server.tool(
        description=(
            "Read a RIMAPI endpoint by catalog name (see list_reads). "
            "params become query-string parameters, e.g. {\"map_id\": 0}."
        ),
    )
    async def rimapi_read(endpoint: str, params: dict[str, Any] | None = None) -> str:
        try:
            return _dumps(await session.read(endpoint, params))
        except Exception as exc:  # surfaced to the agent, never crashes the server
            return _dumps({"error": str(exc)})

    @server.tool(
        description=(
            "Finish this turn. Call once you have issued all writes for the tick; "
            "the environment then advances the game and scores the tick."
        ),
    )
    def end_turn(summary: str = "") -> str:
        session.ledger.end_turn(summary)
        n = len(session.ledger.actions)
        return f"Turn ended after {n} action(s)."

    for name, raw in sorted(WRITE_CATALOG.items()):
        entry = cast(dict[str, Any], raw)
        server.add_tool(
            _make_action_tool(session, name),
            name=name,
            description=(
                f"{entry.get('description', name)}. "
                f"parameters shape: {json.dumps(entry.get('params', {}), default=str)}. "
                "Executes immediately and returns {ok, error}."
            ),
        )
    return server


def _make_action_tool(session: McpSession, action_type: str) -> Any:
    async def tool(
        parameters: dict[str, Any] | None = None,
        target_colonist_id: str | None = None,
        reason: str = "",
    ) -> str:
        try:
            result = await session.act(action_type, parameters, target_colonist_id, reason)
        except Exception as exc:
            result = {"ok": False, "action_type": action_type, "error": str(exc)}
        return _dumps(result)

    tool.__name__ = action_type
    return tool
