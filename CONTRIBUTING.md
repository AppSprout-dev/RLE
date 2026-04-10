# Contributing to RLE

## Setup

```bash
git clone https://github.com/AppSprout-dev/RLE.git
cd RLE
uv sync --extra dev
pytest  # should pass 326+ tests
```

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

## Development workflow

1. Create a branch from `master`
2. Make changes
3. Run `pytest`, `ruff check src/ tests/ scripts/`, and `mypy src/`
4. Commit with a descriptive message
5. Open a PR against `master`

CI runs lint + type check + tests + smoke test on every push/PR.

## Running locally

### Prerequisites

| Service | Purpose | Default Port |
|---------|---------|-------------|
| LM Studio | LLM inference | 1234 |
| RimWorld + RIMAPI mod | Game state + actions | 8765 |
| Dashboard (optional) | Live visualization | 3000 |
| Tick data server (optional) | Dashboard data feed | 9000 |
| Docker (optional) | Headless benchmarks | 8765 |

### Recommended local model

**Nemotron 3 Nano 4B** (Q4_K_M, ~2.5GB VRAM). 100% parse rate, fits on 8GB cards.

LM Studio settings: Flash Attention ON, Context 10000, GPU Offload max, Keep in Memory ON.

### Quick test (no RimWorld needed)

```bash
# Smoke test — tests the full pipeline with fake game state
python scripts/run_benchmark.py --smoke-test --ticks 3

# Smoke test with real LLM (needs LM Studio running)
OPENAI_API_KEY=lm-studio python scripts/run_benchmark.py \
  --smoke-test --provider openai \
  --model unsloth/nvidia-nemotron-3-nano-4b \
  --base-url http://localhost:1234/v1 \
  --no-think --ticks 3
```

### Live game test

```bash
# Start RimWorld with RIMAPI mod, load a colony, then:
OPENAI_API_KEY=lm-studio python scripts/run_scenario.py crashlanded_survival \
  --provider openai \
  --model unsloth/nvidia-nemotron-3-nano-4b \
  --base-url http://localhost:1234/v1 \
  --no-think --visualize --ticks 10
```

### Docker benchmark (headless, no display)

```bash
# Build image (see docker/README.md for prerequisites)
docker compose -f docker/docker-compose.yml up -d

# Run benchmark against container
python scripts/run_benchmark.py --docker --runs 4 --output results/docker/
```

### OpenRouter (cloud, no local GPU needed)

```bash
OPENAI_API_KEY=<your-openrouter-key> python scripts/run_benchmark.py \
  --provider openai \
  --model nvidia/nemotron-3-super-120b-a12b \
  --base-url https://openrouter.ai/api/v1 \
  --no-think --ticks 10 --output results/
```

## Code conventions

- **Python 3.14+** — `uv` for package management, `hatchling` build backend
- **mypy strict** — all code must pass `mypy src/` with `strict = true`
- **Async-first** — httpx AsyncClient, async game loop
- **Pydantic v2** — frozen models for all data structures
- **No `Any` types** in metric contexts — use `TYPE_CHECKING` imports to break circular deps
- **No scipy/numpy** — stdlib only for statistics (see ADR-003)
- **Parallel by default** — agents deliberate concurrently via `asyncio.to_thread`
- **JSON repair** — LLM output goes through `json_repair.py` before parsing
- **CentralPost for inter-agent context** — not orchestrator-passed lists
- **SSE events in agent context** — each role agent gets relevant events in `filter_game_state()`

## Adding a new agent

1. Create `src/rle/agents/your_agent.py` subclassing `RimWorldRoleAgent`
2. Set `ROLE_NAME`, `ALLOWED_ACTIONS`, `TEMPERATURE_RANGE` class vars
3. Implement `filter_game_state()`, `_get_task_description()`, `_get_role_description()`
4. Add `"recent_events": self._format_events("relevant_event_type")` to `filter_game_state()`
5. Register in `src/rle/agents/__init__.py` — add to `_ROLE_AGENTS` and `AGENT_DISPLAY`
6. Add tests in `tests/unit/test_role_agents.py`

## Adding a new scenario

1. Create `src/rle/scenarios/definitions/NN_your_scenario.yaml`
2. Follow the schema: name, description, difficulty, expected_duration_days, initial_population, victory_conditions, failure_conditions, max_ticks, scoring_weights (include all 10 metrics)
3. The loader auto-discovers YAML files — no registration needed

## Project structure

```
src/rle/
├── config.py              # RLEConfig (env vars, provider, helix preset)
├── docker.py              # Docker container lifecycle + RIMAPI health checks
├── rimapi/                # RIMAPI client + SSE + schemas
├── agents/                # 7 agents (MapAnalyst + 6 role) + base class + JSON repair
├── orchestration/         # Game loop, state manager, executor, resolver
├── scoring/               # 10 metrics, composite scorer, bootstrap CIs, CSV recorder
├── tracking/              # Cost tracking, event log, leaderboard, W&B/HF loggers
└── scenarios/             # YAML schema, loader, evaluator, 6 definitions
docker/                    # HeadlessRim Dockerfile, compose, entrypoint
.github/workflows/         # CI (lint+test+smoke) and benchmark (Docker) workflows
```

## Key dependencies

- [felix-agent-sdk](https://github.com/AppSprout-dev/felix-agent-sdk) >= 0.2.1
- [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) C# mod
- httpx, pydantic >= 2.0, pyyaml
- Optional: wandb, huggingface-hub (`uv sync --extra tracking`)

## Questions?

Open an issue or reach out on Discord.
