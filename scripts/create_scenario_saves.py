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
import sys
from pathlib import Path
from typing import Any

from rle.rimapi.client import RimAPIClient

SAVES_DIR = Path(__file__).resolve().parent.parent / "docker" / "saves"
BASE_SAVE = "rle_crashlanded_v1"

# Colony center (from the base save)
COLONY_X, COLONY_Z = 132, 137

# Names for spawned extra colonists
CLONE_NAMES: list[dict[str, str]] = [
    {"first": "Valeska", "nick": "Val", "last": "Kowalski"},
    {"first": "Jin", "nick": "Jin", "last": "Tanaka"},
]

# RimWorld difficulty def names: Easy, Medium, Rough, Hard, VeryHard

# Per-scenario setup recipe. Each scenario is a sequence of API calls.
# `items` entries are (def_name, amount[, stuff_def]) tuples.
SCENARIOS: dict[str, dict[str, Any]] = {
    "rle_first_winter_v1": {
        "difficulty": "Medium",
        "extra_pawns": 0,
        "description": "60-day survival through winter — same start, longer duration",
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
    """Poll /api/v1/game/state until colonist_count > 0 or timeout."""
    poll_interval = 2.0
    elapsed = 0.0
    while elapsed < timeout_seconds:
        try:
            state = await client._get("/api/v1/game/state")
            if state.get("colonist_count", 0) > 0:
                return True
        except Exception:
            pass
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    return False


async def _spawn_items(
    client: RimAPIClient, items: list[tuple[str, int]],
) -> int:
    """Spawn items near the colony center. Returns count spawned."""
    spawned = 0
    # Spawn in a small grid near colony (avoid stacking all at same cell)
    x_offset, z_offset = -2, -2
    for def_name, amount in items:
        try:
            await client.spawn_item(
                def_name=def_name,
                x=COLONY_X + x_offset,
                z=COLONY_Z + z_offset,
                amount=amount,
            )
            spawned += 1
            # Shift position so items don't all pile on one cell
            x_offset += 1
            if x_offset > 2:
                x_offset = -2
                z_offset += 1
        except Exception as e:
            print(f"    failed to spawn {def_name} x{amount}: {e}")
    return spawned


async def _spawn_extra_pawns(
    client: RimAPIClient, count: int,
) -> int:
    """Spawn extra colonists at offsets from colony center."""
    spawned = 0
    for i in range(count):
        name = CLONE_NAMES[i]
        try:
            await client.spawn_pawn(
                pawn_kind="Colonist",
                faction="PlayerColony",
                first_name=name["first"],
                last_name=name["last"],
                nickname=name["nick"],
                x=COLONY_X + 2 + i * 2,
                z=COLONY_Z + 2,
            )
            spawned += 1
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

    # 2. Spawn items
    if items:
        count = await _spawn_items(client, items)
        print(f"    spawned {count}/{len(items)} item stacks")

    # 3. Spawn extra colonists
    if extra_pawns:
        count = await _spawn_extra_pawns(client, extra_pawns)
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
    await client.pause_game()
    try:
        await client.save_game(save_name)
    except Exception as e:
        print(f"    ERROR: save failed: {e}")
        return False

    # 7. Patch difficulty offline (game saves whatever it loaded with)
    save_path = SAVES_DIR / f"{save_name}.rws"
    if save_path.exists():
        patch_difficulty_in_file(save_path, difficulty)
        size_mb = save_path.stat().st_size / (1024 * 1024)
        print(f"    wrote {save_path.name} ({size_mb:.1f} MB)")
    else:
        print(f"    WARNING: expected save at {save_path} not found")

    return True


async def run_all(
    rimapi_url: str,
    only: str | None = None,
) -> int:
    """Build all (or one) scenario save. Returns number built successfully."""
    built = 0
    async with RimAPIClient(rimapi_url) as client:
        for save_name, config in SCENARIOS.items():
            if only and only not in save_name:
                continue
            ok = await build_scenario_save(client, save_name, config)
            if ok:
                built += 1
    return built


def difficulty_only() -> None:
    """Patch difficulty on existing saves without touching the game."""
    base_path = SAVES_DIR / f"{BASE_SAVE}.rws"
    if not base_path.exists():
        print(f"ERROR: Base save not found: {base_path}", file=sys.stderr)
        sys.exit(1)

    base_data = base_path.read_bytes()
    for save_name, config in SCENARIOS.items():
        out_path = SAVES_DIR / f"{save_name}.rws"
        if not out_path.exists():
            # Seed from base save
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
        "--only",
        default=None,
        help="Only build scenarios matching this substring (e.g. 'first_winter')",
    )
    parser.add_argument(
        "--difficulty-only",
        action="store_true",
        help="Skip RIMAPI — patch difficulty bytes on existing save files",
    )
    args = parser.parse_args()

    if args.difficulty_only:
        print("Patching difficulty only (offline)...\n")
        difficulty_only()
        return

    print("Creating scenario saves via RIMAPI...")
    print(f"  rimapi_url = {args.rimapi_url}")
    if args.only:
        print(f"  only = {args.only}")
    print()

    built = asyncio.run(run_all(args.rimapi_url, only=args.only))
    print(f"\nBuilt {built} scenario saves.")


if __name__ == "__main__":
    main()
