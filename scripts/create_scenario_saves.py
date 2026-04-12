"""Create scenario save files from the crashlanded base save.

Phase A (offline, no game needed):
  Copies rle_crashlanded_v1.rws and patches the difficulty XML field.

Phase B (offline, no game needed):
  Clones colonist pawns and inserts items via XML manipulation.
  Superset of Phase A — applies difficulty + pawns + items in one pass.

Usage:
  python scripts/create_scenario_saves.py --phase a            # difficulty only
  python scripts/create_scenario_saves.py --phase b            # full saves
  python scripts/create_scenario_saves.py --phase a --phase b  # same as just b
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

SAVES_DIR = Path(__file__).resolve().parent.parent / "docker" / "saves"
BASE_SAVE = "rle_crashlanded_v1"

# Source pawn to clone (Bobby "Bob" Triebl)
SOURCE_PAWN_ID = 184
SOURCE_APPAREL_IDS = [185, 186]  # CollarShirt, Pants (worn by source pawn)

# Colony center from the base save
COLONY_X, COLONY_Z = 132, 137

# Names for cloned colonists
CLONE_NAMES: list[dict[str, str]] = [
    {"first": "Valeska", "nick": "Val", "last": "Kowalski"},
    {"first": "Jin", "nick": "Jin", "last": "Tanaka"},
]

# RimWorld difficulty defs:
#   Easy, Medium, Rough, Hard, VeryHard

SCENARIOS: dict[str, dict[str, object]] = {
    "rle_first_winter_v1": {
        "difficulty": "Medium",
        "target_pop": 3,
        "description": "60-day survival through winter — same colony start, longer duration",
        "items": {},
    },
    "rle_toxic_fallout_v1": {
        "difficulty": "Rough",
        "target_pop": 4,
        "description": "Survive 20 days of toxic fallout with 4 colonists",
        "items": {"WoodLog": 500, "MealSurvivalPack": 30, "Steel": 200},
    },
    "rle_raid_defense_v1": {
        "difficulty": "Rough",
        "target_pop": 5,
        "description": "Defend against raids for 15 days with 5 colonists",
        "items": {
            "Gun_BoltActionRifle": 2,
            "Gun_Revolver": 1,
            "Apparel_FlakVest": 3,
            "Steel": 500,
            "WoodLog": 300,
            "ComponentIndustrial": 20,
        },
    },
    "rle_plague_response_v1": {
        "difficulty": "Rough",
        "target_pop": 5,
        "description": "Manage a plague outbreak with 5 colonists over 20 days",
        "items": {"MedicineIndustrial": 30, "MedicineHerbal": 20, "MealSurvivalPack": 40},
    },
    "rle_ship_launch_v1": {
        "difficulty": "Hard",
        "target_pop": 5,
        "description": "Long-term research push (120 days) with 5 colonists",
        "items": {
            "Steel": 1000,
            "ComponentIndustrial": 50,
            "ComponentSpacer": 10,
            "Plasteel": 200,
            "Gold": 50,
            "Uranium": 100,
        },
    },
}

# RimWorld max stack sizes
MAX_STACK: dict[str, int] = {
    "WoodLog": 75, "Steel": 75, "Plasteel": 75, "Gold": 500,
    "Uranium": 75, "MealSurvivalPack": 10, "MedicineIndustrial": 25,
    "MedicineHerbal": 25, "ComponentIndustrial": 25, "ComponentSpacer": 1,
    "Gun_BoltActionRifle": 1, "Gun_Revolver": 1, "Apparel_FlakVest": 1,
}

# Approximate max HP per item def
ITEM_HEALTH: dict[str, int] = {
    "WoodLog": 65, "Steel": 100, "Plasteel": 200, "Gold": 60,
    "Uranium": 200, "MealSurvivalPack": 50, "MedicineIndustrial": 60,
    "MedicineHerbal": 50, "ComponentIndustrial": 30, "ComponentSpacer": 30,
    "Gun_BoltActionRifle": 100, "Gun_Revolver": 100, "Apparel_FlakVest": 280,
}


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def extract_pawn_block(content: str, pawn_num_id: int) -> tuple[str, int, int]:
    """Extract a pawn's <thing Class="Pawn"> block.

    Returns (block_text, start_pos, end_pos_exclusive).
    """
    id_tag = f"<id>Human{pawn_num_id}</id>"
    id_pos = content.index(id_tag)

    # Walk backward to find the opening <thing Class="Pawn">
    open_tag = '<thing Class="Pawn">'
    start = content.rfind(open_tag, 0, id_pos)
    if start == -1:
        raise ValueError(f"Could not find opening <thing Class='Pawn'> for Human{pawn_num_id}")

    # Determine indentation of the opening tag
    line_start = content.rfind("\n", 0, start) + 1
    indent = content[line_start:start]

    # Find the matching closing </thing> at the same indent level.
    # Pawn blocks contain no nested <thing> elements (apparel uses <li>),
    # so the first indent-matched </thing> after the opening is correct.
    close_tag = f"\r\n{indent}</thing>"
    close_pos = content.index(close_tag, start + len(open_tag))
    end = close_pos + len(close_tag)

    return content[start:end], start, end


def clone_pawn(
    template: str,
    base_thing_id: int,
    clone_index: int,
    load_id_start: int,
) -> tuple[str, int]:
    """Clone a pawn block with new IDs, name, position, and remapped loadIDs.

    Returns (cloned_xml, next_load_id).
    """
    name = CLONE_NAMES[clone_index]
    clone = template

    # -- Replace thing IDs (pawn + worn apparel) --
    pawn_id = base_thing_id
    clone = clone.replace(f"Human{SOURCE_PAWN_ID}", f"Human{pawn_id}")
    # Replace worn apparel thing IDs with new unique IDs.
    # The source pawn (Human184) wears Apparel_CollarShirt185 and Apparel_Pants186.
    clone = clone.replace("Apparel_CollarShirt185", f"Apparel_CollarShirt{base_thing_id + 1}")
    clone = clone.replace("Apparel_Pants186", f"Apparel_Pants{base_thing_id + 2}")

    # -- Replace name --
    clone = re.sub(r"<first>Bobby</first>", f"<first>{name['first']}</first>", clone)
    clone = re.sub(r"<nick>Bob</nick>", f"<nick>{name['nick']}</nick>", clone)
    clone = clone.replace("<last>Triebl</last>", f"<last>{name['last']}</last>")
    clone = clone.replace(
        "<birthLastName>Triebl</birthLastName>",
        f"<birthLastName>{name['last']}</birthLastName>",
    )

    # -- Replace position (offset from colony center) --
    new_x = COLONY_X + 2 + clone_index * 2
    new_z = COLONY_Z + 2
    clone = re.sub(
        r"<pos>\(\d+, 0, \d+\)</pos>",
        f"<pos>({new_x}, 0, {new_z})</pos>",
        clone,
        count=1,
    )

    # -- Clear social direct relations (avoid asymmetric references) --
    clone = re.sub(
        r"<directRelations>.*?</directRelations>",
        "<directRelations />",
        clone,
        flags=re.DOTALL,
        count=1,
    )

    # -- Remap ALL <loadID> values to avoid collisions with originals --
    counter = load_id_start

    def _remap(match: re.Match[str]) -> str:
        nonlocal counter
        result = f"<loadID>{counter}</loadID>"
        counter += 1
        return result

    clone = re.sub(r"<loadID>\d+</loadID>", _remap, clone)

    # -- Update displayOrder for colonist bar --
    clone = re.sub(
        r"<displayOrder>\d+</displayOrder>",
        f"<displayOrder>{4 + clone_index}</displayOrder>",
        clone,
    )

    return clone, counter


def make_item_xml(
    def_name: str,
    thing_id: int,
    x: int,
    z: int,
    stack_count: int,
    indent: str,
) -> str:
    """Generate a <thing> XML block for an item."""
    i = indent
    ii = indent + "\t"
    health = ITEM_HEALTH.get(def_name, 100)
    cls = "Apparel" if def_name.startswith("Apparel_") else "ThingWithComps"

    lines = [
        f'{i}<thing Class="{cls}">',
        f'{ii}<def>{def_name}</def>',
        f'{ii}<id>{def_name}{thing_id}</id>',
        f'{ii}<map>0</map>',
        f'{ii}<pos>({x}, 0, {z})</pos>',
        f'{ii}<health>{health}</health>',
        f'{ii}<stackCount>{stack_count}</stackCount>',
        f'{ii}<questTags IsNull="True" />',
        f'{ii}<spawnedTick>0</spawnedTick>',
        f'{ii}<despawnedTick>-1</despawnedTick>',
        f'{ii}<beenRevealed>True</beenRevealed>',
        f'{ii}<forbidden>False</forbidden>',
    ]
    if def_name.startswith("Meal"):
        lines.append(f'{ii}<ingredients />')
    if def_name.startswith("Apparel_"):
        lines.append(f'{ii}<quality>Normal</quality>')
        lines.append(f'{ii}<sourcePrecept>null</sourcePrecept>')
        lines.append(f'{ii}<everSeenByPlayer>True</everSeenByPlayer>')
    lines.extend([
        f'{ii}<verbTracker>',
        f'{ii}\t<verbs IsNull="True" />',
        f'{ii}</verbTracker>',
        f'{i}</thing>',
    ])
    return "\r\n".join(lines)


# ---------------------------------------------------------------------------
# Phase A — difficulty patch only
# ---------------------------------------------------------------------------

def phase_a() -> None:
    """Copy base save and patch difficulty for each scenario."""
    base_path = SAVES_DIR / f"{BASE_SAVE}.rws"
    if not base_path.exists():
        print(f"ERROR: Base save not found: {base_path}", file=sys.stderr)
        sys.exit(1)

    base_data = base_path.read_bytes()
    base_difficulty = b"<difficulty>Medium</difficulty>"
    if base_data.count(base_difficulty) != 1:
        print(
            f"ERROR: Expected exactly 1 occurrence of {base_difficulty!r}, "
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


# ---------------------------------------------------------------------------
# Phase B — full save creation (difficulty + pawns + items)
# ---------------------------------------------------------------------------

def phase_b() -> None:
    """Create full scenario saves with cloned colonists and spawned items."""
    base_path = SAVES_DIR / f"{BASE_SAVE}.rws"
    if not base_path.exists():
        print(f"ERROR: Base save not found: {base_path}", file=sys.stderr)
        sys.exit(1)

    # Read base save (strip BOM on decode, preserve \r\n)
    base_bytes = base_path.read_bytes()
    base_content = base_bytes.decode("utf-8-sig")

    # Extract the template pawn block (Thing_Human184 = Bobby "Bob" Triebl)
    template_block, _, _ = extract_pawn_block(base_content, SOURCE_PAWN_ID)

    # Detect indentation of things in the map (from the template block)
    # Template starts with tabs followed by <thing
    indent_match = re.match(r"(\t+)<thing", template_block)
    thing_indent = indent_match.group(1) if indent_match else "\t\t\t\t\t\t"

    for save_name, config in SCENARIOS.items():
        content = base_content  # always start from the original base
        difficulty = str(config["difficulty"])
        target_pop = int(str(config["target_pop"]))
        items_config: dict[str, int] = dict(config.get("items", {}))  # type: ignore[arg-type]
        extra_pawns = target_pop - 3

        # -- 1. Patch difficulty --
        content = content.replace(
            "<difficulty>Medium</difficulty>",
            f"<difficulty>{difficulty}</difficulty>",
            1,
        )

        # -- 2. Clone pawns --
        # IDs consumed per pawn: 1 (pawn) + len(SOURCE_APPAREL_IDS) (worn items)
        ids_per_pawn = 1 + len(SOURCE_APPAREL_IDS)
        # Start from the base save's nextThingID
        next_thing_id = 37771
        # loadID counter for hediffs/genes/jobs — start high to avoid collisions
        load_id_counter = 1000

        new_pawn_ids: list[int] = []
        insertion_xml = ""

        for i in range(extra_pawns):
            pawn_base_id = next_thing_id
            new_pawn_ids.append(pawn_base_id)
            next_thing_id += ids_per_pawn

            clone_xml, load_id_counter = clone_pawn(
                template_block, pawn_base_id, i, load_id_counter,
            )
            insertion_xml += "\r\n" + clone_xml

        # -- 3. Create item stacks --
        item_x, item_z = COLONY_X - 2, COLONY_Z - 2
        item_count = 0
        for def_name, total in items_config.items():
            max_stack = MAX_STACK.get(def_name, 75)
            stacks_needed = math.ceil(total / max_stack)
            remaining = total
            for _ in range(stacks_needed):
                stack = min(remaining, max_stack)
                item_xml = make_item_xml(
                    def_name, next_thing_id, item_x, item_z, stack, thing_indent,
                )
                insertion_xml += "\r\n" + item_xml
                next_thing_id += 1
                item_count += 1
                remaining -= stack

        # -- 4. Insert new things into the map's <things> list --
        if insertion_xml:
            # Find the template pawn's end position in the (already-modified) content
            _, _, template_end = extract_pawn_block(content, SOURCE_PAWN_ID)
            content = content[:template_end] + insertion_xml + content[template_end:]

        # -- 5. Add new pawns to startingAndOptionalPawns --
        if new_pawn_ids:
            marker = "\t\t\t</startingAndOptionalPawns>"
            new_entries = "".join(
                f"\r\n\t\t\t\t<li>Thing_Human{pid}</li>" for pid in new_pawn_ids
            )
            content = content.replace(marker, new_entries + "\r\n" + marker, 1)

        # -- 6. Update uniqueIDsManager counters --
        content = re.sub(
            r"<nextThingID>\d+</nextThingID>",
            f"<nextThingID>{next_thing_id}</nextThingID>",
            content, count=1,
        )
        content = re.sub(
            r"<nextHediffID>\d+</nextHediffID>",
            f"<nextHediffID>{load_id_counter}</nextHediffID>",
            content, count=1,
        )
        content = re.sub(
            r"<nextGeneID>\d+</nextGeneID>",
            f"<nextGeneID>{load_id_counter}</nextGeneID>",
            content, count=1,
        )
        content = re.sub(
            r"<nextJobID>\d+</nextJobID>",
            f"<nextJobID>{load_id_counter}</nextJobID>",
            content, count=1,
        )

        # -- 7. Write save (restore UTF-8 BOM) --
        out_path = SAVES_DIR / f"{save_name}.rws"
        out_path.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

        size_mb = out_path.stat().st_size / (1024 * 1024)
        pawn_info = f"{target_pop} colonists"
        if extra_pawns > 0:
            names = ", ".join(CLONE_NAMES[i]["nick"] for i in range(extra_pawns))
            pawn_info += f" (+{extra_pawns}: {names})"
        item_info = f"{item_count} item stacks" if item_count else "no items"
        print(f"  {save_name}.rws  ({size_mb:.1f} MB)")
        print(f"    difficulty={difficulty} | {pawn_info} | {item_info}")

    print(f"\nPhase B complete: {len(SCENARIOS)} saves written to {SAVES_DIR}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create scenario save files from the crashlanded base save.",
    )
    parser.add_argument(
        "--phase",
        action="append",
        choices=["a", "b"],
        required=True,
        help="Phase(s) to run: 'a' = difficulty only, 'b' = full (difficulty + pawns + items)",
    )
    args = parser.parse_args()
    phases: list[str] = args.phase

    if "b" in phases:
        # Phase B is a superset of Phase A
        print("Phase B: Creating full scenario saves (difficulty + pawns + items)...\n")
        phase_b()
    elif "a" in phases:
        print("Phase A: Generating scenario saves (difficulty only)...\n")
        phase_a()


if __name__ == "__main__":
    main()
