# RLE — RimWorld Learning Environment

Multi-agent benchmark where 7 Felix Agent SDK role-specialized LLM agents manage a RimWorld colony. Think FLE (Factorio Learning Environment) but for multi-agent coordination under uncertainty.

## Prerequisites

Four things must be set up before RLE can run against a live game:

1. **RimWorld** — Steam install at `C:\Steam\steamapps\common\RimWorld\` (or wherever Steam is)
2. **Harmony + RIMAPI mods** — Subscribe on Steam Workshop, then **enable both** in the in-game Mods menu. Load order: Harmony → Core → Royalty → RIMAPI. RIMAPI exposes REST API on `:8765` + SSE events.
3. **LLM provider** — [LM Studio](https://lmstudio.ai/) (local, port 1234) or [OpenRouter](https://openrouter.ai/) (cloud)
4. **Save file** — `rle_crashlanded_v1` save must exist in RimWorld's save folder (`C:\Users\<you>\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Saves\`). The scenario auto-loads it.

### RIMAPI mod setup (critical)

The Workshop version may be behind our needs. We maintain a fork build:

```bash
# Clone the fork (if not already)
git clone https://github.com/AppSprout-dev/RIMAPI.git
cd RIMAPI
git checkout rle-testing

# Build for RimWorld 1.6
cd Source/RIMAPI
dotnet build RimApi.csproj -c Release-1.6

# Deploy DLL over Workshop install (close RimWorld first!)
cp ../../1.6/Assemblies/RIMAPI.dll \
  "C:/Steam/steamapps/workshop/content/294100/3593423732/1.6/Assemblies/RIMAPI.dll"
```

The upstream Workshop DLL is backed up as `RIMAPI.dll.upstream-backup` in the same folder.

### RIMAPI gotchas

- RIMAPI only starts serving **after the map loads** (not on the main menu)
- It listens on **IPv6 `[::1]:8765`**, not IPv4 `127.0.0.1:8765`. Use `localhost` (resolves to both).
- The game must be **unpaused** (or the intro dialog dismissed) for RIMAPI to process requests. The HTTP server runs on Unity's main thread queue — paused games don't process the queue.
- All POST request bodies must use **snake_case** field names (`pawn_id` not `PawnId`). See RIMAPI's [API conventions](https://github.com/IlyaChichkov/RIMAPI/blob/develop/docs/developer_guide/api_conventions.md).
- All pawn/building/zone IDs are **integers**, not strings. Sending `"184"` deserializes as `0`.
- POST requests require a `Content-Length` header (send `{}` as body even if using query params).
- **Writes are async.** `save_game`, `load_game`, and `spawn_*` return HTTP 200 before Unity's main thread actually executes them. `save_game` returns before the file is flushed (poll file size to confirm). `load_game` needs ~10s settle after `colonist_count > 0` before the map is usable.
- **`spawn_item` cannot split stacks.** Sending `amount > max_stack[def_name]` triggers a null ref that cascades and destabilizes the entire game. Chunk manually (e.g. MealSurvivalPack max=10, WoodLog/Steel max=75).
- **Null-ref cascades.** Once one RIMAPI call errors with "Object reference not set", subsequent calls start failing. Only recovery is a game restart.

### Verify everything is running

```bash
# RIMAPI running? (game must be loaded into a map)
curl http://localhost:8765/api/v1/game/state

# LM Studio running? (if using local)
curl http://localhost:1234/v1/models
```

## Commands

- Install: `uv sync --extra dev`
- Test: `pytest`
- Lint: `ruff check src/ tests/ scripts/`
- Type check: `mypy src/`
- List scenarios: `python scripts/run_scenario.py --list`
- Smoke test: `python scripts/run_benchmark.py --smoke-test --ticks 5`
- Compare runs: `python scripts/compare_benchmarks.py results/run1 results/run2`

### Configure `.env`

```bash
cp .env.example .env
```

The `.env` file controls which LLM provider is used. Key fields:

| Field | Description | Example |
|-------|-------------|---------|
| `OPENAI_API_KEY` | API key for OpenAI SDK (LM Studio: any string; OpenRouter: your key) | `lm-studio` or `sk-or-v1-...` |
| `PROVIDER` | `openai` (LM Studio/OpenRouter/OpenAI) or `anthropic` | `openai` |
| `MODEL` | Model name as the provider expects it | `unsloth/nvidia-nemotron-3-nano-4b` |
| `PROVIDER_BASE_URL` | API base URL (required for LM Studio and OpenRouter) | `http://localhost:1234/v1` |
| `RIMAPI_URL` | RIMAPI mod URL | `http://localhost:8765` |

