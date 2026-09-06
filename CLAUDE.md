# RLE — RimWorld Learning Environment

A harness × model benchmark: swappable agent harnesses (the original 7-agent Felix Agent SDK stack, an unmanaged baseline, or external coding agents installed as `rle-harness-*` packages) manage a RimWorld colony and are scored identically. Think FLE (Factorio Learning Environment) but for multi-agent coordination under uncertainty, with the harness as a first-class benchmark variable.

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

- Install: `uv sync --extra dev --extra felix` (add `--extra mcp` for the RimAPI MCP server; core alone has no agent framework)
- Test: `pytest`
- Lint: `ruff check src/ tests/ scripts/`
- Type check: `mypy src/`
- List scenarios: `python scripts/run_scenario.py --list`
- Smoke test: `python scripts/run_benchmark.py --smoke-test --ticks 5 --harness felix --harness baseline`
- Harness boundary: `python scripts/check_harness_boundary.py`
- List harnesses: `python scripts/run_benchmark.py --harness list`
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
| `MCP_CONTAINER_REACHABLE` | Bind MCP on `0.0.0.0:8766`, advertise `http://host.docker.internal:8766/mcp` for Docker agents (host RimWorld). Not `--docker`. | `true` |
| `MCP_BIND_HOST` / `MCP_ADVERTISE_HOST` / `MCP_PORT` | Optional MCP listen overrides (also `--harness-opt mcp_*`) | `0.0.0.0` / `host.docker.internal` / `8766` |

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
- `--harness NAME` — Which harness decides (default `felix`; `--harness list` shows installed plugins; `--harness-opt key=value` for plugin options).
- `--no-agent` — Baseline mode: alias for `--harness baseline`; colony runs unmanaged (for comparison).
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
RLEGameLoop (environment — no agent framework imports)
  pause → read state → drain SSE → harness.step(state, tick, macro_time, events)
  → execute StepResult.plan (unless the harness already applied its writes)
  → score → harness.on_tick_end → export tick JSON → unpause → evaluate
    ↕ Harness protocol (rle.harness.BaseHarness), discovered via `rle.harnesses` entry points
    ├── felix     (in tree, extra `felix`)  CentralPost hub-spoke → MapAnalyst FIRST →
    │             6 role agents (parallel) → ActionResolver → merged ActionPlan → helix viz
    ├── baseline  (in tree)                 unmanaged colony — the paired control
    ├── raw-grok  (in tree, extra `mcp`)    MODEL BASELINE: stock grok, TURN_RULES only
    └── <tool>    (own repos: rle-harness-template / -opencode / …)
                  HeadlessCliHarness → RLE MCP server (rle.mcp, in-process HTTP) →
                  coding agent acts through tools during its turn → TickLedger → StepResult.execution
    ↕
ActionExecutor → RIMAPI write calls (shared by every harness; MCP tools call it too)
    ↕
CompositeScorer (scoring 1.2: outcomes + efficiency + plan_coherence) → ScoreSnapshot per tick
    ↕
ScenarioEvaluator → victory/defeat/timeout
    ↕
Dashboard (React :3000 via latest_tick.json :9000; `harness` + `extras` fields are harness-neutral)
```

**Repo boundary rule:** RLE-authored harnesses (`baseline`, `felix`, `raw-grok` model baseline) live here. Product wrappers for third-party coding agents ship as their own `AppSprout-dev/rle-harness-*` packages. `scripts/check_harness_boundary.py` (run in CI) fails on any `felix_agent_sdk` import outside `src/rle/harness/felix/` and on any third-party product-harness name in `src/`, `tests/`, or `scripts/`. Writing a harness: `docs/harness-plugins.md`; Felix knobs: `docs/harness-felix.md`; design rationale: ADR-004.

```bash
python scripts/run_benchmark.py --harness list                     # installed plugins + availability
python scripts/run_benchmark.py --harness felix --harness baseline --smoke-test
python scripts/run_scenario.py crashlanded --harness felix --harness-opt no_think=true --harness-opt parallel=false
python scripts/run_scenario.py crashlanded --harness raw-grok --model grok-4.6 --seed 42 --ticks 10 \
  --harness-opt binary=grok --harness-opt turn_timeout_s=300 \
  --harness-opt mcp_advertise_url=http://host.docker.internal:8766/mcp
