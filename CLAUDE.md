# RLE — RimWorld Learning Environment

Multi-agent benchmark where Felix Agent SDK agents play RimWorld. 6 role-specialized LLM agents manage a colony via the RIMAPI REST API.

## Commands
- Install: `pip install -e ".[dev]"`
- Test: `pytest`
- Lint: `ruff check src/ tests/`
- Type check: `mypy src/`

## Architecture
- **Agents map to roles, not colonists**: ResourceManager, DefenseCommander, ResearchDirector, SocialOverseer, ConstructionPlanner, MedicalOfficer
- **Hub-spoke communication** via Felix's CentralPost — agents send messages through Spoke connections
- **Helix geometry** drives colony phase adaptation: early=exploration (high temp), mid=analysis, late=synthesis (low temp)
- **Turn-based loop**: pause → read state via RIMAPI → agents deliberate → resolve conflicts → execute → unpause → advance
- **RIMAPI**: C# RimWorld mod exposing REST API on localhost:8765

## Conventions
- Async-first (httpx AsyncClient, async game loop)
- Pydantic v2 models with frozen=True for game state
- Felix Agent SDK for providers, agents, helix, communication
- Tests use pytest-asyncio with auto mode