**Important:** For OpenRouter, `OPENAI_API_KEY` must be set to your OpenRouter API key. The OpenAI SDK reads this env var directly. The `OPENROUTER_API_KEY` field is NOT read by the SDK.

CLI flags (`--provider`, `--model`, `--base-url`) override `.env` values.

### Live scenario (requires RimWorld + RIMAPI running)

```bash
# If .env is configured, just:
python scripts/run_scenario.py crashlanded \
  --no-think --no-pause --visualize --ticks 10 \
  --output results/live --tick-interval 30

# Or override provider on the command line:
# Local LM Studio (Nemotron Nano 4B)
python scripts/run_scenario.py crashlanded \
  --provider openai \
  --model unsloth/nvidia-nemotron-3-nano-4b \
  --base-url http://localhost:1234/v1 \
  --no-think --no-pause --visualize --ticks 10 \
  --output results/live --tick-interval 30

# OpenRouter (Nemotron Super 120B — set OPENAI_API_KEY first)
OPENAI_API_KEY=<your-openrouter-key> \
python scripts/run_scenario.py crashlanded \
  --provider openai \
  --model nvidia/nemotron-3-super-120b-a12b:free \
  --base-url https://openrouter.ai/api/v1 \
  --no-think --no-pause --visualize --ticks 10 \
  --output results/live --tick-interval 30
```

**Important flags:**
- `--no-think` — Required for thinking models (Nemotron, Qwen). Injects `</think>` prefix.
- `--no-pause` — Game runs continuously via SSE. Without this, game pauses each tick.
- `--no-agent` — Baseline mode: no LLM deliberation, colony runs unmanaged (for comparison).
- `--output results/live` — Exports `latest_tick.json` for the dashboard.
- `--tick-interval 30` — Seconds between ticks. 30s gives agents time to deliberate.

### Dashboard (3 terminals)

```bash
# Terminal 1: Run the scenario with --output
python scripts/run_scenario.py crashlanded --output results/live ...

# Terminal 2: Serve tick data (CORS-enabled :9000)
python scripts/serve_dashboard.py results/live

# Terminal 3: Start React dashboard (requires bun)
cd ../rimapi-dashboard && bun run start
# Open http://localhost:3000
```

### Smoke test (no game needed)

```bash
python scripts/run_benchmark.py --smoke-test --ticks 10
```

### Docker benchmark (no display needed)

```bash
# Build the headless image (see docker/README.md for prerequisites)
docker compose -f docker/docker-compose.yml up -d

# Run benchmark against containerized game
python scripts/run_benchmark.py --docker --provider openai \
  --model nvidia/nemotron-3-super-120b-a12b:free \
  --base-url https://openrouter.ai/api/v1 \
  --no-think --runs 4 --output results/docker/
```

**Benchmark flags:**
- `--smoke-test` — Mock RIMAPI (replaces deprecated `--dry-run`)
- `--docker` — Use Docker container for headless RimWorld
- `--runs N` — Paired runs per scenario (N≥4 for statistical validity)
- `--no-baseline` — Skip baseline (no-agent) comparison runs
- `--ablation` — (WIP) Run with each agent removed to measure contribution
- `--wandb` — Log to Weights & Biases
- `--push-hf` — Push results to HuggingFace Hub (requires `--runs 4+`)

## Architecture

```
RimWorld (game)
    ↕ Harmony patches
RIMAPI mod (REST :8765 + SSE /api/v1/events)
    ↕
RimAPIClient (httpx async) + RimAPISSEClient (event stream)
    ↕
RLEGameLoop
  unpause → read state → drain SSE → inject events → route spoke messages
  → MapAnalyst deliberates FIRST (spatial analysis)
  → broadcast MapAnalyst output via CentralPost
  → 6 role agents deliberate (parallel) → resolve conflicts → execute actions
  → score → broadcast score → export tick JSON → render helix
    ↕
CentralPost hub-spoke (TASK_COMPLETE, STATUS_UPDATE, PHASE_ANNOUNCE)
 ↕  ↕  ↕  ↕  ↕  ↕  ↕
7 Agents (MapAnalyst + 6 Role Agents)
    ↕
ActionResolver → merged ActionPlan
    ↕
ActionExecutor → RIMAPI write calls
    ↕
CompositeScorer → ScoreSnapshot per tick
    ↕
ScenarioEvaluator → victory/defeat/timeout
    ↕
HelixVisualizer (terminal) + Dashboard (React :3000 via latest_tick.json :9000)
```

