# /// script
# dependencies = ["obsws-python>=1.7"]
# ///
"""Control OBS recording via obs-websocket (v5) for benchmark run capture.

Usage (run via uv so the dependency resolves without polluting the venv):
    uv run scripts/obs_record.py status
    uv run scripts/obs_record.py start --label fable5
    uv run scripts/obs_record.py stop

The WebSocket password is read from the OBS_WS_PASSWORD env var, falling back
to OBS's own plugin config file. `start --label X` sets the recording filename
to ``rle_<label>_<timestamp>`` so per-model footage is self-identifying.

Requires OBS running with the WebSocket server enabled (Tools > WebSocket
Server Settings, port 4455).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import obsws_python as obs


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument("--label", default="", help="filename label for start")
    parser.add_argument("--port", type=int, default=4455)
    args = parser.parse_args()

    client = obs.ReqClient(
        host="localhost", port=args.port, password=_password(), timeout=10
    )

    status = client.get_record_status()
    if args.command == "status":
        print(f"recording={status.output_active} timecode={status.output_timecode}")
        return 0

    if args.command == "start":
        if status.output_active:
            print("already recording", file=sys.stderr)
            return 1
        if args.label:
            client.set_profile_parameter(
                "Output",
                "FilenameFormatting",
                f"rle_{args.label}_%CCYY-%MM-%DD_%hh-%mm-%ss",
            )
        client.start_record()
        print(f"recording started label={args.label or '(default)'}")
        return 0

    # stop
    if not status.output_active:
        print("not recording", file=sys.stderr)
        return 1
    resp = client.stop_record()
    print(f"recording stopped -> {resp.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
