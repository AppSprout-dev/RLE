# /// script
# dependencies = ["obsws-python>=1.7"]
# ///
"""RLE production-studio control for OBS via obs-websocket (v5).

Subcommands:
    setup    Idempotently create the RLE scene collection:
               - "RLE Game"      game capture + score ticker overlay
               - "RLE Dashboard" full-screen dashboard browser source
               - "RLE PiP"       game capture + dashboard picture-in-picture
                                 (bottom-right) + score ticker
               - "RLE Vertical"  narrow (608px) dashboard browser source,
                                 centered — crop to 9:16 in post for phone clips
    scene    Switch the program scene:  obs_studio.py scene "RLE PiP"
    overlay  Watch run output dirs and keep the score ticker text current:
               obs_studio.py overlay --watch results/spread
             Picks the most recently updated */latest_tick.json under --watch;
             the model label is the parent directory name. Runs until killed.

Run via uv: ``uv run scripts/obs_studio.py setup``. The browser sources render
the dashboard inside OBS itself — no visible browser window is needed, so the
desktop stays free while runs record. Requires the React dashboard on :3000
and the tick server on :9000.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import obsws_python as obs

SCENE_GAME = "RLE Game"
SCENE_DASH = "RLE Dashboard"
SCENE_PIP = "RLE PiP"
SCENE_VERTICAL = "RLE Vertical"
GAME_INPUT = "Game Capture"  # pre-existing user source, reused not recreated
DASH_INPUT = "RLE Dashboard Browser"
DASH_VERTICAL_INPUT = "RLE Dashboard Vertical"
OVERLAY_INPUT = "RLE Overlay"
# ?api skips the dashboard's first-run setup screen; ?preset selects the
# built-in capture layouts (both ship in rimapi-dashboard for fresh browser
# profiles like OBS's embedded CEF).
DASHBOARD_URL = (
    "http://localhost:3000/rimapi-dashboard"
    "?api=http%3A%2F%2Flocalhost%3A8765%2Fapi%2Fv1&preset=RLE%20Capture"
)
DASHBOARD_VERTICAL_URL = (
    "http://localhost:3000/rimapi-dashboard"
    "?api=http%3A%2F%2Flocalhost%3A8765%2Fapi%2Fv1&preset=RLE%20Vertical"
)
CANVAS_W, CANVAS_H = 1920, 1080
VERTICAL_W = 608  # 608x1080 is exactly 9:16 on a 1080p canvas


def _password() -> str:
    env = os.environ.get("OBS_WS_PASSWORD")
    if env:
        return env
    cfg = (
        Path(os.environ["APPDATA"])
        / "obs-studio"
        / "plugin_config"
        / "obs-websocket"
        / "config.json"
    )
    data = json.loads(cfg.read_text(encoding="utf-8-sig"))
    password: str = data["server_password"]
    return password


def _client(port: int) -> obs.ReqClient:
    return obs.ReqClient(host="localhost", port=port, password=_password(), timeout=10)


# ---------------------------------------------------------------- setup ----


def _ensure_scene(c: obs.ReqClient, name: str) -> None:
    existing = {s["sceneName"] for s in c.get_scene_list().scenes}
    if name not in existing:
        c.create_scene(name)
        print(f"created scene: {name}")


def _ensure_input(
    c: obs.ReqClient, scene: str, name: str, kind: str, settings: dict[str, Any]
) -> None:
    existing = {i["inputName"] for i in c.get_input_list().inputs}
    if name in existing:
        c.set_input_settings(name, settings, overlay=True)
    else:
        c.create_input(scene, name, kind, settings, True)
        print(f"created input: {name} ({kind})")


def _ensure_item(c: obs.ReqClient, scene: str, source: str) -> int:
    for item in c.get_scene_item_list(scene).scene_items:
        if item["sourceName"] == source:
            return int(item["sceneItemId"])
    item_id: int = c.create_scene_item(scene, source, True).scene_item_id
    print(f"added {source} -> {scene}")
    return item_id


def _place(
    c: obs.ReqClient,
    scene: str,
    item_id: int,
    x: float,
    y: float,
    bounds_w: float | None = None,
    bounds_h: float | None = None,
) -> None:
    transform: dict[str, Any] = {"positionX": x, "positionY": y}
    if bounds_w is not None and bounds_h is not None:
        transform |= {
            "boundsType": "OBS_BOUNDS_SCALE_INNER",
            "boundsAlignment": 0,
            "boundsWidth": bounds_w,
            "boundsHeight": bounds_h,
        }
    c.set_scene_item_transform(scene, item_id, transform)


def _text_kind(c: obs.ReqClient) -> str:
    kinds = c.get_input_kind_list(False).input_kinds
    for kind in ("text_gdiplus_v3", "text_gdiplus_v2", "text_ft2_source_v2"):
        if kind in kinds:
            return kind
    raise RuntimeError(f"no text source kind available, found: {kinds}")


def cmd_setup(c: obs.ReqClient) -> None:
    inputs = {i["inputName"] for i in c.get_input_list().inputs}
    if GAME_INPUT not in inputs:
        print(
            f"warning: no '{GAME_INPUT}' input found — game scenes will be "
            "created without it; add your capture source manually",
            file=sys.stderr,
        )

    browser_settings = {
        "url": DASHBOARD_URL,
        "width": CANVAS_W,
        "height": CANVAS_H,
        # Keep rendering when not in program so scene switches never show a
        # page reload on stream.
        "shutdown": False,
        "restart_when_active": False,
    }
    overlay_settings = {
        "text": "RLE — waiting for tick data",
        "font": {"face": "Consolas", "size": 30, "style": "Bold"},
        "outline": True,
        "outline_size": 2,
        "outline_color": 0xFF000000,
    }

    for scene in (SCENE_GAME, SCENE_DASH, SCENE_PIP, SCENE_VERTICAL):
        _ensure_scene(c, scene)

    _ensure_input(c, SCENE_DASH, DASH_INPUT, "browser_source", browser_settings)
    _ensure_input(
        c,
        SCENE_VERTICAL,
        DASH_VERTICAL_INPUT,
        "browser_source",
        browser_settings | {"width": VERTICAL_W, "url": DASHBOARD_VERTICAL_URL},
    )
    _ensure_input(c, SCENE_GAME, OVERLAY_INPUT, _text_kind(c), overlay_settings)

    # RLE Game: game full-canvas, ticker bottom-left
    if GAME_INPUT in inputs:
        gid = _ensure_item(c, SCENE_GAME, GAME_INPUT)
        _place(c, SCENE_GAME, gid, 0, 0, CANVAS_W, CANVAS_H)
    oid = _ensure_item(c, SCENE_GAME, OVERLAY_INPUT)
    _place(c, SCENE_GAME, oid, 24, CANVAS_H - 60)

    # RLE Dashboard: browser full-canvas
    did = _ensure_item(c, SCENE_DASH, DASH_INPUT)
    _place(c, SCENE_DASH, did, 0, 0, CANVAS_W, CANVAS_H)

    # RLE PiP: game full-canvas, dashboard 30% bottom-right, ticker bottom-left
    if GAME_INPUT in inputs:
        gid = _ensure_item(c, SCENE_PIP, GAME_INPUT)
        _place(c, SCENE_PIP, gid, 0, 0, CANVAS_W, CANVAS_H)
    pip_w, pip_h, margin = 576, 324, 16
    pid = _ensure_item(c, SCENE_PIP, DASH_INPUT)
    _place(
        c,
        SCENE_PIP,
        pid,
        CANVAS_W - pip_w - margin,
        CANVAS_H - pip_h - margin,
        pip_w,
        pip_h,
    )
    oid = _ensure_item(c, SCENE_PIP, OVERLAY_INPUT)
    _place(c, SCENE_PIP, oid, 24, CANVAS_H - 60)

    # RLE Vertical: narrow dashboard centered (crop the 608px band in post)
    vid = _ensure_item(c, SCENE_VERTICAL, DASH_VERTICAL_INPUT)
    _place(c, SCENE_VERTICAL, vid, (CANVAS_W - VERTICAL_W) / 2, 0)

    print("setup complete")


# -------------------------------------------------------------- overlay ----


def _latest_tick_file(watch: Path) -> Path | None:
    candidates = list(watch.glob("*/latest_tick.json"))
    direct = watch / "latest_tick.json"
    if direct.exists():
        candidates.append(direct)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def cmd_overlay(c: obs.ReqClient, watch: Path, interval: float) -> None:
    print(f"watching {watch} (ctrl-c to stop)")
    last_text = ""
    while True:
        tick_file = _latest_tick_file(watch)
        if tick_file is not None:
            try:
                data = json.loads(tick_file.read_text())
                label = tick_file.parent.name
                score = data.get("score") or {}
                composite = score.get("composite")
                score_txt = f"{composite:.3f}" if composite is not None else "—"
                text = (
                    f"{label}  •  tick {data.get('tick', '?')}"
                    f"  •  day {data.get('day', '?')}"
                    f"  •  score {score_txt}"
                    f"  •  {data.get('phase', '')}"
                )
                if text != last_text:
                    c.set_input_settings(OVERLAY_INPUT, {"text": text}, overlay=True)
                    last_text = text
            except (json.JSONDecodeError, OSError):
                pass  # mid-write or transient — retry next cycle
        time.sleep(interval)


# ----------------------------------------------------------------- main ----


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    p_scene = sub.add_parser("scene")
    p_scene.add_argument("name")
    p_overlay = sub.add_parser("overlay")
    p_overlay.add_argument("--watch", default="results/spread", type=Path)
    p_overlay.add_argument("--interval", default=2.0, type=float)
    parser.add_argument("--port", type=int, default=4455)
    args = parser.parse_args()

    c = _client(args.port)

    if args.command == "setup":
        cmd_setup(c)
    elif args.command == "scene":
        c.set_current_program_scene(args.name)
        print(f"program scene -> {args.name}")
    elif args.command == "overlay":
        try:
            cmd_overlay(c, args.watch, args.interval)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
