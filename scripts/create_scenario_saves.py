"""Create scenario save files via RIMAPI.

Loads the base crashlanded save, applies per-scenario setup (spawn pawns,
spawn items, trigger incidents, set research, change weather) through
RIMAPI, then saves each scenario as a new save file.

Prerequisites:
  - RimWorld running with RIMAPI mod loaded
  - Base save `rle_crashlanded_v1` exists and loads cleanly

Usage:
  python scripts/create_scenario_saves.py                    # build all
  python scripts/create_scenario_saves.py --only first_winter  # one only
  python scripts/create_scenario_saves.py --difficulty-only  # just patch
                                                              # difficulty on
                                                              # existing saves
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from rle.rimapi.client import RimAPIClient

DOCKER_SAVES_DIR = Path(__file__).resolve().parent.parent / "docker" / "saves"
BASE_SAVE = "rle_crashlanded_v1"


def _default_rimworld_save_dir() -> Path:
    """Return RimWorld's default save directory for the current OS."""
    if sys.platform == "win32":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        return (
            user_profile / "AppData" / "LocalLow" / "Ludeon Studios"
            / "RimWorld by Ludeon Studios" / "Saves"
        )
    if sys.platform == "darwin":
        return (
            Path.home() / "Library" / "Application Support"
            / "RimWorld" / "Saves"
        )
    # Linux/other
    return (
        Path.home() / ".config" / "unity3d" / "Ludeon Studios"
        / "RimWorld by Ludeon Studios" / "Saves"
    )

# Colony center (from the base save)
COLONY_X, COLONY_Z = 132, 137

# Timing constants — RIMAPI returns from many commands before they've
# actually completed in Unity. These delays give the game engine time to
# finish its work before we issue the next command.
LOAD_SETTLE_SECONDS = 10.0        # after load_game, let map fully populate
BETWEEN_SCENARIOS_SECONDS = 8.0   # between scenario runs (map teardown)
BETWEEN_OPS_SECONDS = 0.3         # small pause between successive spawns
SAVE_WAIT_TIMEOUT = 30.0          # how long to wait for save file to write
SAVE_MIN_SIZE_MB = 5.0            # valid RimWorld save is ~14 MB

# Names for spawned extra colonists
CLONE_NAMES: list[dict[str, str]] = [
    {"first": "Valeska", "nick": "Val", "last": "Kowalski"},
    {"first": "Jin", "nick": "Jin", "last": "Tanaka"},
]

# RimWorld difficulty def names: Easy, Medium, Rough, Hard, VeryHard

# Max stack size per def — spawns above this need to be split into multiple
# calls because RIMAPI can't auto-split and errors with null refs.
MAX_STACK: dict[str, int] = {
    "WoodLog": 75, "Steel": 75, "Plasteel": 75, "Gold": 500,
    "Uranium": 75, "MealSurvivalPack": 10, "MedicineIndustrial": 25,
    "MedicineHerbal": 25, "ComponentIndustrial": 25, "ComponentSpacer": 1,
    "Gun_BoltActionRifle": 1, "Gun_Revolver": 1, "Apparel_FlakVest": 1,
}
DEFAULT_MAX_STACK = 75

# Per-scenario setup recipe. Each scenario is a sequence of API calls.
# `items` entries are (def_name, amount[, stuff_def]) tuples.
# NOTE on "day advancement": the plan (and issue #7) originally called for
# building saves at day 30 / 60 / etc with shelter, food, and research
# progress. RIMAPI does not currently expose an endpoint to fast-forward
# the game clock or complete research instantly, so the saves below remain
# day-0 snapshots with setup additions. `set_research_target(force=True)`
# sets the target but does not complete the project — only queues it.
#
# Once RIMAPI adds a dev-mode tick-advance endpoint, first_winter and
# ship_launch can be advanced via:
#   await client.advance_ticks(N)   # hypothetical, not yet available

