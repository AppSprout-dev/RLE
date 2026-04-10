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

- Image builds successfully on Docker Desktop (Windows + WSL2) and Docker CE (Linux)
- HeadlessRimPatch v1.0.0 DLL downloaded and installed at `/opt/mods/HeadlessRimPatch/`
- Entrypoint pre-seeds RIMAPI config to bind `0.0.0.0:8765` (fixes IPv6 loopback issue)
- Windows CRLF line endings are stripped from `entrypoint.sh` during build
- Runs as non-root `rimworld` user (uid 1000)
- Full e2e requires Linux game files mounted at runtime

## Known Issues

- **Startup time**: HeadlessRimPatch generates a throwaway map before we load our save. Feature request filed ([HeadlessRimPatch#5](https://github.com/IlyaChichkov/HeadlessRimPatch/issues/5)) for direct save loading via env var.

## References

- [IlyaChichkov/HeadlessRim](https://github.com/IlyaChichkov/HeadlessRim) — Docker setup
- [IlyaChichkov/HeadlessRimPatch](https://github.com/IlyaChichkov/HeadlessRimPatch) — Harmony patches for headless mode
- [HeadlessRim#1](https://github.com/IlyaChichkov/HeadlessRim/issues/1) — RIMAPI compatibility confirmed
