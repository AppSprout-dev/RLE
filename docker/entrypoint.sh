#!/bin/bash
set -e

# Clean stale X11 locks
rm -f /tmp/.X99-lock /tmp/.X11-unix/X99

# Start Xvfb
Xvfb :99 -screen 0 1280x720x24 -ac +extension GLX &
XVFB_PID=$!

# Wait for X socket
ELAPSED=0
while [ ! -e /tmp/.X11-unix/X99 ]; do
    sleep 0.5
    ELAPSED=$((ELAPSED + 1))
    if [ "$ELAPSED" -ge 60 ]; then
        echo "ERROR: Xvfb failed to start within 30s"
        exit 1
    fi
done
echo "Xvfb ready on :99"

# DBus machine-id (prevents Unity startup crash)
dbus-uuidgen --ensure 2>/dev/null || true

# Pre-seed RIMAPI config: bind to 0.0.0.0 instead of localhost (IPv6 loopback)
# so Docker port forwarding can reach the server from the host.
CONFIG_DIR="$HOME/.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config"
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/Mod_RedEyeDev.RIMAPI_Settings.xml" ]; then
    cat > "$CONFIG_DIR/Mod_RedEyeDev.RIMAPI_Settings.xml" << 'XMLEOF'
<?xml version="1.0" encoding="utf-8"?>
<Mod_RedEyeDev.RIMAPI_Settings>
  <serverIP>0.0.0.0</serverIP>
  <serverPort>8765</serverPort>
</Mod_RedEyeDev.RIMAPI_Settings>
XMLEOF
fi

# Link save files into RimWorld saves directory
SAVES_DIR="$HOME/.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Saves"
mkdir -p "$SAVES_DIR"
if [ -d /opt/saves ]; then
    for f in /opt/saves/*; do
        [ -e "$f" ] && ln -sf "$f" "$SAVES_DIR/$(basename "$f")"
    done
fi

# Link mods into a writable overlay (game dir is mounted :ro)
MODS_DIR="/opt/mods-merged"
mkdir -p "$MODS_DIR"
# Copy game's built-in mods (read-only source)
if [ -d /opt/game/Mods ]; then
    for mod in /opt/game/Mods/*/; do
        [ -d "$mod" ] && ln -sf "$mod" "$MODS_DIR/$(basename "$mod")"
    done
fi
# Link our additional mods on top
for mod_dir in /opt/mods/*/; do
    [ -d "$mod_dir" ] && ln -sf "$mod_dir" "$MODS_DIR/$(basename "$mod_dir")"
done

# Launch RimWorld
echo "Starting RimWorld headless..."
/opt/game/RimWorldLinux \
    -batchmode \
    -nographics \
    -noshaders \
    -force-opengl \
    -startServer \
    -logFile /tmp/rimworld_log.txt &
GAME_PID=$!

# Wait for RIMAPI to become responsive
echo "Waiting for RIMAPI on :8765..."
ELAPSED=0
while ! curl -sf http://localhost:8765/api/v1/game/state > /dev/null 2>&1; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ "$ELAPSED" -ge 120 ]; then
        echo "ERROR: RIMAPI not responsive after 120s"
        tail -30 /tmp/rimworld_log.txt 2>/dev/null
        exit 1
    fi
done
echo "RIMAPI ready"

# Keep container alive
tail -f /tmp/rimworld_log.txt
