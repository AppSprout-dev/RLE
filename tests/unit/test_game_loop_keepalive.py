"""Tests for the no-pause speed keepalive (issue #05: pause-on-threat).

RimWorld force-pauses on threat letters; in --no-pause mode the loop must
re-assert speed continuously, not just at tick boundaries, or slow models
leave the game frozen for their whole deliberation window.

The keepalive only touches ``_speed_keepalive_s`` and ``_client``, so the
tests build a bare instance instead of wiring the full 7-agent loop.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

from rle.orchestration.game_loop import RLEGameLoop


def _bare_loop(keepalive_s: float, client: MagicMock) -> RLEGameLoop:
    loop = object.__new__(RLEGameLoop)
    loop._speed_keepalive_s = keepalive_s
    loop._client = client
    return loop


class TestSpeedKeepalive:
    async def test_reasserts_speed_repeatedly(self) -> None:
        client = MagicMock()
        client.unpause_game = AsyncMock()
        loop = _bare_loop(0.01, client)

        task = asyncio.create_task(loop._speed_keepalive())
        await asyncio.sleep(0.1)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert client.unpause_game.await_count >= 2

    async def test_survives_client_errors(self) -> None:
        """A flaky RIMAPI call must not kill the keepalive for the run."""
        client = MagicMock()
        client.unpause_game = AsyncMock(side_effect=ConnectionError("rimapi down"))
        loop = _bare_loop(0.01, client)

        task = asyncio.create_task(loop._speed_keepalive())
        await asyncio.sleep(0.1)
        assert not task.done()  # still looping despite every call failing
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert client.unpause_game.await_count >= 2

    async def test_cancellation_stops_cleanly(self) -> None:
        client = MagicMock()
        client.unpause_game = AsyncMock()
        loop = _bare_loop(10.0, client)

        task = asyncio.create_task(loop._speed_keepalive())
        await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert task.cancelled()
