"""Mirror the most-recently-updated per-model latest_tick.json up to the watch
root, so a single dashboard tick server (serve_dashboard.py on :9000) follows
whichever model is currently running in a spread.

    python scripts/mirror_latest_tick.py results/spread

Runs until killed. Pairs with run_spread_n1.sh (per-model output dirs) and the
OBS score ticker (obs_studio.py overlay), which use the same discovery logic.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "results/spread")
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "latest_tick.json"
    print(f"mirroring newest {root}/*/latest_tick.json -> {dest} (ctrl-c to stop)")
    last_src: Path | None = None
    last_mtime = 0.0
    while True:
        candidates = list(root.glob("*/latest_tick.json"))
        if candidates:
            newest = max(candidates, key=lambda p: p.stat().st_mtime)
            mtime = newest.stat().st_mtime
            if newest != last_src or mtime != last_mtime:
                try:
                    shutil.copyfile(newest, dest)
                    if newest != last_src:
                        print(f"now following {newest.parent.name}")
                    last_src, last_mtime = newest, mtime
                except OSError:
                    pass  # mid-write; retry next cycle
        time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