SCENARIOS: dict[str, dict[str, Any]] = {
    "rle_first_winter_v1": {
        "difficulty": "Medium",
        "extra_pawns": 0,
        "description": (
            "60-day survival through winter — starts at day 0 (no "
            "advancement endpoint yet, see note above)"
        ),
        "items": [],
        "incidents": [],
        "research_complete": [],
    },
    "rle_toxic_fallout_v1": {
        "difficulty": "Rough",
        "extra_pawns": 1,
        "description": "Survive 20 days of toxic fallout with 4 colonists",
        "items": [
            ("WoodLog", 500),
            ("MealSurvivalPack", 30),
            ("Steel", 200),
        ],
        "incidents": [("ToxicFallout", {})],
        "research_complete": [],
    },
    "rle_raid_defense_v1": {
        "difficulty": "Rough",
        "extra_pawns": 2,
        "description": "Defend against raids for 15 days with 5 colonists",
        "items": [
            ("Gun_BoltActionRifle", 2),
            ("Gun_Revolver", 1),
            ("Apparel_FlakVest", 3),
            ("Steel", 500),
            ("WoodLog", 300),
            ("ComponentIndustrial", 20),
        ],
        "incidents": [],  # Raid itself is triggered at scenario runtime
        "research_complete": [],
    },
    "rle_plague_response_v1": {
        "difficulty": "Rough",
        "extra_pawns": 2,
        "description": "Manage a plague outbreak with 5 colonists over 20 days",
        "items": [
            ("MedicineIndustrial", 30),
            ("MedicineHerbal", 20),
            ("MealSurvivalPack", 40),
        ],
        "incidents": [],  # Plague triggered at scenario runtime
        "research_complete": [],
    },
    "rle_ship_launch_v1": {
        "difficulty": "Hard",
        "extra_pawns": 2,
        "description": "Long-term research push (120 days) with 5 colonists",
        "items": [
            ("Steel", 1000),
            ("ComponentIndustrial", 50),
            ("ComponentSpacer", 10),
            ("Plasteel", 200),
            ("Gold", 50),
            ("Uranium", 100),
        ],
        "incidents": [],
        # Force-complete mid-tier research so the agents have a head start
        "research_complete": [
            "Electricity", "Batteries", "Smithing", "ComplexClothing",
            "StonecuttingTech", "PassiveCooler",
        ],
    },
}


# ---------------------------------------------------------------------------
# Difficulty patching (offline, pure bytes replacement)
# ---------------------------------------------------------------------------

def patch_difficulty_in_file(path: Path, difficulty: str) -> None:
    """Rewrite a save's difficulty tag in-place. Offline operation."""
    base_difficulty = b"<difficulty>Medium</difficulty>"
    data = path.read_bytes()
    new_tag = f"<difficulty>{difficulty}</difficulty>".encode()
    if data.count(base_difficulty) != 1:
        print(
            f"  WARNING: {path.name} has unexpected difficulty tag count "
            f"({data.count(base_difficulty)}), skipping patch",
            file=sys.stderr,
        )
        return
    path.write_bytes(data.replace(base_difficulty, new_tag, 1))


# ---------------------------------------------------------------------------
# Scenario setup (online, via RIMAPI)
# ---------------------------------------------------------------------------

async def _wait_for_game_ready(
    client: RimAPIClient,
    timeout_seconds: float = 60.0,
) -> bool:
    """Wait until game is loaded AND Unity has had time to fully settle.

    RIMAPI returns from load_game() before the map is actually usable.
    Spawning/saving too soon hits null refs. We wait for colonist_count
    then add extra settle time before returning.
    """
    poll_interval = 2.0
    elapsed = 0.0
    while elapsed < timeout_seconds:
        try:
            state = await client._get("/api/v1/game/state")
            if state.get("colonist_count", 0) > 0:
                await asyncio.sleep(LOAD_SETTLE_SECONDS)
                return True
        except Exception:
            pass
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    return False


