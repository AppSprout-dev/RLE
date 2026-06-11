"""Replay a spread model's tick snapshots into a directory served by
serve_dashboard.py, so the React dashboard animates the run for screen recording.

Usage:
  python replay_ticks.py --model fable5 [--interval 2.0] [--loop]
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path


def snap_sort_key(p: Path) -> int:
    try:
        return int(json.loads(p.read_text(encoding="utf-8")).get("tick", 0))
    except (json.JSONDecodeError, OSError):
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True, help="model dir name under --spread-dir")
    ap.add_argument("--spread-dir", default=r"c:\Users\redmo\Projects\RLE\results\spread")
    ap.add_argument("--replay-dir", default=r"c:\Users\redmo\Projects\RLE\results\replay")
    ap.add_argument("--interval", type=float, default=2.0, help="seconds per tick")
    ap.add_argument("--loop", action="store_true", help="repeat forever")
    args = ap.parse_args()

    snaps_dir = Path(args.spread_dir) / args.model / "tick_snapshots"
    snaps = sorted(snaps_dir.glob("snap_*.json"), key=snap_sort_key)
    if not snaps:
        raise SystemExit(f"no snapshots in {snaps_dir}")
    out = Path(args.replay_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "latest_tick.json"

    print(f"replaying {len(snaps)} ticks of {args.model} -> {target} "
          f"@ {args.interval}s/tick{' (loop)' if args.loop else ''}")
    while True:
        for s in snaps:
            shutil.copyfile(s, target)
            tick = json.loads(s.read_text(encoding="utf-8")).get("tick")
            print(f"  tick {tick}")
            time.sleep(args.interval)
        if not args.loop:
            break


if __name__ == "__main__":
    main()
