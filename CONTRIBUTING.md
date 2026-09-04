# Contributing to RLE

## Setup

```bash
git clone https://github.com/AppSprout-dev/RLE.git
cd RLE
uv sync --extra dev --extra felix
pytest  # should pass 458+ tests
```

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/).

## Development workflow

1. Create a branch from `master`
2. Make changes
3. Run `pytest`, `ruff check src/ tests/ scripts/`, and `mypy src/`
4. Commit using [Conventional Commits](https://www.conventionalcommits.org/) (see below)
5. Open a PR against `master` — **regular merge commits, never squash** (preserves per-commit history)

CI runs lint + type check + tests + smoke test on every push/PR.

### Commit messages drive versioning

Versioning is automated by [release-please](https://github.com/googleapis/release-please): commit prefixes determine the version bump and changelog entry. Don't hand-edit `version` in `pyproject.toml`.

| Prefix | Example | Effect (pre-1.0) |
|--------|---------|------------------|
| `feat:` | `feat: add toxic fallout scenario` | minor bump |
| `fix:` | `fix: correct food_security divisor` | patch bump |
| `feat!:` / `BREAKING CHANGE:` | breaking API change | minor bump (stays <1.0) |
| `docs:` `chore:` `refactor:` `test:` `ci:` `perf:` | tidy-ups | no release |

release-please keeps an open "release PR" accumulating changes; merging it tags the version and publishes a GitHub release with generated notes.

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
# Smoke test — full pipeline with fake game state and each harness's mock agent
# (no LLM calls; proves plumbing, not colony management)
python scripts/run_benchmark.py --smoke-test --ticks 3 --harness felix --harness baseline

# Which harnesses are installed and usable here
python scripts/run_benchmark.py --harness list

# Run the suite as CI does, with and without the felix extra
uv sync --extra dev --extra felix --extra mcp && pytest
UV_PROJECT_ENVIRONMENT=.venv-nofelix uv sync --extra dev --extra mcp && \
  UV_PROJECT_ENVIRONMENT=.venv-nofelix uv run --no-sync pytest
python scripts/check_harness_boundary.py
```

`--smoke-test` always uses mock LLMs. To exercise a real model against the fake game state, run a real harness with `--ticks` small against a live RIMAPI instead (below).

### Live game test

```bash
# Start RimWorld with RIMAPI mod, load a colony, then:
OPENAI_API_KEY=lm-studio python scripts/run_scenario.py crashlanded_survival \
  --harness felix \
  --provider openai \
  --model unsloth/nvidia-nemotron-3-nano-4b \
  --base-url http://localhost:1234/v1 \
  --no-think --visualize --ticks 10

# Same scenario, a coding-agent harness (needs the plugin + its binary installed)
uv pip install git+https://github.com/AppSprout-dev/rle-harness-opencode
python scripts/run_scenario.py crashlanded_survival --harness opencode --model openai/gpt-4o --ticks 10
```

### Testing a harness plugin

External plugins depend on RLE core and use `rle.testing`:

```python
from rle.testing import run_harness_smoke

async def test_smoke() -> None:
    report = await run_harness_smoke("your-harness", ticks=3)
    assert report.ok
```

`run_harness_smoke` builds `plugin.smoke(...)`, drives it through `RLEGameLoop` against `MockRimAPI`, and returns the tick results plus every POST the harness made. Coding-agent plugins return `rle.testing.scripted_agent.ScriptedMcpHarness` from `smoke()` so the MCP round trip is covered without the binary. See [rle-harness-template](https://github.com/AppSprout-dev/rle-harness-template) for the full layout.

### Docker benchmark (headless, no display)

```bash
# Build image (see docker/README.md for prerequisites)
docker compose -f docker/docker-compose.yml up -d

# Run a harness x model matrix against the container, 4 paired runs each
python scripts/run_benchmark.py --docker --runs 4 --harness felix --harness baseline --output results/docker/
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
- **Core is framework-free** — `felix_agent_sdk` is imported only under `src/rle/harness/felix/`; everything else must run with the `felix` extra uninstalled (the `test-no-felix` CI job checks this)
- **Harness-agnostic scoring** — metrics read the executed write stream, never a harness's internal messaging
- **Parallel by default (felix)** — role agents deliberate concurrently
- **JSON repair** — LLM output goes through `json_repair.py` before parsing
- **CentralPost for inter-agent context (felix)** — not orchestrator-passed lists
- **SSE events in agent context** — the loop passes each tick's events to `harness.step()`; Felix role agents get relevant ones in `filter_game_state()`

## Adding a new harness

Harnesses are plugins discovered through the `rle.harnesses` entry-point group. Only
RLE-authored harnesses (`baseline`, `felix`) live in this repo; a harness that wraps a
third-party tool gets its own repo — start from
[rle-harness-template](https://github.com/AppSprout-dev/rle-harness-template) and read
`docs/harness-plugins.md`. `scripts/check_harness_boundary.py` (CI) rejects third-party
harness code and stray `felix_agent_sdk` imports in this tree.

## Adding a new Felix role agent

1. Create `src/rle/harness/felix/agents/your_agent.py` subclassing `RimWorldRoleAgent`
2. Set `ROLE_NAME`, `ALLOWED_ACTIONS`, `TEMPERATURE_RANGE` class vars
3. Implement `filter_game_state()`, `_get_task_description()`, `_get_role_description()`
4. Add `"recent_events": self._format_events("relevant_event_type")` to `filter_game_state()`
5. Register in `src/rle/harness/felix/agents/__init__.py` (`_ROLE_AGENTS`, `AGENT_DISPLAY`) and the roster in `src/rle/harness/felix/build.py`
6. Add tests in `tests/unit/test_role_agents.py`

## Adding a new scenario

1. Create `src/rle/scenarios/definitions/NN_your_scenario.yaml`
2. Follow the schema: name, description, difficulty, expected_duration_days, initial_population, victory_conditions, failure_conditions, max_ticks, scoring_weights (all 9 metrics, summing to 1.0)
3. The loader auto-discovers YAML files — no registration needed

## Project structure

```
src/rle/
├── config.py              # RLEConfig (env vars; provider/model/harness as strings)
├── docker.py              # Docker container lifecycle + RIMAPI health checks
├── rimapi/                # RIMAPI client + SSE + schemas
├── agents/                # Harness-neutral action vocabulary + JSON repair
├── harness/               # Harness protocol, registry, CLI glue, brief, baseline, felix/ (extra), cli_base
├── mcp/                   # RimAPI as an MCP tool server + per-tick ledger (extra `mcp`)
├── testing/               # MockRimAPI, run_harness_smoke, ScriptedMcpHarness (for plugin authors)
├── orchestration/         # Game loop, save loader, state manager, executor, resolver
├── scoring/               # 9 metrics, coherence, composite scorer, bootstrap CIs, CSV recorder
├── tracking/              # Cost tracking, event log, leaderboard (harness×model), W&B/HF loggers
└── scenarios/             # YAML schema, loader, evaluator, 6 definitions
docker/                    # HeadlessRim Dockerfile, compose, entrypoint
.github/workflows/         # CI (lint+test+smoke) and benchmark (Docker) workflows
```

## Key dependencies

- [felix-agent-sdk](https://github.com/AppSprout-dev/felix-agent-sdk) >= 0.3.0
- [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) C# mod
- httpx, pydantic >= 2.0, pyyaml
- Optional: wandb, huggingface-hub (`uv sync --extra tracking`)

## Questions?

Open an issue or reach out on Discord.