async def _wait_for_save_written(
    path: Path,
    timeout_seconds: float = SAVE_WAIT_TIMEOUT,
) -> bool:
    """Poll the save file until size stabilizes above the min threshold.

    RIMAPI's save_game() returns before the file is flushed. Without
    polling, we see partial writes (67 KB - 1.4 MB for files that should
    be ~14 MB). Returns True once the file reaches SAVE_MIN_SIZE_MB and
    its size is unchanged across two consecutive polls.
    """
    poll_interval = 1.0
    elapsed = 0.0
    last_size = -1
    stable_polls = 0
    min_size = int(SAVE_MIN_SIZE_MB * 1024 * 1024)
    while elapsed < timeout_seconds:
        if path.exists():
            size = path.stat().st_size
            if size >= min_size and size == last_size:
                stable_polls += 1
                if stable_polls >= 2:
                    return True
            else:
                stable_polls = 0
            last_size = size
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    return False


async def _spawn_items(
    client: RimAPIClient,
    items: list[tuple[str, int]],
    center: tuple[int, int] = (COLONY_X, COLONY_Z),
) -> int:
    """Spawn items near the colony center, splitting into max-stack chunks.

    RIMAPI can't auto-split stacks — spawning amount > max_stack triggers
    a null reference that destabilizes the game. We split into chunks of
    MAX_STACK[def_name] each. Returns count of successful spawn calls.
    """
    spawned = 0
    cx, cz = center
    x_offset, z_offset = -2, -2
    for def_name, total in items:
        max_stack = MAX_STACK.get(def_name, DEFAULT_MAX_STACK)
        remaining = total
        while remaining > 0:
            chunk = min(remaining, max_stack)
            try:
                await client.spawn_item(
                    def_name=def_name,
                    x=cx + x_offset,
                    z=cz + z_offset,
                    amount=chunk,
                )
                spawned += 1
                await asyncio.sleep(BETWEEN_OPS_SECONDS)
                # Shift position so items don't all pile on one cell
                x_offset += 1
                if x_offset > 2:
                    x_offset = -2
                    z_offset += 1
            except Exception as e:
                print(f"    failed to spawn {def_name} x{chunk}: {e}")
                break  # Stop trying this def if it fails
            remaining -= chunk
    return spawned


async def _spawn_extra_pawns(
    client: RimAPIClient,
    count: int,
    center: tuple[int, int] = (COLONY_X, COLONY_Z),
) -> int:
    """Spawn extra colonists at offsets from colony center."""
    spawned = 0
    cx, cz = center
    for i in range(count):
        name = CLONE_NAMES[i]
        try:
            await client.spawn_pawn(
                pawn_kind="Colonist",
                faction="PlayerColony",
                first_name=name["first"],
                last_name=name["last"],
                nickname=name["nick"],
                x=cx + 2 + i * 2,
                z=cz + 2,
            )
            spawned += 1
            await asyncio.sleep(BETWEEN_OPS_SECONDS)
        except Exception as e:
            print(f"    failed to spawn pawn {name['nick']}: {e}")
    return spawned


async def _trigger_incidents(
    client: RimAPIClient,
    incidents: list[tuple[str, dict[str, Any]]],
) -> int:
    """Fire setup-phase incidents. Returns count triggered."""
    triggered = 0
    for name, parms in incidents:
        try:
            await client.trigger_incident(name, **parms)
            triggered += 1
        except Exception as e:
            print(f"    failed to trigger {name}: {e}")
    return triggered


async def _complete_research(
    client: RimAPIClient, projects: list[str],
) -> int:
    """Force-complete research projects by setting target with force=True.

    NOTE: This sets the target; the game still needs to tick for
    completion. Repeated calls with different targets will advance
    through them. For true instant completion we'd need a dev endpoint.
    """
    count = 0
    for project in projects:
        try:
            await client.set_research_target(project, force=True)
            count += 1
        except Exception as e:
            print(f"    failed to set research {project}: {e}")
    return count


