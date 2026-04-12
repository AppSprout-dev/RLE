"""Create scenario save files from the crashlanded base save.

Phase A (offline, no game needed):
  Copies rle_crashlanded_v1.rws and patches the difficulty XML field for each
  scenario. Preserves UTF-8 BOM and CRLF line endings.

Phase B (requires RimWorld + dev mode):
  Prints a per-scenario checklist of manual steps (spawn pawns, items) to
  complete in dev mode, then re-save.

Usage:
  python scripts/create_scenario_saves.py --phase a          # generate saves
  python scripts/create_scenario_saves.py --phase b          # print checklist
  python scripts/create_scenario_saves.py --phase a --phase b  # both
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SAVES_DIR = Path(__file__).resolve().parent.parent / "docker" / "saves"
BASE_SAVE = "rle_crashlanded_v1"

# RimWorld difficulty defs:
#   Easy (Community Builder), Medium (Adventure Story),
#   Rough (Strive to Survive), Hard (Blood and Dust),
#   VeryHard (Losing is Fun)

SCENARIOS: dict[str, dict[str, object]] = {
    "rle_first_winter_v1": {
        "difficulty": "Medium",
        "target_pop": 3,
        "description": "60-day survival through winter — same colony start, longer duration",
    },
    "rle_toxic_fallout_v1": {
        "difficulty": "Rough",
        "target_pop": 4,
        "description": "Survive 20 days of toxic fallout with 4 colonists",
    },
    "rle_raid_defense_v1": {
        "difficulty": "Rough",
        "target_pop": 5,
        "description": "Defend against raids for 15 days with 5 colonists",
    },
    "rle_plague_response_v1": {
        "difficulty": "Rough",
        "target_pop": 5,
        "description": "Manage a plague outbreak with 5 colonists over 20 days",
    },
    "rle_ship_launch_v1": {
        "difficulty": "Hard",
        "target_pop": 5,
        "description": "Long-term research push (120 days) with 5 colonists",
    },
}

# Phase B: manual dev-mode checklist per scenario
PHASE_B_CHECKLISTS: dict[str, list[str]] = {
    "rle_first_winter_v1": [
        "No extra setup needed — same 3 colonists as crashlanded.",
        "The winter challenge comes from the 60-day duration and food_days victory condition.",
    ],
    "rle_toxic_fallout_v1": [
        "Spawn 1 additional colonist (Dev Tools > Spawn pawn > Colonist)",
        "Spawn items near colony center:",
        "  - WoodLog x500",
        "  - MealSurvivalPack x30",
        "  - Steel x200",
        "Save as 'rle_toxic_fallout_v1' (overwrite Phase A save)",
    ],
    "rle_raid_defense_v1": [
        "Spawn 2 additional colonists (Dev Tools > Spawn pawn > Colonist)",
        "Spawn items near colony center:",
        "  - Gun_BoltActionRifle x2",
        "  - Gun_Revolver x1",
        "  - Apparel_FlakVest x3",
        "  - Steel x500",
        "  - WoodLog x300",
        "  - ComponentIndustrial x20",
        "Save as 'rle_raid_defense_v1' (overwrite Phase A save)",
    ],
    "rle_plague_response_v1": [
        "Spawn 2 additional colonists (Dev Tools > Spawn pawn > Colonist)",
        "Spawn items near colony center:",
        "  - MedicineIndustrial x30",
        "  - MedicineHerbal x20",
        "  - MealSurvivalPack x40",
        "Save as 'rle_plague_response_v1' (overwrite Phase A save)",
    ],
    "rle_ship_launch_v1": [
        "Spawn 2 additional colonists (Dev Tools > Spawn pawn > Colonist)",
        "Spawn items near colony center:",
        "  - Steel x1000",
        "  - ComponentIndustrial x50",
        "  - ComponentSpacer x10",
        "  - Plasteel x200",
        "  - Gold x50",
        "  - Uranium x100",
        "Save as 'rle_ship_launch_v1' (overwrite Phase A save)",
    ],
}


def phase_a() -> None:
    """Copy base save and patch difficulty for each scenario."""
    base_path = SAVES_DIR / f"{BASE_SAVE}.rws"
    if not base_path.exists():
        print(f"ERROR: Base save not found: {base_path}", file=sys.stderr)
        sys.exit(1)

    base_data = base_path.read_bytes()

    # The base save has <difficulty>Medium</difficulty> at line 405.
    # We do byte-level replacement to preserve BOM, CRLF, and all formatting.
    base_difficulty = b"<difficulty>Medium</difficulty>"
    if base_data.count(base_difficulty) != 1:
        print(
            f"ERROR: Expected exactly 1 occurrence of {base_difficulty!r} in base save, "
            f"found {base_data.count(base_difficulty)}",
            file=sys.stderr,
        )
        sys.exit(1)

    for save_name, config in SCENARIOS.items():
        target_difficulty = str(config["difficulty"]).encode()
        new_tag = b"<difficulty>" + target_difficulty + b"</difficulty>"
        patched = base_data.replace(base_difficulty, new_tag, 1)

        out_path = SAVES_DIR / f"{save_name}.rws"
        out_path.write_bytes(patched)

        size_mb = out_path.stat().st_size / (1024 * 1024)
        print(f"  {save_name}.rws  ({size_mb:.1f} MB)  difficulty={config['difficulty']}")

    print(f"\nPhase A complete: {len(SCENARIOS)} saves written to {SAVES_DIR}")


def phase_b() -> None:
    """Print per-scenario manual dev-mode checklists."""
    print("=" * 60)
    print("Phase B: Manual Dev Mode Setup")
    print("=" * 60)
    print()
    print("Load each save in RimWorld with dev mode enabled.")
    print("Follow the checklist, then save (overwriting the Phase A file).")
    print()

    for save_name, steps in PHASE_B_CHECKLISTS.items():
        config = SCENARIOS[save_name]
        print(f"--- {save_name} ---")
        print(f"    {config['description']}")
        print(f"    Target population: {config['target_pop']} colonists")
        print()
        for step in steps:
            print(f"    {step}")
        print()

    print("After completing all scenarios, copy the final .rws files back to")
    print(f"  {SAVES_DIR}")
    print("and commit them. They become the frozen benchmark starting states.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create scenario save files from the crashlanded base save.",
    )
    parser.add_argument(
        "--phase",
        action="append",
        choices=["a", "b"],
        required=True,
        help="Phase(s) to run: 'a' = XML patch, 'b' = print manual checklist",
    )
    args = parser.parse_args()
    phases: list[str] = args.phase

    if "a" in phases:
        print("Phase A: Generating scenario saves...\n")
        phase_a()
        print()

    if "b" in phases:
        phase_b()


if __name__ == "__main__":
    main()
