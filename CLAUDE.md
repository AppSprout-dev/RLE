# RLE — RimWorld Learning Environment

Multi-agent benchmark where 6 Felix Agent SDK role-specialized LLM agents manage a RimWorld colony. Think FLE (Factorio Learning Environment) but for multi-agent coordination under uncertainty.

## Commands

- Install: `pip install -e ".[dev]"`
- Test: `pytest`
- Lint: `ruff check src/ tests/ scripts/`
- Type check: `mypy src/`
- List scenarios: `python scripts/run_scenario.py --list`
- Run scenario (live game): `python scripts/run_scenario.py crashlanded_survival --provider openai --model <model> --base-url <url> --no-think --visualize --ticks 10`
- Run scenario (mock): `python scripts/run_benchmark.py --dry-run --ticks 10`
- Run benchmark: `python scripts/run_benchmark.py --provider openai --model <model> --base-url <url> --no-think --ticks 10 --output results/`
- Serve dashboard: `python scripts/serve_dashboard.py results/live`
- Visualize CSV: `python scripts/visualize_results.py results/ --all`

## Architecture

```
RimWorld (game)
    ↕ Harmony patches
RIMAPI mod (REST :8765 + SSE /api/v1/events)
    ↕
RimAPIClient (httpx async) + RimAPISSEClient (event stream)
    ↕
RLEGameLoop
  pause → read state → drain SSE → inject events → route spoke messages
  → 6 agents deliberate (parallel) → resolve conflicts → execute actions
  → score → broadcast score → export tick JSON → render helix → unpause
    ↕
CentralPost hub-spoke (TASK_COMPLETE, STATUS_UPDATE, PHASE_ANNOUNCE)
 ↕  ↕  ↕  ↕  ↕  ↕
6 Role Agents (LLMAgent subclasses, read spoke + SSE context)
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

| Agent | Domain | Actions |
|-------|--------|---------|
| ResourceManager | Food, materials, power, hauling | set_work_priority, haul_resource, set_growing_zone, toggle_power |
| DefenseCommander | Raids, drafting, positioning | draft_colonist, undraft_colonist, move_colonist |
| ResearchDirector | Tech tree, researcher assignment | set_research_target, assign_researcher |
| SocialOverseer | Mood, recreation, mental breaks | set_recreation_policy, assign_social_activity |
| ConstructionPlanner | Buildings, walls, repairs | place_blueprint, cancel_blueprint |
| MedicalOfficer | Injuries, disease, medicine | assign_bed_rest, administer_medicine |

Each agent filters GameState to its domain, reads CentralPost spoke messages for inter-agent context, and outputs a JSON ActionPlan with typed actions.

## CentralPost Hub-Spoke Communication

Agents communicate through Felix SDK's CentralPost, not through the orchestrator:

- **Before deliberation**: `process_all_messages()` routes previous tick's messages to agent spoke inbound queues. Agents read via `_get_spoke_context()`.
- **After deliberation**: Each agent sends `TASK_COMPLETE` with role, summary, confidence, action types.
- **After scoring**: Hub broadcasts `STATUS_UPDATE` with composite score + all 8 metrics.
- **On phase change**: Hub broadcasts `PHASE_ANNOUNCE` when macro_time crosses 0.4 (exploration→analysis) or 0.7 (analysis→synthesis).

## SSE Events

RimAPISSEClient connects to `/api/v1/events` and buffers real-time game events (raids, deaths, mental breaks). Each tick:

1. GameStateManager drains SSE buffer → `pending_events`
2. Game loop injects events into all agents via `set_pending_events()`
3. Each agent's `filter_game_state()` includes role-relevant events as `"recent_events"`

Event routing: DefenseCommander gets `letter_received`/`pawn_killed`, MedicalOfficer gets `colonist_died`/`colonist_mental_break`, ResourceManager gets `colonist_ate`/`plant_harvested`, etc.

## Conflict Resolution (4 rules)

1. Emergency roles promoted during crises (DefenseCommander during raids, MedicalOfficer during plague)
2. Same-pawn conflicts: lowest action priority number wins
3. Role priority tiebreak (ResourceManager=3, DefenseCommander=3, MedicalOfficer=4, others=5)
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

| Provider | Example |
|----------|---------|
| OpenRouter (cloud) | `--provider openai --model nvidia/nemotron-3-super-120b-a12b --base-url https://openrouter.ai/api/v1` |
| LM Studio (local) | `--provider openai --model unsloth/nvidia-nemotron-3-nano-4b --base-url http://localhost:1234/v1` |
| Anthropic | `--provider anthropic --model claude-sonnet-4-5` |
| OpenAI | `--provider openai --model gpt-4o` |

