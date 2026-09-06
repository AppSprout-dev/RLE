# RLE — RimWorld Learning Environment

## ELI5

RLE is a public research benchmark — not a product — where AI agent setups try to keep a RimWorld colony alive. The published leaderboard is one 11-model Crashlanded run (2026-06-11, N=1, seed 42, 10 ticks) on the `felix` harness at scoring 1.1 — Grok 4.3 leads at mean composite 0.836; it is content-first and not statistically valid. Winners advance to N=4; N=4 is not published. Those rows are not comparable to scoring 1.2. Harness × model and scoring 1.2 are how the code works now; that matrix is not a published result yet. Full table: [Benchmark Results](#benchmark-results).

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
    ├─ raw-grok  MODEL BASELINE: stock grok binary, TURN_RULES only                      [in tree, extra `mcp`]
    └─ <tool>    external coding agents attached over the RimAPI MCP server (rle-mcp)    [own repos]
    ↕ OpenAI-compatible / Anthropic / local API (provider + model are strings; the harness interprets them)
LLM
```

```bash
python scripts/run_benchmark.py --harness list          # what is installed
python scripts/run_benchmark.py --harness felix --harness baseline --smoke-test
```

Writing a harness: see [docs/harness-plugins.md](docs/harness-plugins.md). Third-party harnesses (OpenCode, Grok Build, ...) live in their own `AppSprout-dev/rle-harness-*` repos and are installed with `pip`, never committed here.

## Harnesses

The benchmark has two axes. `--model` picks the LLM; `--harness` picks the decision architecture around it. Every harness gets the same scenarios, saves, neutral scenario brief (goals, state, MAP_SUMMARY, action catalog) and scoring, and is paired against the same unmanaged baseline. Leaderboard rows are `harness/model`.

| Harness | Where | What it is | Install |
|---------|-------|------------|---------|
| `felix` | this repo (extra `felix`) | MapAnalyst + 6 role agents over Felix SDK CentralPost, merged by ActionResolver — the original RLE stack. Roster ablation: `--harness-opt roles=` / `exclude_agent=`. See [docs/harness-felix.md](docs/harness-felix.md). | `uv sync --extra felix` |
| `baseline` | this repo | Unmanaged colony (RimWorld's own pawn AI) — the paired control | built in |
| `raw-grok` | this repo (extra `mcp`) | **Model baseline** — stock `grok` binary, one `HeadlessCliHarness` turn per tick, `TURN_RULES` only. Not a product harness; do not compare to `felix` or external coding-agent packages as an architecture. | `uv sync --extra mcp`; `grok` on PATH |
| `opencode` | [rle-harness-opencode](https://github.com/AppSprout-dev/rle-harness-opencode) | [OpenCode](https://opencode.ai) coding agent, one prompt per tick, acting through the RLE MCP tools | `uv pip install git+https://github.com/AppSprout-dev/rle-harness-opencode` |
| `grok-build` | [rle-harness-grok-build](https://github.com/AppSprout-dev/rle-harness-grok-build) | [Grok Build](https://github.com/xai-org/grok-build) coding agent, headless `grok -p` per tick, acting through the RLE MCP tools | `uv pip install git+https://github.com/AppSprout-dev/rle-harness-grok-build` |
| `template` | [rle-harness-template](https://github.com/AppSprout-dev/rle-harness-template) | Copy-me starting point for your own harness | `uv pip install git+https://github.com/AppSprout-dev/rle-harness-template` |

```bash
python scripts/run_benchmark.py --harness list                                  # installed plugins + availability
python scripts/run_benchmark.py --harness felix --harness opencode --model openai/gpt-4o --runs 4
python scripts/run_scenario.py crashlanded --harness grok-build --model grok-4.6 --tick-interval 30
python scripts/run_scenario.py crashlanded --harness felix --harness-opt no_think=true --harness-opt parallel=false
python scripts/run_scenario.py crashlanded --harness raw-grok --model grok-4.6 --seed 42 --ticks 10 \
  --harness-opt binary=grok --harness-opt turn_timeout_s=300 \
  --harness-opt mcp_container_reachable=true \
  --harness-opt mcp_advertise_url=http://host.docker.internal:8766/mcp
```

Coding-agent harnesses attach to RLE over MCP: RLE hosts a RimAPI tool server in-process (`rle.mcp`, extra `mcp`), the agent calls `get_brief`, then write tools (`work_priority`, `blueprint`, ...), then `end_turn`; the writes that reached the game are what gets scored. `--smoke-test` needs none of the binaries — each plugin ships a scripted stand-in that plays the same round trip.

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
# Smoke test: mock game state + each harness's mock agent (no LLM, no RimWorld)
python scripts/run_benchmark.py --smoke-test --ticks 10 --harness felix --harness baseline

# Harness matrix against a live game, 4 paired runs each
python scripts/run_benchmark.py --harness felix --harness opencode --runs 4 --output results/matrix/

# List scenarios / harnesses
python scripts/run_scenario.py --list
python scripts/run_benchmark.py --harness list

# Visualize CSV results
python scripts/visualize_results.py results/ --all

# Cross-model leaderboard vs the pinned baseline (after a spread)
python scripts/analyze_spread.py --spread-dir results/spread
```

## Benchmark Results

**11-model spread, `felix` harness, scoring 1.1** — Crashlanded, 10 ticks, seed 42, 2026-06-11. **N=1, content-first — not statistically valid (no confidence intervals). Winners advance to N=4; N=4 is not published.** Ranked by mean composite across the run. Featured numbers live on the [HF card](https://huggingface.co/datasets/AppSprout/rle-benchmarks) and [rle.appsprout.dev](https://rle.appsprout.dev) (same `site_data.json` payload).

These rows predate the harness axis and scoring 1.2: they were all produced by the Felix harness and include the since-removed `coordination` / `communication_efficiency` metrics, so they are not comparable to 1.2 runs. The next published spread will be a harness × model matrix at scoring 1.2.

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

`plan_coherence` is measured after whatever coordination a harness does internally, so it is a floor a competent harness clears rather than a way to rank harnesses against each other; the colony outcome metrics (86% of the weight) are what separate them. Harness-internal process data (Felix's CentralPost traffic, resolver conflicts, a coding agent's tool-call count) is recorded in the event log as diagnostics, not scored.

Every run also records `harness`, `harness_options`, `harness_versions`, per-tick step latency and cost, and a `harness_failed` flag when RIMAPI plumbing errors (null-ref cascades, invalid plant defs) occurred; quarantined runs are excluded from leaderboard means.

## Development

```bash
uv sync --extra dev --extra felix --extra mcp
pytest                                      # Run all tests (Felix-only modules skip without the extra)
ruff check src/ tests/ scripts/             # Lint
mypy src/                                   # Type check
python scripts/check_harness_boundary.py    # felix confined to harness/felix; no third-party harness code in tree
```

CI runs the suite twice — with and without the `felix` extra — plus a contract job that installs [rle-harness-template](https://github.com/AppSprout-dev/rle-harness-template) from GitHub and checks it appears in `--harness list` and passes `--smoke-test`.

## Related Repos

| Repo | What | Notes |
|------|------|-------|
| [rle-harness-template](https://github.com/AppSprout-dev/rle-harness-template) | Template for a harness plugin | Start here to add a harness; RLE CI installs it as the plugin-API contract test |
| [rle-harness-opencode](https://github.com/AppSprout-dev/rle-harness-opencode) | OpenCode as a harness | `opencode serve` + HTTP API over the RLE MCP server |
| [rle-harness-grok-build](https://github.com/AppSprout-dev/rle-harness-grok-build) | Grok Build as a harness | headless `grok -p`, session resumed per tick, over the RLE MCP server |
| [felix-agent-sdk](https://github.com/AppSprout-dev/felix-agent-sdk) | Agent framework behind the `felix` harness (LLMAgent, CentralPost, HelixGeometry, providers) | optional extra `felix` |
| [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) | C# RimWorld mod (REST API + SSE) | We contribute upstream. [Our fork](https://github.com/AppSprout-dev/RIMAPI) has `rle-testing` branch. |
| [rimapi-dashboard](https://github.com/AppSprout-dev/rimapi-dashboard) | React dashboard with RLE widgets | Runs on :3000, reads tick data from :9000 (`latest_tick.json` now carries `harness` + `extras`) |

## License

MIT

---

Built by [AppSprout](https://github.com/AppSprout-dev) with [Claude Code](https://claude.com/claude-code)
