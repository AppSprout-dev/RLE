# RLE — RimWorld Learning Environment

Multi-agent benchmark where 6 Felix Agent SDK role-specialized LLM agents manage a RimWorld colony. Think FLE (Factorio Learning Environment) but for multi-agent coordination under uncertainty.

## Commands

- Install: `pip install -e ".[dev]"`
- Test: `pytest`
- Lint: `ruff check src/ tests/ scripts/`
- Type check: `mypy src/`
- Run scenario: `python scripts/run_scenario.py crashlanded_survival`
- Run benchmark: `python scripts/run_benchmark.py --output results/`
- Visualize: `python scripts/visualize_results.py results/ --all`
- List scenarios: `python scripts/run_scenario.py --list`

## Architecture

```
RimWorld ←→ RIMAPI mod (REST :8765) ←→ RimAPIClient (async httpx)
                                            ↕
                                     RLEGameLoop (orchestrator)
                                            ↕
                                     CentralPost (hub-spoke)
                                      ↕  ↕  ↕  ↕  ↕  ↕
                                     6 Role Agents (LLMAgent subclasses)
                                            ↕
                                     ActionResolver → merged ActionPlan
                                            ↕
                                     ActionExecutor → RIMAPI write calls
                                            ↕
                                     CompositeScorer → ScoreSnapshot per tick
                                            ↕
                                     ScenarioEvaluator → victory/defeat/timeout
```

**Turn-based loop**: pause → read state → 6 agents deliberate → resolve conflicts → execute → score → evaluate → unpause → repeat.

## Agents (map to roles, not colonists)

| Agent | Domain | Actions |
|-------|--------|---------|
| ResourceManager | Food, materials, power, hauling | set_work_priority, haul_resource, set_growing_zone, toggle_power |
| DefenseCommander | Raids, drafting, positioning | draft_colonist, undraft_colonist, move_colonist |
| ResearchDirector | Tech tree, researcher assignment | set_research_target, assign_researcher |
| SocialOverseer | Mood, recreation, mental breaks | set_recreation_policy, assign_social_activity |
| ConstructionPlanner | Buildings, walls, repairs | place_blueprint, cancel_blueprint |
| MedicalOfficer | Injuries, disease, medicine | assign_bed_rest, administer_medicine |

Each agent filters GameState to its domain, outputs a JSON ActionPlan with typed actions.

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
| mood | 0.15 | avg colonist mood |
| food_security | 0.10 | days of food (10+ = 1.0) |
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

## Conventions

- Async-first (httpx AsyncClient, async game loop)
- Pydantic v2 models with frozen=True for game state and results
- Felix Agent SDK for providers, agents, helix geometry, communication
- Tests use pytest-asyncio with auto mode
- Provider-agnostic: Anthropic, OpenAI, or local models via felix-agent-sdk

## Package Structure

```
src/rle/
├── config.py              # RLEConfig (pydantic-settings)
├── rimapi/                # RIMAPI async HTTP client + Pydantic schemas
├── agents/                # 6 role agents + base class + action schema
├── orchestration/         # Game loop, state manager, action executor/resolver
├── scoring/               # 8 metrics, composite scorer, CSV recorder
└── scenarios/             # YAML schema, loader, evaluator, 6 definitions
```
