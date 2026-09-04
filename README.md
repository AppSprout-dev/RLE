# RLE — RimWorld Learning Environment

Multi-agent benchmark where 7 Felix Agent SDK role-specialized LLM agents manage a RimWorld colony. Think [FLE](https://github.com/chenhao-wang/FLE) (Factorio Learning Environment) but for **multi-agent coordination under uncertainty**.

## What makes this different

- **7 agents, not 1** — MapAnalyst (spatial reasoning), ResourceManager, DefenseCommander, ResearchDirector, SocialOverseer, ConstructionPlanner, MedicalOfficer coordinate through a hub-spoke communication network
- **Spatial awareness** — deterministic terrain analysis from the game map tells agents exactly where to build, farm, and mine
- **Stochastic environment** — raids, plague, mental breaks, weather. Agents adapt, not just optimize
- **Helix-driven strategy** — agents shift from exploration (diverse strategies) to synthesis (decisive actions) as the colony progresses
- **Provider-agnostic** — runs on a free local 4B model or a cloud 30B, same architecture

## Architecture

```
RimWorld (game)
    ↕ Harmony patches
RIMAPI mod (C# REST :8765 + SSE events)
    ↕ httpx async + SSE
RLE Orchestrator
    ↕ CentralPost hub-spoke
    MapAnalyst → spatial analysis (runs first)
    6 Role Agents (parallel deliberation)
    ↕ OpenAI-compatible API
LLM (Nemotron 4B local / 30B cloud / Anthropic / OpenAI)
```

## The 7 Agents

| Agent | Domain | Key Actions |
|-------|--------|-------------|
| **MapAnalyst** | Spatial reasoning (runs first) | Produces MAP_SUMMARY with verified build/farm/stockpile coordinates |
| ResourceManager | Food, materials, power | work_priority, growing_zone, stockpile_zone, designate_area |
| DefenseCommander | Raids, drafting | draft, move |
| ResearchDirector | Tech tree | research_target, work_priority |
| SocialOverseer | Mood, recreation | time_assignment, work_priority |
| ConstructionPlanner | Buildings, walls | blueprint, designate_area, work_priority |
| MedicalOfficer | Injuries, disease | bed_rest, tend, work_priority |

## Prerequisites

You need four things set up:

1. **RimWorld** (Steam) with **Harmony** and **[RIMAPI](https://github.com/IlyaChichkov/RIMAPI)** mods subscribed and **enabled** in the Mods menu. Load order: Harmony → Core → (DLCs) → RIMAPI.
2. **LLM provider** — [LM Studio](https://lmstudio.ai/) (local, free) or [OpenRouter](https://openrouter.ai/) (cloud)
3. **Python 3.14+** with [uv](https://docs.astral.sh/uv/)
4. **Save file** — `rle_crashlanded_v1` in RimWorld's save folder (the scenario auto-loads it)

> **RIMAPI note:** The Workshop version may not have our contributed endpoints yet. See [CLAUDE.md](CLAUDE.md) for instructions on building and deploying our fork DLL.

### Verify

```bash
# Start RimWorld, load into a colony, then:
curl http://localhost:8765/api/v1/game/state   # RIMAPI (must be in-game, not main menu)
curl http://localhost:1234/v1/models            # LM Studio (if using local)
```

## Quick Start

### Install

```bash
git clone https://github.com/AppSprout-dev/RLE.git
cd RLE
uv sync --extra dev
```

### Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` with your setup:

```bash
# LM Studio (local, free)
OPENAI_API_KEY=lm-studio
PROVIDER=openai
MODEL=unsloth/nvidia-nemotron-3-nano-4b
PROVIDER_BASE_URL=http://localhost:1234/v1

# -- OR --

# OpenRouter (cloud)
OPENAI_API_KEY=sk-or-v1-your-key-here
PROVIDER=openai
MODEL=nvidia/nemotron-3-super-120b-a12b
PROVIDER_BASE_URL=https://openrouter.ai/api/v1
```

**Important:** For OpenRouter, `OPENAI_API_KEY` must be your OpenRouter API key. The OpenAI SDK reads this env var directly. CLI flags (`--provider`, `--model`, `--base-url`) override `.env` values.

### Run a live scenario

```bash
# Local (LM Studio, Nemotron Nano 4B)
python scripts/run_scenario.py crashlanded \
  --provider openai \
  --model unsloth/nvidia-nemotron-3-nano-4b \
  --base-url http://localhost:1234/v1 \
  --no-think --no-pause --visualize --ticks 10 \
  --output results/live --tick-interval 30

# Cloud (OpenRouter, Nemotron 30B)
OPENAI_API_KEY=<your-openrouter-key> \
python scripts/run_scenario.py crashlanded \
  --provider openai \
  --model nvidia/nemotron-3-nano-30b-a3b \
  --base-url https://openrouter.ai/api/v1 \
  --no-think --no-pause --visualize --ticks 10 \
  --output results/live --tick-interval 30
```

The scenario will:
1. Load the save file (`rle_crashlanded_v1`)
2. Wait for the game to be ready
3. Unforbid all starting items
4. Unpause and start running agents

### Key flags

| Flag | What it does |
|------|-------------|
| `--no-think` | Required for thinking models (Nemotron, Qwen). Skips reasoning chain. |
| `--no-pause` | Game runs continuously via SSE. Without this, game pauses each tick. |
| `--output DIR` | Exports `latest_tick.json` for the dashboard. |
| `--tick-interval N` | Seconds between ticks. 30s recommended for cloud models. |
| `--visualize` | Shows terminal helix visualization. |
| `--no-agent` | Baseline mode — no agents, colony runs unmanaged. |
| `--sequential` | Agents deliberate one at a time instead of in parallel. |

### Dashboard (optional, 3 terminals)

```bash
# Terminal 1: Run scenario with --output
python scripts/run_scenario.py crashlanded --output results/live ...

# Terminal 2: Serve tick data (CORS-enabled file server on :9000)
python scripts/serve_dashboard.py results/live

# Terminal 3: React dashboard on :3000
cd ../rimapi-dashboard && bun run start
# Open http://localhost:3000, add the 5 RLE widgets
```

### Other commands

```bash
# Full benchmark (mock game state, real LLM)
python scripts/run_benchmark.py --smoke-test --ticks 10

# List scenarios
python scripts/run_scenario.py --list

# Visualize CSV results
python scripts/visualize_results.py results/ --all

# Cross-model leaderboard vs the pinned baseline (after a spread)
python scripts/analyze_spread.py --spread-dir results/spread
```

## Benchmark Results

**11-model spread** — Crashlanded, 10 ticks, seed 42, 2026-06-11. **N=1, content-first — not statistically valid (no confidence intervals). Winners advance to N=4; N=4 is not published.** Ranked by mean composite across the run. Featured numbers live on the [HF card](https://huggingface.co/datasets/AppSprout/rle-benchmarks) and [rle.appsprout.dev](https://rle.appsprout.dev) (same `site_data.json` payload).

| # | Model | Mean | Final | vs baseline | Cost |
|---|-------|------|-------|-------------|------|
| 1 | Grok 4.3 | **0.836** | 0.804 | −0.004 | $0.36 |
| 2 | Mistral Medium 3.5 | 0.827 | 0.804 | −0.004 | $0.73 |
| 3 | Gemini 3.5 Flash | 0.815 | 0.774 | −0.013 | $2.28 |
| 4 | Qwen3.7 Max | 0.805 | 0.783 | −0.011 | $0.75 |
| 5 | Claude Fable 5 | 0.805 | 0.721 | −0.015 | ~$5.48 |
| 6 | Nemotron 3 Super 120B | 0.804 | 0.793 | −0.006 | $0.12 |
| 7 | Claude Opus 4.8 | 0.801 | 0.710 | −0.009 | ~$1.83 |
| 8 | GLM-5.1 | 0.782 | 0.740 | +0.028 | $0.94 |
| 9 | GPT-5.5 | 0.764 | 0.624 | −0.015 | $4.00 |
| 10 | DeepSeek-V4 Pro | 0.716 | 0.610 | −0.021 | $0.52 |
| 11 | Kimi K2.6 | 0.686 | 0.638 | −0.034 | $1.22 |

Measured against a pinned no-agent baseline (4 seeds, mean time-to-end 8.0 days). **1 of 11 models beat the no-agent baseline** (GLM-5.1). Highest mean composite is not the same as beating baseline. Costs marked `~` are token-count estimates (subscription-billed); unmarked costs are OpenRouter billed.

## Scenarios

| # | Name | Difficulty | Duration |
|---|------|-----------|----------|
| 01 | Crashlanded Survival | easy | 30 days |
| 02 | First Winter | medium | 60 days |
| 03 | Toxic Fallout | hard | 20 days |
| 04 | Raid Defense | hard | 15 days |
| 05 | Plague Response | hard | 20 days |
| 06 | Ship Launch | extreme | 120 days |

## Scoring

9 metrics, weighted composite (`SCORING_VERSION = "1.2"`; scenarios can override weights):

| Metric | Default Weight | What it measures |
|--------|---------------|------------------|
| survival | 0.24 | alive / started colonists |
| threat_response | 0.14 | draft response speed |
| mood | 0.12 | avg colonist mood |
| food_security | 0.10 | days of food (10+ = 1.0) |
| wealth | 0.08 | wealth growth ratio |
| research | 0.08 | % research tree completed |
| self_sufficiency | 0.10 | power + food + population stability |
| efficiency | 0.06 | executed / proposed writes per tick |
| plan_coherence | 0.08 | 1 − contradictory executed writes / executed writes per tick |

Both process metrics (`efficiency`, `plan_coherence`) are computed from the writes that actually reached RIMAPI, so any harness is scored the same way, and both return a neutral 0.5 for ticks with no writes so the unmanaged baseline earns no free points. The pre-1.2 `coordination` / `communication_efficiency` metrics were removed because they were ≈1.0 by construction (issue #51).

## Development

```bash
pytest                              # Run all tests
ruff check src/ tests/ scripts/     # Lint
mypy src/                           # Type check
```

## Related Repos

| Repo | What | Notes |
|------|------|-------|
| [felix-agent-sdk](https://github.com/AppSprout-dev/felix-agent-sdk) | Agent framework (LLMAgent, CentralPost, HelixGeometry, providers) | pip dependency |
| [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) | C# RimWorld mod (REST API + SSE) | We contribute upstream. [Our fork](https://github.com/AppSprout-dev/RIMAPI) has `rle-testing` branch. |
| [rimapi-dashboard](https://github.com/AppSprout-dev/rimapi-dashboard) | React dashboard with RLE widgets | Runs on :3000, reads tick data from :9000 |

## License

MIT

---

Built by [AppSprout](https://github.com/AppSprout-dev) with [Claude Code](https://claude.com/claude-code)