```

## Harnesses

| Harness | Where | What |
|---------|-------|------|
| `felix` | in tree, extra `felix` (`src/rle/harness/felix/`) | MapAnalyst + 6 role agents over CentralPost, merged by ActionResolver; helix phases; the original stack. Everything in the next four sections describes this harness only. Roster: `--harness-opt roles=` / `exclude_agent=`. |
| `baseline` | in tree | Unmanaged colony — paired control for every run. |
| `raw-grok` | in tree, extra `mcp` | **Model baseline** — stock `grok` binary, `TURN_RULES` only. Not comparable to felix or product coding-agent harnesses as an architecture. |
| `opencode` / `grok-build` | own repos (`AppSprout-dev/rle-harness-*`) | Coding agents driven via `HeadlessCliHarness`: one prompt per tick, act through the RLE MCP tools, `end_turn`; the ledger of writes is scored. |
| `template` | own repo | Starting point for new harnesses; RLE CI installs it as the plugin-API contract test. |

Every harness receives the same neutral brief (`rle.harness.brief`: scenario goals, state snapshot, MAP_SUMMARY, action catalog). Anything beyond that — role splits, bootstrap playbook, helix temperature, tool framing — is the harness's own prompt engineering and is part of what is measured. Options are per plugin (`--harness-opt key=value`, validated by its pydantic schema); Felix's are `parallel`, `no_think`, `helix_preset`, `role_timeout_s`, `roles`, `exclude_agent`, `provider_kwargs`, `visualize` (see `docs/harness-felix.md`).

## Felix harness: agents (map to roles, not colonists)

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

The deterministic spatial analysis is core (`rle.harness.brief.build_map_summary`, from RIMAPI `/api/v1/map/terrain`) and every harness gets it in its brief. In the Felix harness, MapAnalyst runs before the other 6 agents each tick and narrates it:

- **MAP_SUMMARY** — compact ~500 token text injected into every agent's context
- **SHELTER_SITE** — verified 7x7 rectangle on solid ground near colony center
- **FARM_SITE** — verified 8x8 rectangle on fertile soil
- **STOCKPILE_SITE** — verified 5x5 rectangle on buildable ground
- **WATER_ZONES** — areas agents must never build on

All role agents are told: "MUST use coordinates from MAP_SUMMARY, do NOT invent coordinates."

### Bootstrap Playbook (day < 3) — Felix only

Tick-specific priorities injected into all Felix agents (other harnesses get no playbook; that is their harness's problem to solve):
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

## Felix harness: CentralPost Hub-Spoke Communication

Felix agents communicate through Felix SDK's CentralPost, owned by `FelixHarness` (the loop knows nothing about it):

- **Before deliberation**: `process_all_messages()` routes previous tick's messages to agent spoke inbound queues. Agents read via `_get_spoke_context()`.
- **MapAnalyst first**: Deliberates, sends TASK_COMPLETE with spatial analysis. Messages routed immediately so role agents see it.
- **After deliberation**: Each role agent sends `TASK_COMPLETE` with role, summary, confidence, action types.
- **After scoring** (`on_tick_end`): Hub broadcasts `STATUS_UPDATE` with the composite score + all metrics, and a `STATUS_UPDATE` listing last tick's failed writes ("DO NOT REPEAT").
- **On phase change**: Hub broadcasts `PHASE_ANNOUNCE` when macro_time crosses 0.4 (exploration→analysis) or 0.7 (analysis→synthesis).

Message and conflict counts are emitted on the `CONFLICT` event as diagnostics; since scoring 1.2 they do not feed the composite.

## SSE Events

RimAPISSEClient connects to `/api/v1/events` and buffers real-time game events (raids, deaths, mental breaks). Each tick:

1. GameStateManager drains SSE buffer → `pending_events`
2. The loop passes them to `harness.step(state, tick, macro_time, events)`; the brief carries the most recent ones as `recent_events`
3. Felix: `FelixHarness` injects them into every agent via `set_pending_events()`, and each agent's `filter_game_state()` includes role-relevant events as `"recent_events"`

## Felix harness: Conflict Resolution (4 rules)

1. Emergency roles promoted during crises (DefenseCommander during raids, MedicalOfficer during plague)
2. Same-pawn conflicts: lowest action priority number wins
3. Role priority tiebreak (ResourceManager=3, DefenseCommander=3, MedicalOfficer=4, MapAnalyst=10, others=5)
4. Final tiebreak: highest plan confidence score

## Felix harness: Helix Phase Adaptation

`macro_time = min(1.0, game_day / expected_duration_days)` is computed by the loop and handed to every harness. Felix maps it onto helix phases that drive agent temperature and prompt directives:
- **Exploration** (t < 0.4): High temperature, diverse strategies
- **Analysis** (0.4 <= t < 0.7): Medium temp, evaluate trade-offs
- **Synthesis** (t >= 0.7): Low temperature, decisive actions

## Scoring (9 metrics, weighted composite, SCORING_VERSION 1.2)

| Metric | Default Weight | Source |
|--------|---------------|--------|
| survival | 0.24 | alive/started colonists |
| threat_response | 0.14 | draft response speed |
| mood | 0.12 | avg colonist mood (from real RIMAPI data) |
| food_security | 0.10 | food count / 10 (from /api/v1/resources/summary) |
| wealth | 0.08 | wealth growth ratio |
| research | 0.08 | % research tree completed |
| self_sufficiency | 0.10 | power + food + population stability |
| efficiency | 0.06 | executed / proposed writes per tick (neutral 0.5 when no writes) |
| plan_coherence | 0.08 | 1 − contradictory executed writes / executed writes per tick (neutral 0.5 when no writes); see `scoring/coherence.py` |

Process metrics are harness-agnostic: they read the executed write stream (`ExecutionResult.outcomes`), never CentralPost or resolver counters. Those Felix-specific counts are still emitted on the `CONFLICT` event as diagnostics. `coordination` / `communication_efficiency` were removed in 1.2 (issue #51) because they were ≈1.0 by construction. Bump `SCORING_VERSION` in `tracking/metadata.py` whenever weights or metric implementations change; pinned `.baseline.json` sidecars are rejected on mismatch until recalibrated with `scripts/calibrate_baseline.py`.

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

## Provider / Model Configuration

`--provider`, `--model`, `--base-url` (and the matching `.env` fields) are plain strings on `RLEConfig`; the selected harness interprets them. Model naming therefore follows the harness:

| Harness | Provider/model meaning | Example |
|---------|------------------------|---------|
| `felix` | Felix SDK provider registry (`anthropic`, `openai`, `local`, `claude-code`) in `rle/harness/felix/provider_factory.py` | `--provider openai --model unsloth/nvidia-nemotron-3-nano-4b --base-url http://localhost:1234/v1` |
| `felix` | | `OPENAI_API_KEY=<key> --provider openai --model nvidia/nemotron-3-nano-30b-a3b --base-url https://openrouter.ai/api/v1` |
| `felix` | | `--provider anthropic --model claude-sonnet-4-5` |
| `opencode` | OpenCode's `provider/model` ids, credentials from `opencode auth` | `--model openai/gpt-4o`, `--model anthropic/claude-sonnet-4-5` |
| `grok-build` | Grok Build's `-m` model id, auth via `XAI_API_KEY` or cached login | `--model grok-4.6` |

