"""CLI entry point: run an RLE scenario."""

from __future__ import annotations

import argparse
import asyncio
import logging

from rle.agents.resource_manager import ResourceManager
from rle.config import RLEConfig
from rle.orchestration.game_loop import RLEGameLoop
from rle.rimapi.client import RimAPIClient


async def main(args: argparse.Namespace) -> None:
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    config = RLEConfig()
    provider = config.get_provider()
    helix = config.get_helix_config().to_geometry()
    agent = ResourceManager(
        "resource_manager_1", provider, helix, spawn_time=0.0, velocity=1.0,
    )

    async with RimAPIClient(config.rimapi_url) as client:
        loop = RLEGameLoop(
            config, client, [agent], expected_duration_days=args.duration,
        )
        results = await loop.run(max_ticks=args.ticks)
        print(f"Completed {len(results)} ticks")
        for r in results:
            print(
                f"  Day {r.day} | {r.execution.total} actions "
                f"({r.execution.executed} executed, {r.execution.failed} failed)"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an RLE scenario")
    parser.add_argument("--ticks", type=int, default=10, help="Number of ticks to run")
    parser.add_argument(
        "--duration", type=int, default=60, help="Expected scenario duration in days",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    asyncio.run(main(parser.parse_args()))