async def build_scenario_save(
    client: RimAPIClient,
    save_name: str,
    config: dict[str, Any],
    rimworld_save_dir: Path,
) -> bool:
    """Load the base save, apply setup, and save as `save_name`.

    Returns True on success.
    """
    difficulty = str(config["difficulty"])
    items = list(config.get("items", []))
    incidents = list(config.get("incidents", []))
    extra_pawns = int(config.get("extra_pawns", 0))
    research = list(config.get("research_complete", []))

    print(f"\n  {save_name}:")
    print(f"    difficulty={difficulty}, +{extra_pawns} pawns, "
          f"{len(items)} item types, {len(incidents)} incidents, "
          f"{len(research)} research")

    # 1. Load base save
    try:
        await client.load_game(BASE_SAVE)
    except Exception as e:
        print(f"    ERROR: could not load base save: {e}")
        return False

    if not await _wait_for_game_ready(client):
        print("    ERROR: game did not become ready after load")
        return False

    # Unpause so RIMAPI processes queued requests
    await client.unpause_game(speed=1)

    # Compute colony center from live colonist positions so we aren't
    # coupled to hardcoded coords if the base save is ever regenerated.
    center = await _compute_colony_center(client)
    if center != (COLONY_X, COLONY_Z):
        print(f"    colony center from live positions: {center}")

    # 2. Spawn items
    if items:
        count = await _spawn_items(client, items, center)
        print(f"    spawned {count}/{len(items)} item stacks")

    # 3. Spawn extra colonists
    if extra_pawns:
        count = await _spawn_extra_pawns(client, extra_pawns, center)
        print(f"    spawned {count}/{extra_pawns} extra pawns")

    # 4. Complete research (sequential target setting with force=True)
    if research:
        count = await _complete_research(client, research)
        print(f"    set {count}/{len(research)} research targets")

    # 5. Trigger setup-phase incidents (fallout, etc.)
    if incidents:
        count = await _trigger_incidents(client, incidents)
        print(f"    triggered {count}/{len(incidents)} incidents")

    # 6. Pause and save
    try:
        await client.pause_game()
    except Exception as e:
        print(f"    WARNING: pause failed (continuing to save anyway): {e}")

    try:
        await client.save_game(save_name)
    except Exception as e:
        print(f"    ERROR: save_game call failed: {e}")
        return False

    # 7. Wait for file to be fully written — save_game() returns async
    source_path = rimworld_save_dir / f"{save_name}.rws"
    if not await _wait_for_save_written(source_path):
        raw_size = (
            source_path.stat().st_size if source_path.exists() else 0
        )
        size_kb = raw_size / 1024
        print(
            f"    WARNING: save did not reach {SAVE_MIN_SIZE_MB} MB within "
            f"{SAVE_WAIT_TIMEOUT}s (current: {size_kb:.0f} KB) — skipping mirror"
        )
        return False

    # 8. Patch difficulty and mirror to docker/saves/
    patch_difficulty_in_file(source_path, difficulty)
    DOCKER_SAVES_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = DOCKER_SAVES_DIR / f"{save_name}.rws"
    shutil.copy2(source_path, dest_path)
    size_mb = dest_path.stat().st_size / (1024 * 1024)
    print(f"    wrote {source_path} ({size_mb:.1f} MB)")
    print(f"    mirrored to {dest_path}")

    return True


async def _check_rimapi_alive(client: RimAPIClient) -> bool:
    """Probe RIMAPI to see if the game is still responsive."""
    return await client.ping()


async def _compute_colony_center(
    client: RimAPIClient,
    fallback: tuple[int, int] = (COLONY_X, COLONY_Z),
) -> tuple[int, int]:
    """Centroid of live colonist positions. Falls back to hardcoded coords
    if the colonist list is empty or unreachable.

    This protects against silent breakage when the base save is
    regenerated with a different starting location.
    """
    try:
        colonists = await client.get_colonists()
        if not colonists:
            return fallback
        cx = sum(c.position[0] for c in colonists) // len(colonists)
        cz = sum(c.position[1] for c in colonists) // len(colonists)
        return cx, cz
    except Exception:
        return fallback