Felix-only: `--no-think` (or `--harness-opt no_think=true`) injects a `</think>` assistant prefill so thinking models (Qwen3.5, Nemotron) skip the reasoning chain. Leaderboard rows are `harness/model`, so the same model under two harnesses is two rows.

## Conventions

- Python 3.14+, `uv` for package management, `hatchling` build backend
- Async-first (httpx AsyncClient, async game loop)
- Core is framework-free: `felix_agent_sdk` is imported only under `src/rle/harness/felix/`; everything else runs with the `felix` extra uninstalled (CI `test-no-felix` job + `scripts/check_harness_boundary.py`). Third-party harnesses never live in this tree (ADR-004).
- Harness-agnostic scoring: metrics read the executed write stream, never a harness's internal messaging
- Felix harness: MapAnalyst runs first (sequential), then 6 role agents deliberate concurrently via `asyncio.gather` (`--sequential` / `--harness-opt parallel=false` to disable)
- Pydantic v2 models with frozen=True for game state and results
- mypy strict mode — all code must pass `mypy src/` with `strict = true`; `py.typed` is shipped so external harness packages type-check against RLE
- No scipy/numpy — stdlib only for statistics (random, math). See ADR-003 for rationale
- Felix Agent SDK (inside the `felix` harness only) for providers, agents, helix geometry, CentralPost communication
- JSON repair + parse retry for LLM output resilience (strips think tags, trailing commas, extracts first JSON object)
- Real RIMAPI data via state adapters + deterministic terrain analysis
- Tests use pytest-asyncio with auto mode

