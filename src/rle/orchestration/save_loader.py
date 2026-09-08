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
from dataclasses import dataclass

from rle.docker import wait_for_rimapi
from rle.rimapi.client import RimAPIClient
from rle.scenarios.loader import LiveSaveStatus, ensure_live_save

logger = logging.getLogger(__name__)

# The colony population must be > 0 and unchanged for this many consecutive
# polls (2 s apart) before we consider the load settled (~10 s).
STABLE_POLLS_REQUIRED = 5
POLL_INTERVAL_S = 2.0
MAX_POLLS = 30


@dataclass(frozen=True)
class LoadSettleResult:
    """Outcome of ``load_save_and_settle`` (unforbid count + optional staging)."""

    unforbid_count: int
    live_save: LiveSaveStatus | None = None


async def load_save_and_settle(
    client: RimAPIClient,
    rimapi_url: str,
    save_name: str,
    *,
    unforbid_items: bool = True,
    rimapi_timeout_s: float = 30.0,
    save_sha256: str | None = None,
    stage_live: bool = False,
) -> LoadSettleResult:
    """Load ``save_name`` and block until the colony is stable.

    When ``stage_live`` is True and ``save_sha256`` is set (native path),
    copy ``docker/saves/<name>.rws`` into RimWorld AppData Saves if the live
    file does not already match the pin. Docker skips this — the entrypoint
    already symlinks ``/opt/saves``. Staging failures raise
    ``LiveSavePinError`` (fail closed) before ``game/load``.

    Returns ``LoadSettleResult`` (unforbid count + live-save status).
    Raises whatever ``load_game`` / ``wait_for_rimapi`` / staging raise so
    callers can decide whether to skip the run.
    """
    live_save: LiveSaveStatus | None = None
    if stage_live and save_sha256:
        live_save = ensure_live_save(save_name, save_sha256)
        logger.info(
            "live_save_sha256=%s copied=%s path=%s",
            live_save.live_save_sha256,
            live_save.copied,
            live_save.live_path,
        )
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
        return LoadSettleResult(unforbid_count=0, live_save=live_save)
    count = await client.unforbid_all_items()
    return LoadSettleResult(unforbid_count=int(count or 0), live_save=live_save)
