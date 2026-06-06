"""Compute SHA-256 of each canonical scenario save and write/update the
corresponding YAML's save_sha256 field.

Run after rebuilding saves via scripts/create_scenario_saves.py to re-pin the
scenarios to the new save bytes. The loader will then enforce hash matches at
run time, surfacing any silent drift between docker/saves/ and what's loaded
in a live RimWorld instance.

Usage:
    python scripts/hash_saves.py             # update all scenario YAMLs
    python scripts/hash_saves.py --print     # print proposed changes, don't write
    python scripts/hash_saves.py --only crashlanded
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from rle.scenarios.loader import canonical_save_path
from rle.scenarios.schema import ScenarioConfig
from rle.tracking.metadata import file_sha256

DEFINITIONS_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "rle" / "scenarios" / "definitions"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pin canonical save SHAs into scenario YAMLs.",
    )
    parser.add_argument(
        "--print", dest="dry_run", action="store_true",
        help="Print proposed changes without writing.",
    )
    parser.add_argument(
        "--only", help="Substring match on YAML filename (e.g. 'crashlanded').",
    )
    args = parser.parse_args()

    rc = 0
    for yaml_path in sorted(DEFINITIONS_DIR.glob("*.yaml")):
        if args.only and args.only not in yaml_path.stem:
            continue

        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        scenario = ScenarioConfig.model_validate(data)

        if not scenario.save_name:
            print(f"[skip] {yaml_path.name}: no save_name set")
            continue

        save_path = canonical_save_path(scenario.save_name)
        actual = file_sha256(save_path)
        if actual is None:
            print(
                f"[miss] {yaml_path.name}: canonical save not found at {save_path}",
            )
            rc = 1
            continue

        prev = data.get("save_sha256")
        if prev == actual:
            print(f"[ok]   {yaml_path.name}: {actual[:16]}…")
            continue

        action = "would set" if args.dry_run else "set"
        print(
            f"[{action}] {yaml_path.name}: "
            f"{prev[:16] + '…' if prev else 'None'} -> {actual[:16]}…",
        )
        if not args.dry_run:
            data["save_sha256"] = actual
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, sort_keys=False)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