## Agents (map to roles, not colonists)

| Agent | Domain | Key Actions |
|-------|--------|-------------|
| **MapAnalyst** | Spatial reasoning (runs FIRST) | no_action (analysis only — produces MAP_SUMMARY) |
| ResourceManager | Food, materials, power, hauling | work_priority, growing_zone, stockpile_zone, designate_area |
| DefenseCommander | Raids, drafting, positioning | draft, move |
| ResearchDirector | Tech tree, researcher assignment | research_target, research_stop, work_priority |
| SocialOverseer | Mood, recreation, mental breaks | time_assignment, work_priority |
| ConstructionPlanner | Buildings, walls, repairs | blueprint, designate_area, work_priority |
| MedicalOfficer | Injuries, disease, medicine | bed_rest, tend, work_priority |

### MapAnalyst + Spatial Awareness

MapAnalyst runs before the other 6 agents each tick. It reads terrain data from RIMAPI (`/api/v1/map/terrain`) and produces a deterministic spatial analysis:

- **MAP_SUMMARY** — compact ~500 token text injected into every agent's context
- **SHELTER_SITE** — verified 7x7 rectangle on solid ground near colony center
- **FARM_SITE** — verified 8x8 rectangle on fertile soil
- **STOCKPILE_SITE** — verified 5x5 rectangle on buildable ground
- **WATER_ZONES** — areas agents must never build on

All role agents are told: "MUST use coordinates from MAP_SUMMARY, do NOT invent coordinates."

### Bootstrap Playbook (day < 3)

Tick-specific priorities injected into all agents:
- Tick 1: Stockpile + work priorities + growing zone (Plant_Rice)
- Tick 2: 5x5 shelter walls + door + 3 beds (WoodLog)
- Tick 3: Campfire/stove + research bench + research target
- Tick 4+: Mining + expansion

### Save Loading + Item Setup

`run_scenario.py` automatically:
1. Loads the scenario's save file (`rle_crashlanded_v1`, etc.)
2. Polls until game is ready (colonist_count > 0)
3. Unforbids all starting items (via `POST /api/v1/things/set-forbidden`)
4. Runs any `setup_commands` declared in the scenario YAML (spawn_pawn, spawn_item, change_weather, drop_pod)
5. Unpauses game at speed 3 (if `--no-pause`)

### Regenerating scenario saves

The 5 advanced saves (first_winter, toxic_fallout, raid_defense, plague_response, ship_launch) are built via `scripts/create_scenario_saves.py` — declarative RIMAPI calls that load the base crashlanded save, spawn items/pawns, trigger incidents, and write each scenario. Requires RimWorld running with a map loaded. Saves land in AppData and are mirrored to `docker/saves/`. Use `--only <name>` for a single rebuild or `--difficulty-only` for offline byte-patching.

## CentralPost Hub-Spoke Communication

Agents communicate through Felix SDK's CentralPost, not through the orchestrator:

- **Before deliberation**: `process_all_messages()` routes previous tick's messages to agent spoke inbound queues. Agents read via `_get_spoke_context()`.
- **MapAnalyst first**: Deliberates, sends TASK_COMPLETE with spatial analysis. Messages routed immediately so role agents see it.
- **After deliberation**: Each role agent sends `TASK_COMPLETE` with role, summary, confidence, action types.
- **After scoring**: Hub broadcasts `STATUS_UPDATE` with composite score + all 10 metrics.
- **On phase change**: Hub broadcasts `PHASE_ANNOUNCE` when macro_time crosses 0.4 (exploration→analysis) or 0.7 (analysis→synthesis).

## SSE Events

RimAPISSEClient connects to `/api/v1/events` and buffers real-time game events (raids, deaths, mental breaks). Each tick:

1. GameStateManager drains SSE buffer → `pending_events`
2. Game loop injects events into all agents via `set_pending_events()`
3. Each agent's `filter_game_state()` includes role-relevant events as `"recent_events"`

## Conflict Resolution (4 rules)

