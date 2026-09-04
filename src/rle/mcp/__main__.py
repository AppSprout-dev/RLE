"""``rle-mcp`` — stdio MCP server against a live RIMAPI, for manual play.

Standalone mode has no environment loop: every call is "in a tick", writes go
straight to the game, and the ledger is only informational. Benchmark runs
use ``rle.mcp.host.McpHost`` inside a harness instead.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from rle.config import RLEConfig
from rle.harness.brief import build_brief
from rle.mcp.ledger import TickLedger
from rle.mcp.server import build_server
from rle.mcp.session import McpSession
from rle.orchestration.action_executor import ActionExecutor
from rle.orchestration.state_manager import GameStateManager
from rle.rimapi.client import RimAPIClient


async def _serve(rimapi_url: str) -> None:
    async with RimAPIClient(rimapi_url) as client:
        ledger = TickLedger(harness_name="manual")
        session = McpSession(client=client, executor=ActionExecutor(client), ledger=ledger)
        manager = GameStateManager(client, expected_duration_days=30)
        try:
            state = await manager.refresh()
            session.begin_tick(0, state, build_brief(state, tick=0, macro_time=0.0))
        except Exception:
            logging.getLogger(__name__).warning(
                "RIMAPI not reachable at %s — serving with an empty brief", rimapi_url,
            )
            ledger.active = True
        await build_server(session).run_stdio_async()


def main() -> None:
    parser = argparse.ArgumentParser(description="RLE RimAPI MCP server (stdio)")
    parser.add_argument("--rimapi-url", default=None, help="Default: RIMAPI_URL / config")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))
    config = RLEConfig()
    asyncio.run(_serve(args.rimapi_url or config.rimapi_url))


if __name__ == "__main__":
    main()
