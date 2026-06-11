"""Parse a spread console log into a footage index:
per-model wall-clock ranges, OBS file offsets, per-tick timestamps/scores, warnings.

Usage:
  python build_footage_index.py --log <spread.log> --obs-file <rec.mkv> \
      --obs-start "2026-06-10 20:55:09" --out footage_index.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (\S+) (\w+) (.*)")
MARKER = re.compile(r"^(>>>|<<<) \[(\w+)\](.*)")
TICK = re.compile(r"Tick (\d+) \(day (\d+)\): (\d+) actions, (\d+) executed \| score=([\d.]+)")


def build_index(log_path: str, obs_file: str, obs_start: datetime, msg_limit: int) -> dict:
    def obs_offset(dt: datetime) -> float | None:
        off = (dt - obs_start).total_seconds()
        return round(off, 1) if off >= 0 else None

    models: list[dict] = []
    cur: dict | None = None
    last_ts: datetime | None = None
    awaiting_start = False

    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = MARKER.match(line)
            if m:
                kind, name = m.group(1), m.group(2)
                if kind == ">>>":
                    cur = {"model": name, "start": None, "start_obs_offset_s": None,
                           "end": None, "end_obs_offset_s": None, "status": None,
                           "ticks": [], "warnings": []}
                    models.append(cur)
                    awaiting_start = True
                elif kind == "<<<" and cur is not None:
                    cur["end"] = last_ts.isoformat(sep=" ") if last_ts else None
                    cur["end_obs_offset_s"] = obs_offset(last_ts) if last_ts else None
                    cur["status"] = "OK" if "OK" in m.group(3) else m.group(3).strip()
                    cur = None
                continue
            t = TS.match(line)
            if not t:
                continue
            dt = datetime.strptime(t.group(1), "%Y-%m-%d %H:%M:%S")
            last_ts = dt
            if cur is not None and awaiting_start:
                cur["start"] = dt.isoformat(sep=" ")
                cur["start_obs_offset_s"] = obs_offset(dt)
                awaiting_start = False
            logger, level, msg = t.group(2), t.group(3), t.group(4)
            if cur is None:
                continue
            tk = TICK.search(msg)
            if tk:
                cur["ticks"].append({
                    "tick": int(tk.group(1)),
                    "day": int(tk.group(2)),
                    "actions": int(tk.group(3)),
                    "executed": int(tk.group(4)),
                    "score": float(tk.group(5)),
                    "wall": dt.isoformat(sep=" "),
                    "obs_offset_s": obs_offset(dt),
                })
            elif level in ("WARNING", "ERROR") and "httpx" not in logger:
                cur["warnings"].append({"wall": dt.isoformat(sep=" "), "level": level,
                                        "msg": msg[:msg_limit]})

    return {"obs_file": obs_file, "obs_start": obs_start.isoformat(sep=" "), "models": models}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", required=True, help="spread console log path")
    ap.add_argument("--obs-file", required=True,
                    help="OBS recording path (for reference in output)")
    ap.add_argument("--obs-start", required=True, help="OBS recording start, 'YYYY-MM-DD HH:MM:SS'")
    ap.add_argument("--out", default="footage_index.json", help="output JSON path")
    ap.add_argument("--msg-limit", type=int, default=200, help="warning message truncation length")
    args = ap.parse_args()

    obs_start = datetime.strptime(args.obs_start, "%Y-%m-%d %H:%M:%S")
    out = build_index(args.log, args.obs_file, obs_start, args.msg_limit)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    for m in out["models"]:
        print(f"{m['model']}: ticks={len(m['ticks'])} status={m['status']} "
              f"obs={m['start_obs_offset_s']}-{m['end_obs_offset_s']}s "
              f"warnings={len(m['warnings'])}")
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