1. Emergency roles promoted during crises (DefenseCommander during raids, MedicalOfficer during plague)
2. Same-pawn conflicts: lowest action priority number wins
3. Role priority tiebreak (ResourceManager=3, DefenseCommander=3, MedicalOfficer=4, MapAnalyst=10, others=5)
4. Final tiebreak: highest plan confidence score

## Helix Phase Adaptation

Macro helix: `t = min(1.0, game_day / expected_duration_days)` drives agent behavior:
- **Exploration** (t < 0.4): High temperature, diverse strategies
- **Analysis** (0.4 <= t < 0.7): Medium temp, evaluate trade-offs
- **Synthesis** (t >= 0.7): Low temperature, decisive actions

## Scoring (10 metrics, weighted composite)

| Metric | Default Weight | Source |
|--------|---------------|--------|
| survival | 0.25 | alive/started colonists |
| threat_response | 0.15 | draft response speed |
| mood | 0.15 | avg colonist mood (from real RIMAPI data) |
| food_security | 0.10 | food count / 10 (from /api/v1/resources/summary) |
| wealth | 0.10 | wealth growth ratio |
| research | 0.10 | % research tree completed |
| self_sufficiency | 0.10 | power + food + population stability |
| efficiency | 0.05 | action execution rate |
| coordination | 0.00* | conflicts resolved / total conflicts |
| communication_efficiency | 0.00* | messages acted on / total messages |

*Process metrics have 0.0 weight until game loop wires MetricContext counters. Target: coordination=0.12, communication_efficiency=0.08.

Scenarios can override weights. TimeSeriesRecorder exports per-tick CSV.

## Scenarios (6 predefined YAML challenges)

| # | Name | Difficulty | Duration |
|---|------|-----------|----------|
| 01 | Crashlanded Survival | easy | 30 days |
| 02 | First Winter | medium | 60 days |
| 03 | Toxic Fallout | hard | 20 days |
| 04 | Raid Defense | hard | 15 days |
| 05 | Plague Response | hard | 20 days |
| 06 | Ship Launch | extreme | 120 days |

Each defines victory/failure conditions, scoring weight overrides, and max ticks.

## Provider Configuration

Provider-agnostic via felix-agent-sdk. CLI flags: `--provider`, `--model`, `--base-url`.

| Provider | Model | Command |
|----------|-------|---------|
| LM Studio (local) | Nemotron Nano 4B | `--provider openai --model unsloth/nvidia-nemotron-3-nano-4b --base-url http://localhost:1234/v1` |
| OpenRouter (cloud) | Nemotron 30B | `OPENAI_API_KEY=<key> --provider openai --model nvidia/nemotron-3-nano-30b-a3b --base-url https://openrouter.ai/api/v1` |
| Anthropic | Claude | `--provider anthropic --model claude-sonnet-4-5` |
| OpenAI | GPT-4o | `--provider openai --model gpt-4o` |

Use `--no-think` for thinking models (Qwen3.5, Nemotron) — injects `</think>` assistant prefix to skip reasoning chain.

## Conventions

- Python 3.14+, `uv` for package management, `hatchling` build backend
- Async-first (httpx AsyncClient, async game loop)
- Parallel-first: MapAnalyst runs first (sequential), then 6 role agents deliberate concurrently via `asyncio.to_thread` + `asyncio.gather` (`--sequential` to disable)
- Pydantic v2 models with frozen=True for game state and results
- mypy strict mode — all code must pass `mypy src/` with `strict = true`
- No scipy/numpy — stdlib only for statistics (random, math). See ADR-003 for rationale
- Felix Agent SDK for providers, agents, helix geometry, CentralPost communication
- JSON repair + parse retry for LLM output resilience (strips think tags, trailing commas, extracts first JSON object)
- Real RIMAPI data via state adapters + deterministic terrain analysis
- Tests use pytest-asyncio with auto mode

## CI/CD

GitHub Actions workflows in `.github/workflows/`:

- **ci.yml** — On every push/PR: ruff lint, mypy strict, pytest, smoke-test
- **benchmark.yml** — Manual dispatch + weekly schedule: Docker benchmark template (requires self-hosted runner with game files)

## Package Structure

