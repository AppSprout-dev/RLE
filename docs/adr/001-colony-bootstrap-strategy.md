# ADR-001: Colony Bootstrap Strategy

**Date:** 2026-03-30
**Status:** Accepted
**Deciders:** @jkbennitt, @calebisgross

## Decision

Agents must be able to bootstrap a colony from scratch, not just manage established colonies. This requires exposing the full RIMAPI endpoint surface (156+ endpoints) to agents and replacing the hardcoded ActionType enum with a dynamic, endpoint-based action system.

## Context

N=4 paired benchmark on Crashlanded Survival (Nemotron 30B-A3B, OpenRouter, speed 3, 30s tick interval) shows agents losing to unmanaged baseline:

```
Agent:    0.762 +/- 0.02
Baseline: 0.782 +/- 0.01
Delta:    -0.021 (p = 0.11)
```

Colonists wander instead of working. Root causes identified:

1. **Insufficient action vocabulary.** We use 15 of 156+ RIMAPI endpoints. Agents can set work priorities and create growing zones but cannot build structures, create stockpiles, or reliably assign jobs. A human player on Day 1 does 10+ things simultaneously; our agents can do 3.

2. **8 of 15 action handlers are broken.** All bugs are in our Python code (wrong field names, missing features, bad defaults), not in RIMAPI. Discovered by testing with httpx against the live game.

3. **RimWorld is fundamentally more complex than Factorio.** FLE (Factorio Learning Environment) agents optimize factories with deterministic mechanics. RLE agents must build AND manage a colony under stochastic conditions (raids, disease, mood, weather). Our action abstraction was too narrow.

## Decision Drivers

From user interview (2026-03-30):

- "The colonists just roam around and don't do anything" -- agents issue commands but lack the action vocabulary to set up basic infrastructure
- "The game is much more complex than Factorio" -- FLE agents optimize factories; RLE agents must build AND manage a colony
- "Let agents bootstrap" -- pre-built saves are for benchmarking reproducibility; the real test is whether AI can build from scratch
- "All of the above simultaneously" -- scenarios should test bootstrap, management, AND crisis response
- "We should never assume the bug lies with RIMAPI" -- it is normally but not always us because we are fresh in this build
- "Add all the APIs and let the agents decide which to use" -- stop cherry-picking; expose the full surface

## What Changes

### 1. Expose all 156+ RIMAPI endpoints via API catalog

Instead of wrapping individual endpoints with typed methods, generate a full catalog from the RIMAPI controller source and let agents reference any endpoint by key.

### 2. Replace ActionType enum with endpoint-based actions

Old:
```python
class ActionType(str, Enum):
    SET_WORK_PRIORITY = "set_work_priority"
    DRAFT_COLONIST = "draft_colonist"
    # ... 16 hardcoded types
```

New:
```python
class Action(BaseModel):
    endpoint: str          # Key from RIMAPI catalog
    parameters: dict       # Passed directly to RIMAPI
    target_colonist_id: str | None = None
    priority: int = 5
    reason: str = ""
```

### 3. Generic executor replaces handler spaghetti

Old: 13 individual `_do_*` handler methods, each with bespoke parameter mapping.

New: One generic dispatcher that looks up the endpoint in the catalog and forwards parameters.

### 4. Richer game state from new read endpoints

Pre-fetch zones, rooms, power grid, farm stats, and research tree into GameState so agents have full colony awareness.

### 5. Updated prompts for colony bootstrap

- Early game (day < 5): override "do no harm" with proactive infrastructure directives
- Inject full API catalog into agent prompts so they know what's available
- Allow 10+ actions per tick instead of 3-5

## Consequences

**Positive:**
- Agents can do anything RIMAPI supports without code changes
- New RIMAPI endpoints are automatically available to agents
- Eliminates the handler bug class entirely (no more wrong field names per handler)
- Agents see real colony data (zones, rooms, power) for informed decisions

**Negative:**
- Conflict resolver needs reworking (endpoint-based instead of enum-based)
- Larger prompts (~2K tokens for API catalog)
- Less type safety (string endpoint keys instead of enum values)
- Existing tests need rewriting

**Risks:**
- Agents may call endpoints incorrectly (wrong params) -- mitigated by catalog documenting required params
- Generic dispatcher may be harder to debug than typed handlers -- mitigated by logging every call with params
- Prompt size increase may degrade small model performance -- mitigated by domain-filtering (each agent only sees relevant endpoints)

## Related

- Issue #6: Agents must beat unmanaged baseline
- Issue #7: Create benchmark save files for all 6 scenarios
- Issue #8: RLE v1.0 multi-model colony management leaderboard (epic)