## CI/CD

GitHub Actions workflows in `.github/workflows/`:

- **ci.yml** — On every push/PR: ruff lint, mypy strict, harness boundary check, pytest (with `felix`+`mcp` extras), `test-no-felix` (core + `mcp` only: suite, `--harness list`, baseline smoke), `smoke-test` (felix + baseline matrix), `external-plugin-contract` (installs `rle-harness-template` from GitHub, asserts it lists and passes smoke)
- **benchmark.yml** — Manual dispatch + weekly schedule: Docker benchmark template (requires self-hosted runner with game files)

## Package Structure

```
src/rle/
├── config.py              # RLEConfig (pydantic-settings; framework-free: provider/model/harness are strings)
├── py.typed               # external harness packages type-check against RLE
├── rimapi/                # RIMAPI async HTTP client + SSE + Pydantic schemas
│   ├── client.py          # RimAPIClient (REST read/write + state adapters + terrain analysis)
│   ├── schemas.py         # GameState, MapData, TerrainSummary, ZoneData, etc.
│   └── sse_client.py      # RimAPISSEClient (real-time event stream)
├── agents/                # Harness-neutral action vocabulary (NO agent framework here)
│   ├── actions.py         # Action, ActionPlan, ActionOutcome, ExecutionResult, resolve_endpoint()
│   └── json_repair.py     # Strip think tags, trailing commas, extract JSON
├── harness/               # Swappable harnesses
│   ├── protocol.py        # BaseHarness, StepResult, HarnessContext, HarnessPlugin, Availability
│   ├── registry.py        # entry-point discovery (`rle.harnesses`), option validation, create_harness()
│   ├── cli.py             # --harness / --harness list / --harness-opt argparse glue
│   ├── brief.py           # harness-neutral scenario brief (goals, state, MAP_SUMMARY, action catalog)
│   ├── baseline.py        # BaselineHarness (unmanaged colony) + PLUGIN
│   ├── compat.py          # RLEGameLoop(agents=..., no_agent=...) legacy shim
│   ├── cli_base.py        # HeadlessCliHarness: scaffold for CLI coding agents over MCP (extra `mcp`)
│   └── felix/             # The Felix multi-agent harness (extra `felix`; only place felix_agent_sdk is imported)
│       ├── plugin.py      # PLUGIN (lazy SDK imports), harness.py (FelixHarness), build.py, options.py
│       ├── provider_factory.py  # Felix providers + helix presets (moved off RLEConfig)
│       ├── agents/        # RimWorldRoleAgent + MapAnalyst + 6 role agents
│       └── providers/     # ClaudeCodeProvider (claude -p)
├── mcp/                   # RimAPI as an MCP tool server (extra `mcp`)
│   ├── ledger.py          # TickLedger: writes made during a turn → StepResult
│   ├── session.py         # tool logic: act()/read()/brief (framework-free)
│   ├── server.py          # MCPServer: one tool per WRITE_CATALOG entry + get_brief/end_turn/...
│   ├── host.py            # in-process streamable-HTTP host (shared ledger with the loop)
│   └── __main__.py        # `rle-mcp` stdio server for manual play
├── testing/               # Exported for plugin authors
│   ├── mock_rimapi.py     # MockRimAPI transport (records POSTs)
│   ├── smoke.py           # run_harness_smoke(plugin) — the plugin contract test
│   └── scripted_agent.py  # ScriptedMcpHarness: fake coding agent over a real MCP client
├── orchestration/         # Environment: game loop, state manager, executor/resolver
│   ├── game_loop.py       # RLEGameLoop (harness-agnostic; pause/state/step/execute/score)
│   ├── save_loader.py     # load_save_and_settle() shared by both CLIs
│   ├── state_manager.py   # GameStateManager (SSE drain, macro time, history)
│   ├── action_executor.py # Routes actions to RIMAPI write endpoints
│   └── action_resolver.py # 4-rule conflict resolution (used by FelixHarness)
├── scoring/               # 9 metrics, composite scorer, bootstrap CIs, CSV recorder
│   ├── metrics.py         # 9 metric functions (7 colony + efficiency + plan_coherence); NEUTRAL = 0.5
│   ├── coherence.py       # contradiction detection over a tick's executed writes
│   ├── composite.py       # CompositeScorer (weighted aggregation)
│   ├── bootstrap.py       # BootstrapCI, bootstrap_ci(), bootstrap_paired_delta()
│   ├── delta.py           # PairedResult (agent vs baseline stats, Welch's t-test)
│   └── recorder.py        # TimeSeriesRecorder (per-tick CSV export)
├── tracking/              # Benchmark history, cost tracking, observability
│   ├── cost_tracker.py    # CostTracker + OpenRouter pricing API
│   ├── event_log.py       # Structured JSONL event log (deliberations, actions, errors)
│   ├── leaderboard.py     # Harness×model×scenario matrix (quarantine-aware), Pareto frontier
│   ├── history.py         # JSONL run history + per-harness×model baselines
│   ├── metadata.py        # Git commit, versions, reproducibility metadata
│   ├── wandb_logger.py    # Weights & Biases integration (optional)
│   └── hf_logger.py       # HuggingFace Hub export (optional)
├── docker.py              # DockerGameServer lifecycle + wait_for_rimapi()
└── scenarios/             # YAML schema, loader, evaluator, 6 definitions
scripts/
├── run_scenario.py        # Single scenario CLI (auto-loads save, unforbids items, --harness)
├── run_benchmark.py       # Full benchmark suite CLI (--docker, --smoke-test, --runs, repeatable --harness)
├── check_harness_boundary.py  # CI guard: felix confined to harness/felix; no third-party harness code in tree
├── run_spread_n1.sh       # N=1 multi-model spread runner (sequential, continue-on-error)
├── compare_benchmarks.py  # Paired statistical comparison of benchmark runs
├── analyze_spread.py      # Cross-model leaderboard vs baseline + failure taxonomy
├── visualize_results.py   # Matplotlib CSV plotter
├── serve_dashboard.py     # CORS-enabled file server for dashboard
├── obs_record.py          # OBS recording start/stop/status via obs-websocket (per-model files)
├── obs_studio.py          # OBS scene setup (Game/Dashboard/PiP/Vertical) + live score ticker
├── replay_ticks.py        # Replay a run's tick snapshots into the dashboard (for capture)
└── capture_run_media.sh   # During-run game-window stills + tick snapshots
# (post-run Playwright dashboard recording lives in the rle-media repo: capture/record_dashboard.mjs)
docker/
├── Dockerfile             # HeadlessRim + Xvfb (debian:bookworm-slim)
├── docker-compose.yml     # Volume mounts for game files, mods, saves
├── entrypoint.sh          # Xvfb → RimWorld → RIMAPI healthcheck
└── README.md              # Docker setup prerequisites and troubleshooting

## Related Repos

- [felix-agent-sdk](https://github.com/AppSprout-dev/felix-agent-sdk) — Agent framework (LLMAgent, CentralPost, HelixGeometry, providers)
- [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) — C# RimWorld mod (REST API + SSE). [Our fork](https://github.com/AppSprout-dev/RIMAPI) has the `rle-testing` branch with extra endpoints pending upstream merge.
- [rimapi-dashboard](https://github.com/AppSprout-dev/rimapi-dashboard) — React dashboard with 5 RLE widgets. Runs on :3000, reads from :9000.
- [rle-harness-template](https://github.com/AppSprout-dev/rle-harness-template) — Template repo for a harness plugin (RLE CI installs it as the plugin-API contract test).
- [rle-harness-opencode](https://github.com/AppSprout-dev/rle-harness-opencode) — OpenCode (`opencode serve` + HTTP API) as a harness over the RLE MCP server.
- [rle-harness-grok-build](https://github.com/AppSprout-dev/rle-harness-grok-build) — Grok Build (headless `grok -p`, session resumed per tick) as a harness over the RLE MCP server.

## RIMAPI Fork Status

We contribute upstream to IlyaChichkov/RIMAPI. PRs #52-54, #60, #63, #65 all merged.

The `rle-testing` branch tracks upstream develop. We always build from `rle-testing` and deploy the DLL to the Workshop folder — this is our active development workflow.

To restore the original Workshop DLL: rename `RIMAPI.dll.upstream-backup` back to `RIMAPI.dll` in `C:\Steam\steamapps\workshop\content\294100\3593423732\1.6\Assemblies\`.
```
