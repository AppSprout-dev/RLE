# RLE — RimWorld Learning Environment

Multi-agent benchmark where 6 Felix Agent SDK role-specialized LLM agents manage a RimWorld colony. Think [FLE](https://github.com/chenhao-wang/FLE) (Factorio Learning Environment) but for **multi-agent coordination under uncertainty**.

## What makes this different

- **6 agents, not 1** — ResourceManager, DefenseCommander, ResearchDirector, SocialOverseer, ConstructionPlanner, MedicalOfficer coordinate through a hub-spoke communication network
- **Stochastic environment** — raids, plague, mental breaks, weather. Agents adapt, not just optimize
- **Helix-driven strategy** — agents shift from exploration (diverse strategies) to synthesis (decisive actions) as the colony progresses
- **Provider-agnostic** — runs on a free local 4B model or a cloud 120B, same architecture

## Architecture

```
RimWorld (game)
    ↕ Harmony patches
RIMAPI mod (C# REST :8765 + SSE events)
    ↕ httpx async + SSE
RLE Orchestrator (pause → read → deliberate → resolve → execute → score → unpause)
    ↕ CentralPost hub-spoke
Felix Agent SDK (6 role agents, parallel deliberation)
    ↕ OpenAI-compatible API
LLM (Nemotron 4B local / 120B cloud / Anthropic / OpenAI)
```

## The 6 Agents

| Agent | Domain | Actions |
|-------|--------|---------|
| ResourceManager | Food, materials, power, hauling | set_work_priority, haul_resource, set_growing_zone, toggle_power |
| DefenseCommander | Raids, drafting, positioning | draft_colonist, undraft_colonist, move_colonist |
| ResearchDirector | Tech tree, researcher assignment | set_research_target, assign_researcher |
| SocialOverseer | Mood, recreation, mental breaks | set_recreation_policy, assign_social_activity |
| ConstructionPlanner | Buildings, walls, repairs | place_blueprint, cancel_blueprint |
| MedicalOfficer | Injuries, disease, medicine | assign_bed_rest, administer_medicine |

## Quick Start

### Prerequisites

- Python 3.10+
- [LM Studio](https://lmstudio.ai/) with **Nemotron 3 Nano 4B** (Q4_K_M, ~2.5GB)
- RimWorld with [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) mod

### Install

```bash
git clone https://github.com/AppSprout-dev/RLE.git
cd RLE
pip install -e ".[dev]"
```

### Configure LM Studio

1. Download `unsloth/nvidia-nemotron-3-nano-4b` (GGUF, Q4_K_M)
2. Settings: Flash Attention ON, Context 10000, GPU Offload max, Keep in Memory ON
3. Start the server (default port 1234)

### Run

```bash
# Single scenario against live RimWorld colony
python scripts/run_scenario.py crashlanded_survival \
  --provider openai \
  --model unsloth/nvidia-nemotron-3-nano-4b \
  --base-url http://localhost:1234/v1 \
  --no-think --visualize

# Full benchmark (mock game state, real LLM)
python scripts/run_benchmark.py \
  --provider openai \
  --model unsloth/nvidia-nemotron-3-nano-4b \
  --base-url http://localhost:1234/v1 \
  --ticks 10 --no-think --output results/

# List available scenarios
python scripts/run_scenario.py --list
```

## Benchmark Results

Tested across 6 scenarios, 10 ticks each:

| Config | Model | Avg Score | Parse Rate | s/tick | Cost |
|--------|-------|----------|-----------|--------|------|
| Local (RX 5700 XT 8GB) | Nemotron Nano 4B | 0.738 | 100% | 41.7 | free |
| Local (RX 7800 XT 16GB) | Nemotron Nano 4B | 0.739 | 100% | 16.8 | free |
| OpenRouter (cloud) | Nemotron Super 120B | 0.739 | 99.4% | 4.7 | ~$0.09 |

Live game test (5 ticks, Crashlanded): 89% action execution rate, 100% parse rate, all colonists alive.

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

8 metrics, weighted composite (scenarios can override weights):

| Metric | Default Weight | What it measures |
|--------|---------------|------------------|
| survival | 0.25 | alive / started colonists |
| threat_response | 0.15 | draft response speed |
| mood | 0.15 | avg colonist mood |
| food_security | 0.10 | days of food (10+ = 1.0) |
| wealth | 0.10 | wealth growth ratio |
| research | 0.10 | % research tree completed |
| self_sufficiency | 0.10 | power + food + population stability |
| efficiency | 0.05 | action execution rate |

## Development

```bash
pytest                              # Run all tests (262)
ruff check src/ tests/ scripts/     # Lint
mypy src/                           # Type check
```

### Project Structure

```
src/rle/
├── config.py              # RLEConfig (pydantic-settings)
├── rimapi/                # RIMAPI async HTTP client + SSE + Pydantic schemas
├── agents/                # 6 role agents + base class + action schema
├── orchestration/         # Game loop, state manager, action executor/resolver
├── scoring/               # 8 metrics, composite scorer, CSV recorder
└── scenarios/             # YAML schema, loader, evaluator, 6 definitions
```

## Key Dependencies

- [felix-agent-sdk](https://github.com/AppSprout-dev/felix-agent-sdk) — agents, communication, helix geometry, providers
- [RIMAPI](https://github.com/IlyaChichkov/RIMAPI) — C# RimWorld mod exposing REST API
- httpx, pydantic, pyyaml

## License

MIT

---

Built by [AppSprout](https://github.com/AppSprout-dev) with [Claude Code](https://claude.com/claude-code)
