#!/bin/bash
set -e

export HOME=/home/rimworld

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
  <enableLogging>True</enableLogging>
  <loggingLevel>0</loggingLevel>
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
# Link Workshop mods from SteamCMD download (if present in game volume)
if [ -d /opt/game/steamapps/workshop/content/294100 ]; then
    for mod in /opt/game/steamapps/workshop/content/294100/*/; do
        [ -d "$mod" ] && ln -sf "$mod" "$MODS_DIR/$(basename "$mod")"
    done
fi
# Link our additional mods on top (overrides Workshop versions)
for mod_dir in /opt/mods/*/; do
    [ -d "$mod_dir" ] && ln -sf "$mod_dir" "$MODS_DIR/$(basename "$mod_dir")"
done
echo "Mods available in $MODS_DIR:"
ls "$MODS_DIR"

# Pre-seed ModsConfig.xml to activate required mods
# Load order: Harmony → Core → Royalty → HeadlessRimPatch → RIMAPI
if [ ! -f "$CONFIG_DIR/ModsConfig.xml" ]; then
    cat > "$CONFIG_DIR/ModsConfig.xml" << 'XMLEOF'
<?xml version="1.0" encoding="utf-8"?>
<ModsConfigData>
  <version>1.6</version>
  <activeMods>
    <li>brrainz.harmony</li>
    <li>ludeon.rimworld</li>
    <li>ludeon.rimworld.royalty</li>
    <li>RedEyeDev.HeadlessRim</li>
    <li>RedEyeDev.RIMAPI</li>
  </activeMods>
  <knownExpansions>
    <li>ludeon.rimworld.royalty</li>
  </knownExpansions>
</ModsConfigData>
XMLEOF
    echo "ModsConfig.xml seeded with HeadlessRimPatch + RIMAPI"
fi

# Replace the game's Mods dir with our merged mods (needs write access to game volume)
if [ -d /opt/game/Mods ] && [ ! -L /opt/game/Mods ]; then
    mv /opt/game/Mods /opt/game/Mods.orig
fi
ln -sfn "$MODS_DIR" /opt/game/Mods
echo "Game Mods -> $MODS_DIR"

# Ensure rimworld user can write to needed dirs
chown -R rimworld:rimworld /home/rimworld /opt/mods-merged /opt/saves 2>/dev/null || true
chmod +x /opt/game/RimWorldLinux 2>/dev/null || true

# Launch RimWorld as rimworld user
echo "Starting RimWorld headless..."
su rimworld -c '/opt/game/RimWorldLinux \
    -batchmode \
    -nographics \
    -noshaders \
    -force-opengl \
    -startServer \
    -logFile /tmp/rimworld_log.txt' &
GAME_PID=$!

# Wait for RIMAPI to become responsive.
# Wait for RIMAPI to become responsive on loopback
RIMAPI_TIMEOUT=${RIMAPI_TIMEOUT:-120}
echo "Waiting for RIMAPI on :8765 (timeout: ${RIMAPI_TIMEOUT}s)..."
ELAPSED=0
while ! curl -sf --max-time 5 http://localhost:8765/api/v1/game/state > /dev/null 2>&1; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    if [ "$ELAPSED" -ge "$RIMAPI_TIMEOUT" ]; then
        echo "ERROR: RIMAPI not responsive after ${RIMAPI_TIMEOUT}s"
        tail -30 /tmp/rimworld_log.txt 2>/dev/null
        exit 1
    fi
done
echo "RIMAPI ready on loopback"

# Mono HttpListener binds to [::1] (IPv6 loopback) regardless of config.
# Bridge all interfaces on port 8765 so Docker port forwarding can reach it.
socat TCP4-LISTEN:8765,fork,reuseaddr TCP6:[::1]:8765 &
echo "socat bridge: 0.0.0.0:8765 -> [::1]:8765"

# Keep container alive
tail -f /tmp/rimworld_log.txt