Use `--no-think` for thinking models (Qwen3.5, Nemotron) — injects `</think>` assistant prefix to skip reasoning chain.

## Dashboard Integration

Game loop writes `latest_tick.json` each tick via `--output` flag. The rimapi-dashboard fork (React) has 5 RLE widgets:

- **Agent Status** — 6 agents with confidence bars, action counts, team confidence
- **Agent Decisions** — per-agent summaries and action chips
- **Helix Phase** — visual phase indicator (exploration/analysis/synthesis)
- **Score Timeline** — Chart.js line graph of 8 metrics + composite over ticks
- **Conflict Resolution** — proposed → resolved → executed → dropped pipeline

Setup: `python scripts/serve_dashboard.py results/live` (CORS-enabled :9000), then open `localhost:3000`.

## Conventions

- Async-first (httpx AsyncClient, async game loop)
- Parallel-first: 6 agents deliberate concurrently via `asyncio.to_thread` + `asyncio.gather` (`--sequential` to disable)
- Pydantic v2 models with frozen=True for game state and results
- Felix Agent SDK for providers, agents, helix geometry, CentralPost communication
- JSON repair + parse retry for LLM output resilience (strips think tags, trailing commas, extracts first JSON object)
- Real RIMAPI data via state adapters (mood, food, resources, weather computed from live endpoints; skills/traits/job not available from RIMAPI)
- Tests use pytest-asyncio with auto mode

## Package Structure

```
src/rle/
├── config.py              # RLEConfig (pydantic-settings)
├── rimapi/                # RIMAPI async HTTP client + SSE + Pydantic schemas
│   ├── client.py          # RimAPIClient (REST read/write + state adapters)
│   ├── schemas.py         # GameState, ColonistData, ResourceData, etc.
│   └── sse_client.py      # RimAPISSEClient (real-time event stream)
├── agents/                # 6 role agents + base class + action schema
│   ├── base_role.py       # RimWorldRoleAgent (spoke context, SSE events, JSON parsing)
│   ├── actions.py         # ActionType enum, Action, ActionPlan
│   ├── json_repair.py     # Strip think tags, trailing commas, extract JSON
│   ├── resource_manager.py
│   ├── defense_commander.py
│   ├── research_director.py
│   ├── social_overseer.py
│   ├── construction_planner.py
│   └── medical_officer.py
├── orchestration/         # Game loop, state manager, action executor/resolver
│   ├── game_loop.py       # RLEGameLoop (parallel deliberation, CentralPost, visualizer, dashboard export)
│   ├── state_manager.py   # GameStateManager (SSE drain, macro time, history)
│   ├── action_executor.py # Routes actions to RIMAPI write endpoints
│   └── action_resolver.py # 4-rule conflict resolution
├── scoring/               # 8 metrics, composite scorer, CSV recorder
└── scenarios/             # YAML schema, loader, evaluator, 6 definitions
scripts/
├── run_scenario.py        # Single scenario CLI
├── run_benchmark.py       # Full benchmark suite CLI
├── visualize_results.py   # Matplotlib CSV plotter
└── serve_dashboard.py     # CORS-enabled file server for dashboard
```
