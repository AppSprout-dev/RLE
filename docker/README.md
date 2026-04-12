# HeadlessRim Docker — Automated RLE Benchmarks

Runs RimWorld headlessly in Docker with RIMAPI for automated benchmark sessions.

## Prerequisites

1. **Linux RimWorld game files** — Download via SteamCMD:
   ```bash
   steamcmd +login <user> +app_update 294100 -platform linux +quit
   ```

2. **RIMAPI mod** — Built from [our fork](https://github.com/AppSprout-dev/RIMAPI) (`rle-testing` branch):
   ```bash
   cd RIMAPI/Source/RIMAPI && dotnet build RimApi.csproj -c Release-1.6
   ```

3. **HeadlessRimPatch** — Downloaded automatically in the Dockerfile from [GitHub Releases](https://github.com/IlyaChichkov/HeadlessRimPatch/releases) (v1.0.0). Alternatively, mount a local build.

4. **Save files** — Place RLE scenario saves in `docker/saves/`.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your paths
docker compose up -d
# Wait for healthcheck (~60-120s)
curl http://localhost:8765/api/v1/game/state
```

## How It Works

1. Container starts Xvfb on `:99` (virtual display)
2. RimWorldLinux launches in `-batchmode -nographics` mode
3. HeadlessRimPatch patches out Unity UI/rendering, calls `SetupForQuickTestPlay()` to auto-start a game
4. RIMAPI starts serving on `:8765` once a map loads
5. RLE orchestrator connects and loads the benchmark save via `POST /api/v1/game/load`

## Running Benchmarks

```bash
# From the RLE project root:
python scripts/run_benchmark.py --docker --provider openai \
    --model nvidia/nemotron-3-super-120b-a12b:free \
    --base-url https://openrouter.ai/api/v1 \
    --no-think --runs 4 --output results/docker/
```

## Validated State

- Image builds on Docker Desktop (Windows + WSL2) and Docker CE (Linux)
- Linux game files via SteamCMD (includes Workshop mods: Harmony, RIMAPI)
- HeadlessRimPatch v1.0.0 patches texture atlas + UI + audio for headless mode
- Entrypoint seeds `ModsConfig.xml` (Harmony → Core → Royalty → HeadlessRim → RIMAPI)
- Entrypoint seeds RIMAPI config to bind `0.0.0.0:8765` (fixes IPv6 loopback)
- Game `Mods/` dir replaced with symlink to merged mods at runtime
- RIMAPI responds on :8765 within ~60s (with patched HeadlessRimPatch, see PR #6)
- CRLF line endings stripped from `entrypoint.sh` during build

### SteamCMD Download (Docker volume approach)

```bash
# Create volume and download Linux RimWorld (~860 MB)
docker volume create rimworld-linux
docker run -it --rm -v rimworld-linux:/opt/rimworld \
  steamcmd/steamcmd:latest \
  +@sSteamCmdForcePlatformType linux \
  +force_install_dir /opt/rimworld \
  +login YOUR_STEAM_USERNAME \
  +app_update 294100 validate +quit
# Prompts for password + Steam Guard code
```

SteamCMD also downloads Workshop mods (Harmony, RIMAPI) into the volume.

### Running with Docker volumes

```bash
docker run -d --name rle-rimworld \
  -p 8765:8765 --shm-size=1g \
  -v rimworld-linux:/opt/game \
  -v rimapi-mod:/opt/mods/RIMAPI:ro \
  -v ./saves:/opt/saves:ro \
  rle-headless:test
# RIMAPI should respond within ~60s:
curl http://localhost:8765/api/v1/game/state
```

## Known Issues

- **IPv6 loopback binding**: RIMAPI's Mono HttpListener binds to `[::1]:8765` inside the container despite `serverIP=0.0.0.0` config. Docker port forwarding can't reach `::1`. Workaround: access RIMAPI from inside the container or fix the HttpListener binding in RIMAPI fork.
- **HeadlessRimPatch autoplay removed**: [PR #6](https://github.com/IlyaChichkov/HeadlessRimPatch/pull/6) removes `SetupForQuickTestPlay()` so RIMAPI serves immediately. Until merged, use our fork's `remove-autoplay` branch.

## References

- [IlyaChichkov/HeadlessRim](https://github.com/IlyaChichkov/HeadlessRim) — Docker setup
- [IlyaChichkov/HeadlessRimPatch](https://github.com/IlyaChichkov/HeadlessRimPatch) — Harmony patches for headless mode
- [HeadlessRim#1](https://github.com/IlyaChichkov/HeadlessRim/issues/1) — RIMAPI compatibility confirmed
