"""Load a scenario save and wait until the game is actually ready.

``load_game`` returns HTTP 200 before Unity's main thread has applied the
load. Writes that race the settle window get 500'd and, worse, can start a
null-ref cascade that poisons the rest of the session. Every entry point
(single scenario, benchmark matrix, baseline reloads) must use this helper
rather than a fixed sleep so agent and baseline runs start from the same
settled state.
"""

from __future__ import annotations

import asyncio
import logging

from rle.docker import wait_for_rimapi
from rle.rimapi.client import RimAPIClient

logger = logging.getLogger(__name__)

# The colony population must be > 0 and unchanged for this many consecutive
# polls (2 s apart) before we consider the load settled (~10 s).
STABLE_POLLS_REQUIRED = 5
POLL_INTERVAL_S = 2.0
MAX_POLLS = 30


async def load_save_and_settle(
    client: RimAPIClient,
    rimapi_url: str,
    save_name: str,
    *,
    unforbid_items: bool = True,
    rimapi_timeout_s: float = 30.0,
) -> int:
    """Load ``save_name`` and block until the colony is stable.

    Returns the number of starting items unforbidden (0 when disabled).
    Raises whatever ``load_game`` / ``wait_for_rimapi`` raise so callers can
    decide whether to skip the run.
    """
    await client.load_game(save_name)
    await wait_for_rimapi(rimapi_url, timeout=rimapi_timeout_s)
    stable_count = 0
    last_population = -1
    for _ in range(MAX_POLLS):
        await asyncio.sleep(POLL_INTERVAL_S)
        try:
            colony = await client.get_colony()
        except Exception:
            stable_count = 0
            continue
        if colony.population > 0 and colony.population == last_population:
            stable_count += 1
            if stable_count >= STABLE_POLLS_REQUIRED:
                break
        else:
            stable_count = 0
        last_population = colony.population
    else:
        logger.warning("Save %s never reported a stable population; continuing", save_name)
    if not unforbid_items:
        return 0
    count = await client.unforbid_all_items()
    return int(count or 0)
