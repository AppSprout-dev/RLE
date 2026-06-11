#!/usr/bin/env bash
# During-run media capture loop. Start BEFORE launching the run/spread, stop after.
#  - every FRAME_INTERVAL s: one PNG still of the RimWorld window (timestamp-named —
#    doubles as a wall-clock index into the OBS recording)
#  - every POLL_INTERVAL s: snapshot each model's latest_tick.json when it changes
#    (dashboard replay source; the run only keeps the latest tick otherwise)
#
# Usage:
#   bash scripts/capture_run_media.sh <results_dir> <frames_out_dir>
# Env overrides: FFMPEG (path to ffmpeg.exe), WINDOW_TITLE, FRAME_INTERVAL, POLL_INTERVAL
set -u
RESULTS_DIR="${1:?usage: capture_run_media.sh <results_dir> <frames_out_dir>}"
FRAMES_DIR="${2:?usage: capture_run_media.sh <results_dir> <frames_out_dir>}"
FFMPEG="${FFMPEG:-ffmpeg}"
WINDOW_TITLE="${WINDOW_TITLE:-RimWorld by Ludeon Studios}"
FRAME_INTERVAL="${FRAME_INTERVAL:-10}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"

mkdir -p "$FRAMES_DIR"
echo "capturing: window '$WINDOW_TITLE' every ${FRAME_INTERVAL}s -> $FRAMES_DIR"
echo "snapshots: $RESULTS_DIR/*/latest_tick.json every ${POLL_INTERVAL}s"

last_frame=0
while true; do
  now=$(date +%s)
  if [ $((now - last_frame)) -ge "$FRAME_INTERVAL" ]; then
    ts=$(date +%Y%m%d_%H%M%S)
    "$FFMPEG" -y -loglevel quiet -f gdigrab -framerate 1 -i "title=$WINDOW_TITLE" \
      -frames:v 1 "$FRAMES_DIR/frame_$ts.png" 2>/dev/null
    last_frame=$now
  fi
  for d in "$RESULTS_DIR"/*/; do
    f="$d/latest_tick.json"
    [ -f "$f" ] || continue
    h=$(md5sum "$f" | cut -d' ' -f1)
    snap="$d/tick_snapshots"
    mkdir -p "$snap"
    last=""
    [ -f "$snap/.last" ] && last=$(cat "$snap/.last")
    if [ "$last" != "$h" ]; then
      cp "$f" "$snap/snap_$(date +%s)_$h.json"
      echo "$h" > "$snap/.last"
    fi
  done
  sleep "$POLL_INTERVAL"
done