async def run_all(
    rimapi_url: str,
    rimworld_save_dir: Path,
    only: str | None = None,
) -> int:
    """Build all (or one) scenario save. Returns number built successfully."""
    built = 0
    first = True
    async with RimAPIClient(rimapi_url) as client:
        for save_name, config in SCENARIOS.items():
            if only and only not in save_name:
                continue

            # Abort early if RIMAPI stopped responding (likely game crash)
            if not await _check_rimapi_alive(client):
                print(
                    "\n  SKIPPING remaining scenarios: RIMAPI unresponsive "
                    "(game may have crashed). Restart RimWorld to continue.",
                    file=sys.stderr,
                )
                break

            # Pause between scenarios — gives the previous map time to
            # tear down fully before we load the next one.
            if not first:
                print(
                    f"\n  (waiting {BETWEEN_SCENARIOS_SECONDS}s before next "
                    f"scenario...)"
                )
                await asyncio.sleep(BETWEEN_SCENARIOS_SECONDS)
            first = False

            try:
                ok = await build_scenario_save(
                    client, save_name, config, rimworld_save_dir,
                )
                if ok:
                    built += 1
            except Exception as e:
                print(f"    ERROR: {save_name} failed with exception: {e}")
                await asyncio.sleep(2.0)
    return built


def difficulty_only() -> None:
    """Patch difficulty on existing docker/saves/ without touching the game."""
    base_path = DOCKER_SAVES_DIR / f"{BASE_SAVE}.rws"
    if not base_path.exists():
        print(f"ERROR: Base save not found: {base_path}", file=sys.stderr)
        sys.exit(1)

    base_data = base_path.read_bytes()
    for save_name, config in SCENARIOS.items():
        out_path = DOCKER_SAVES_DIR / f"{save_name}.rws"
        if not out_path.exists():
            out_path.write_bytes(base_data)
        patch_difficulty_in_file(out_path, str(config["difficulty"]))
        size_mb = out_path.stat().st_size / (1024 * 1024)
        print(f"  {save_name}.rws  ({size_mb:.1f} MB)  "
              f"difficulty={config['difficulty']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create scenario save files via RIMAPI.",
    )
    parser.add_argument(
        "--rimapi-url",
        default="http://localhost:8765",
        help="RIMAPI base URL (default: http://localhost:8765)",
    )
    parser.add_argument(
        "--save-dir",
        default=None,
        help=(
            "RimWorld save directory (default: OS-specific RimWorld path). "
            "RIMAPI writes save files here; we copy them to docker/saves/."
        ),
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Only build scenarios matching this substring (e.g. 'first_winter')",
    )
    parser.add_argument(
        "--difficulty-only",
        action="store_true",
        help="Skip RIMAPI — patch difficulty bytes on existing docker/saves files",
    )
    args = parser.parse_args()

    if args.difficulty_only:
        print("Patching difficulty only (offline)...\n")
        difficulty_only()
        return

    save_dir = (
        Path(args.save_dir) if args.save_dir
        else _default_rimworld_save_dir()
    )
    if not save_dir.exists():
        print(
            f"ERROR: RimWorld save dir does not exist: {save_dir}\n"
            "Use --save-dir to specify the correct location.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Creating scenario saves via RIMAPI...")
    print(f"  rimapi_url = {args.rimapi_url}")
    print(f"  save_dir   = {save_dir}")
    print(f"  mirror_to  = {DOCKER_SAVES_DIR}")
    if args.only:
        print(f"  only       = {args.only}")
    print()

    built = asyncio.run(run_all(args.rimapi_url, save_dir, only=args.only))
    print(f"\nBuilt {built} scenario saves.")


if __name__ == "__main__":
    main()
