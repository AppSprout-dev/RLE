# ADR-002: Map Analyst Agent + Spatial Awareness

**Date:** 2026-03-30
**Status:** Accepted
**Deciders:** @jkbennitt, @calebisgross

## Decision

Add a 7th agent (MapAnalyst) dedicated to spatial reasoning. It reads RIMAPI terrain/ore/plant endpoints, produces a compact map analysis with recommended build sites, farming areas, and resource locations. Other agents consume this analysis instead of blindly picking coordinates.

Also implement a full early-game bootstrap playbook and pre-processed map summaries for all agents.

## Context

After Phase A-E of the RIMAPI overhaul (ADR-001), agents can now execute all action types. But they place buildings in rivers, create zones on barren soil, and build arbitrary layouts. The delta is still negative (-0.015 to -0.024) across multiple models (Nemotron 30B, Grok 4.1 Fast).

**Root cause from user observation:** "The models don't understand how to play this game. Zones were arbitrary and unnecessarily mismatched. Blueprints were built in the middle of the river. A harder scenario is only going to expose these core flaws even more."

This is NOT a model quality problem (Grok 4.1 Fast made the same spatial errors as Nemotron 30B). It's a data problem — agents have no map awareness and no game strategy framework.

## Decision Drivers (user interview)

- "Both" — agents need map data AND game knowledge to make sensible decisions
- "Layered approach" — decision framework for basics + LLM creativity for optimization
- "RIMAPI map endpoints" — use /api/v1/map/terrain, ore, plants for pre-processed features
- "They're inseparable" — you can't place things well without strategy and can't strategize without placement
- "Full bootstrap plan + 7th map analysis agent" — deterministic early-game playbook + dedicated spatial reasoning agent
- "Both" (map pipeline) — shared compact summary for all agents + role-specific deep data

## What Changes

### 1. MapAnalyst Agent (7th agent)

A new agent that runs BEFORE the other 6 each tick. It:
- Reads `/api/v1/map/terrain` — soil fertility, water, rock, sand
- Reads `/api/v1/map/ore` — steel, components, gold deposits
- Reads `/api/v1/map/buildings` — existing structures and their positions
- Reads `/api/v1/map/zones` — existing zones
- Reads `/api/v1/map/rooms` — room layout and roles
- Identifies the colony center (average of colonist positions or drop pod location)
- Produces a structured `MapAnalysis` output:

```python
class MapAnalysis:
    colony_center: tuple[int, int]
    fertile_areas: list[dict]      # [{x1,z1,x2,z2,fertility,crop_rec}]
    build_sites: list[dict]        # [{x1,z1,x2,z2,terrain,reason}]
    ore_deposits: list[dict]       # [{x,z,type,amount}]
    water_features: list[dict]     # [{x1,z1,x2,z2,type}]
    natural_walls: list[dict]      # [{x1,z1,x2,z2,material}]
    existing_zones: list[dict]     # from /api/v1/map/zones
    existing_rooms: list[dict]     # from /api/v1/map/rooms
    recommended_stockpile: dict    # {x1,z1,x2,z2} near colony center
    recommended_growing: dict      # {x1,z1,x2,z2} on fertile soil
    recommended_shelter: dict      # {x1,z1,x2,z2} on solid ground
```

Other agents consume `MapAnalysis` in their filtered state. When ConstructionPlanner wants to place a wall, it uses `recommended_shelter` coordinates instead of random numbers. When ResourceManager creates a growing zone, it uses `recommended_growing` on fertile soil.

### 2. Full Early-Game Bootstrap Playbook

Deterministic plan for ticks 1-10 that agents follow:

```
Tick 1: MapAnalyst analyzes terrain. ResourceManager creates stockpile_zone
        at recommended_stockpile. Sets work priorities for all colonists.
Tick 2: ResourceManager creates growing_zone on recommended_growing (Plant_Rice
        for fast food). ResearchDirector sets research target.
Tick 3: ConstructionPlanner places shelter walls at recommended_shelter
        (5x5 room with door).
Tick 4: ConstructionPlanner places beds inside shelter.
Tick 5: ConstructionPlanner places campfire or stove for cooking.
Tick 6+: LLM takes over for adaptive strategy based on colony state.
```

This is injected into prompts as a "bootstrap phase" directive that overrides normal deliberation for the first few ticks.

### 3. Pre-processed Map Summary (shared + per-role)

**Shared summary** (all agents get this in system prompt):
```
Colony center: (128, 133). Fertile soil: (100-120, 80-95) avg 1.4 fertility.
River: N-S at x=130-135. Mountain: z>200. Steam geyser at (145, 90).
Existing zones: Growing zone 1 (25 cells), Stockpile 1 (16 cells).
Existing rooms: 1 bedroom (25 cells, 21C). No kitchen. No research room.
```

**Role-specific additions:**
- ConstructionPlanner: recommended_shelter coords, available materials, room needs
- ResourceManager: fertile areas with fertility scores, ore locations
- DefenseCommander: natural chokepoints, mountain walls, defensive positions

## Consequences

**Positive:**
- Agents stop building in rivers and farming on rock
- Spatial decisions are informed by actual terrain data
- Bootstrap playbook ensures productive early game
- MapAnalyst separates spatial reasoning from action planning
- Other agents can focus on their domain instead of guessing coordinates

**Negative:**
- 7th agent adds deliberation time (but can run first, then results cached)
- More RIMAPI reads per tick (terrain, ore, plants are large responses)
- Bootstrap playbook may be too rigid for non-Crashlanded scenarios
- Map summary adds ~500 tokens to every agent's context

**Risks:**
- Terrain endpoint may return too much data — need efficient summarization
- MapAnalyst's recommendations may become stale if colony expands
- Bootstrap playbook needs per-scenario variants

## Related

- ADR-001: Colony bootstrap strategy
- Issue #6: Agents must beat unmanaged baseline
- Issue #8: v1.0 multi-model leaderboard (epic)
- Issue #9: RIMAPI integration overhaul
