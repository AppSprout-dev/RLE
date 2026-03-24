---
paths:
  - "src/rle/orchestration/**"
  - "src/rle/agents/**"
---

# Architecture Rules

- Use CentralPost hub-spoke for ALL inter-agent communication. Never pass context lists through the orchestrator.
- Agents read spoke messages via `_get_spoke_context()` before each deliberation. Never bypass this.
- SSE events flow: sse_client → state_manager.pending_events → game_loop injects → agent._pending_events → filter_game_state(). Every agent must include `"recent_events": self._format_events(...)` in its filtered state.
- Parallel deliberation is the default. Sequential is only for debugging.
