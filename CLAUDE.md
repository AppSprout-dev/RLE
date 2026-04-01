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

### Verify everything is running

```bash
# RIMAPI running? (game must be loaded into a map)
curl http://localhost:8765/api/v1/game/state

# LM Studio running? (if using local)
curl http://localhost:1234/v1/models
```

## Commands

- Install: `pip install -e ".[dev]"`
- Test: `pytest`
- Lint: `ruff check src/ tests/ scripts/`
- Type check: `mypy src/`
- List scenarios: `python scripts/run_scenario.py --list`

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

### Mock benchmark (no game needed)

```bash
python scripts/run_benchmark.py --dry-run --ticks 10
```

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
1. Loads the scenario's save file (`rle_crashlanded_v1`)
2. Polls until game is ready (colonist_count > 0)
3. Unforbids all starting items (via `POST /api/v1/things/set-forbidden`)
4. Unpauses game at speed 3 (if `--no-pause`)

## CentralPost Hub-Spoke Communication

Agents communicate through Felix SDK's CentralPost, not through the orchestrator:

- **Before deliberation**: `process_all_messages()` routes previous tick's messages to agent spoke inbound queues. Agents read via `_get_spoke_context()`.
- **MapAnalyst first**: Deliberates, sends TASK_COMPLETE with spatial analysis. Messages routed immediately so role agents see it.
- **After deliberation**: Each role agent sends `TASK_COMPLETE` with role, summary, confidence, action types.
- **After scoring**: Hub broadcasts `STATUS_UPDATE` with composite score + all 8 metrics.
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

## Scoring (8 metrics, weighted composite)

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

- Async-first (httpx AsyncClient, async game loop)
- Parallel-first: MapAnalyst runs first (sequential), then 6 role agents deliberate concurrently via `asyncio.to_thread` + `asyncio.gather` (`--sequential` to disable)
- Pydantic v2 models with frozen=True for game state and results
- Felix Agent SDK for providers, agents, helix geometry, CentralPost communication
- JSON repair + parse retry for LLM output resilience (strips think tags, trailing commas, extracts first JSON object)
- Real RIMAPI data via state adapters + deterministic terrain analysis
- Tests use pytest-asyncio with auto mode

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
├── scoring/               # 8 metrics, composite scorer, CSV recorder
└── scenarios/             # YAML schema, loader, evaluator, 6 definitions
scripts/
├── run_scenario.py        # Single scenario CLI (auto-loads save, unforbids items)
├── run_benchmark.py       # Full benchmark suite CLI
├── visualize_results.py   # Matplotlib CSV plotter
└── serve_dashboard.py     # CORS-enabled file server for dashboard

## Related Repos

- [felix-agent-sdk](https://github.com/AppSprout-dev/felix-agent-sdk) — Agent framework (LLMAgent, CentralPost, HelixGeometry, providers)
- [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) — C# RimWorld mod (REST API + SSE). [Our fork](https://github.com/AppSprout-dev/RIMAPI) has the `rle-testing` branch with extra endpoints pending upstream merge.
- [rimapi-dashboard](https://github.com/AppSprout-dev/rimapi-dashboard) — React dashboard with 5 RLE widgets. Runs on :3000, reads from :9000.

## RIMAPI Fork Status

We contribute upstream to IlyaChichkov/RIMAPI. PRs #52-54, #60, #63 all merged. Pending: PR #65 (set-forbidden).

The `rle-testing` branch on our fork stays ≤1 commit ahead of upstream develop. Once Ilya cuts a Workshop release (v1.9.0), we can stop deploying custom DLLs and use the Workshop version directly.

To restore the original Workshop DLL: rename `RIMAPI.dll.upstream-backup` back to `RIMAPI.dll` in `C:\Steam\steamapps\workshop\content\294100\3593423732\1.6\Assemblies\`.
```