```
src/rle/
├── config.py              # RLEConfig (pydantic-settings)
├── rimapi/                # RIMAPI async HTTP client + SSE + Pydantic schemas
│   ├── client.py          # RimAPIClient (REST read/write + state adapters + terrain analysis)
│   ├── schemas.py         # GameState, MapData, TerrainSummary, ZoneData, etc.
│   └── sse_client.py      # RimAPISSEClient (real-time event stream)
├── agents/                # 7 agents (MapAnalyst + 6 role agents) + base class
│   ├── base_role.py       # RimWorldRoleAgent (spoke context, SSE events, MAP_SUMMARY, bootstrap)
│   ├── actions.py         # Action, ActionPlan, resolve_endpoint()
│   ├── json_repair.py     # Strip think tags, trailing commas, extract JSON
│   ├── map_analyst.py     # MapAnalyst (spatial analysis, runs first)
│   ├── resource_manager.py
│   ├── defense_commander.py
│   ├── research_director.py
│   ├── social_overseer.py
│   ├── construction_planner.py
│   └── medical_officer.py
├── orchestration/         # Game loop, state manager, action executor/resolver
│   ├── game_loop.py       # RLEGameLoop (MapAnalyst-first, parallel deliberation, CentralPost)
│   ├── state_manager.py   # GameStateManager (SSE drain, macro time, history)
│   ├── action_executor.py # Routes actions to RIMAPI write endpoints
│   └── action_resolver.py # 4-rule conflict resolution
├── scoring/               # 10 metrics, composite scorer, bootstrap CIs, CSV recorder
│   ├── metrics.py         # 10 individual metric functions (8 colony + 2 process)
│   ├── composite.py       # CompositeScorer (weighted aggregation)
│   ├── bootstrap.py       # BootstrapCI, bootstrap_ci(), bootstrap_paired_delta()
│   ├── delta.py           # PairedResult (agent vs baseline stats, Welch's t-test)
│   └── recorder.py        # TimeSeriesRecorder (per-tick CSV export)
├── tracking/              # Benchmark history, cost tracking, observability
│   ├── cost_tracker.py    # CostTracker + OpenRouter pricing API
│   ├── event_log.py       # Structured JSONL event log (deliberations, actions, errors)
│   ├── leaderboard.py     # Model×scenario matrix, Pareto frontier
│   ├── history.py         # JSONL run history + per-model baselines
│   ├── metadata.py        # Git commit, versions, reproducibility metadata
│   ├── wandb_logger.py    # Weights & Biases integration (optional)
│   └── hf_logger.py       # HuggingFace Hub export (optional)
├── docker.py              # DockerGameServer lifecycle + wait_for_rimapi()
└── scenarios/             # YAML schema, loader, evaluator, 6 definitions
scripts/
├── run_scenario.py        # Single scenario CLI (auto-loads save, unforbids items)
├── run_benchmark.py       # Full benchmark suite CLI (--docker, --smoke-test, --runs)
├── compare_benchmarks.py  # Paired statistical comparison of benchmark runs
├── visualize_results.py   # Matplotlib CSV plotter
└── serve_dashboard.py     # CORS-enabled file server for dashboard
docker/
├── Dockerfile             # HeadlessRim + Xvfb (debian:bookworm-slim)
├── docker-compose.yml     # Volume mounts for game files, mods, saves
├── entrypoint.sh          # Xvfb → RimWorld → RIMAPI healthcheck
└── README.md              # Docker setup prerequisites and troubleshooting

## Related Repos

- [felix-agent-sdk](https://github.com/AppSprout-dev/felix-agent-sdk) — Agent framework (LLMAgent, CentralPost, HelixGeometry, providers)
- [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) — C# RimWorld mod (REST API + SSE). [Our fork](https://github.com/AppSprout-dev/RIMAPI) has the `rle-testing` branch with extra endpoints pending upstream merge.
- [rimapi-dashboard](https://github.com/AppSprout-dev/rimapi-dashboard) — React dashboard with 5 RLE widgets. Runs on :3000, reads from :9000.

## RIMAPI Fork Status

We contribute upstream to IlyaChichkov/RIMAPI. PRs #52-54, #60, #63, #65 all merged.

The `rle-testing` branch tracks upstream develop. We always build from `rle-testing` and deploy the DLL to the Workshop folder — this is our active development workflow.

To restore the original Workshop DLL: rename `RIMAPI.dll.upstream-backup` back to `RIMAPI.dll` in `C:\Steam\steamapps\workshop\content\294100\3593423732\1.6\Assemblies\`.
```
