# RLE — RimWorld Learning Environment

A **harness × model** benchmark: swappable agent harnesses manage a RimWorld colony under uncertainty and are scored on the same footing against an unmanaged baseline. Think [FLE](https://github.com/chenhao-wang/FLE) (Factorio Learning Environment) but stochastic, multi-agent-capable, and with the *harness* — not just the model — as a first-class variable.

## What makes this different

- **Harnesses are swappable like models** — `--harness felix` (the original 7-agent Felix SDK stack), `--harness baseline` (unmanaged colony), or any harness package installed from PyPI/GitHub (`rle-harness-<tool>`); the core never imports an agent framework
- **Harness-agnostic scoring** — process metrics read the writes that reached the game, not any harness's internal messaging; scenarios, saves and the composite are identical for every harness
- **Spatial awareness** — deterministic terrain analysis from the game map gives every harness verified build/farm/stockpile coordinates (MAP_SUMMARY)
- **Stochastic environment** — raids, plague, mental breaks, weather. Harnesses adapt, not just optimize
- **Paired against a real baseline** — every run is compared to RimWorld's own pawn AI on the same save
- **Provider-agnostic** — runs on a free local 4B model or a cloud 30B, same environment

## Architecture

```
RimWorld (game)
    ↕ Harmony patches
RIMAPI mod (C# REST :8765 + SSE events)
    ↕ httpx async + SSE
RLEGameLoop (environment: pause → state → harness.step → execute → score → unpause)
    ↕ Harness protocol (rle.harness) — discovered via the `rle.harnesses` entry-point group
    ├─ felix     MapAnalyst → 6 role agents over CentralPost, merged by ActionResolver   [in tree, extra `felix`]
    ├─ baseline  unmanaged colony                                                        [in tree]
    └─ <tool>    external coding agents attached over the RimAPI MCP server (rle-mcp)    [own repos]
    ↕ OpenAI-compatible / Anthropic / local API (provider + model are strings; the harness interprets them)
LLM
```

```bash
python scripts/run_benchmark.py --harness list          # what is installed
python scripts/run_benchmark.py --harness felix --harness baseline --smoke-test
```

Writing a harness: see [docs/harness-plugins.md](docs/harness-plugins.md). Third-party harnesses (OpenCode, Grok Build, ...) live in their own `AppSprout-dev/rle-harness-*` repos and are installed with `pip`, never committed here.

## The Felix harness: 7 agents

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
uv sync --extra dev --extra felix     # core + the Felix harness
# add --extra mcp for the RimAPI MCP server used by external coding-agent harnesses
```

Core is framework-free; `felix-agent-sdk` is an optional extra. Without it, `--harness felix` shows as unavailable in `--harness list` and everything else still runs.

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
| `--harness NAME` | Which harness decides (default `felix`; `--harness list` shows installed plugins). |
| `--harness-opt K=V` | Harness-specific option, validated by the plugin (e.g. `role_timeout_s=90`). |
| `--no-agent` | Baseline mode — alias for `--harness baseline`, colony runs unmanaged. |
| `--visualize` | [felix] Shows terminal helix visualization. |
| `--sequential` | [felix] Agents deliberate one at a time instead of in parallel. |
| `--tick-timeout N` | Loop-level cap on a whole harness step (seconds). |

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
