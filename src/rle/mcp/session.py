"""Shared state between the environment and the MCP tool handlers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from rle.agents.actions import Action, ActionOutcome, ActionPlan, resolve_endpoint
from rle.harness.brief import ScenarioBrief, action_catalog
from rle.mcp.ledger import TickLedger
from rle.orchestration.action_executor import NEEDS_PAWN, ActionExecutor
from rle.rimapi.api_catalog import READ_CATALOG
from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import GameState
from rle.tracking.event_log import EventType

EmitFn = Callable[..., None]


def _noop_emit(*_args: Any, **_kwargs: Any) -> None:
    return None


@dataclass
class McpSession:
    """What the tools need: a RIMAPI client, an executor, the current tick's
    brief/state, and the ledger to record into."""

    client: RimAPIClient
    executor: ActionExecutor
    ledger: TickLedger
    brief: ScenarioBrief | None = None
    state: GameState | None = None
    emit: EmitFn = _noop_emit
    extras: dict[str, Any] = field(default_factory=dict)

    def begin_tick(
        self, tick: int, state: GameState, brief: ScenarioBrief | None,
    ) -> None:
        self.state = state
        self.brief = brief
        self.ledger.begin(tick, state.colony.tick)

    async def act(
        self,
        action_type: str,
        parameters: dict[str, Any] | None = None,
        target_colonist_id: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """Execute one write immediately, record it, and return the outcome."""
        self.ledger.require_active()
        action = Action(
            action_type=action_type,
            target_colonist_id=target_colonist_id,
            parameters=dict(parameters or {}),
            reason=reason,
        )
        endpoint = resolve_endpoint(action_type)
        if endpoint == "no_action":
            self.ledger.record(action, None)
            return {"ok": True, "action_type": action_type, "note": "no-op recorded"}
        outcome: ActionOutcome
        if endpoint in NEEDS_PAWN and not target_colonist_id:
            # The executor would silently skip this; tell the agent instead.
            outcome = ActionOutcome(
                action_type=action_type, endpoint=endpoint, target_colonist_id=None,
                success=False, error="target_colonist_id is required for this action",
                parameters=action.parameters,
            )
            self.ledger.record(action, outcome)
            return {"ok": False, "action_type": action_type, "endpoint": endpoint,
                    "error": outcome.error}
        result = await self.executor.execute(
            ActionPlan(role=self.ledger.harness_name, tick=self.ledger.game_tick, actions=[action]),
        )
        if result.outcomes:
            outcome = result.outcomes[0]
        else:
            # The executor skipped it (unknown endpoint).
            outcome = ActionOutcome(
                action_type=action_type, endpoint=endpoint,
                target_colonist_id=target_colonist_id, success=False,
                error="skipped by executor (unknown action)",
                parameters=action.parameters,
            )
        self.ledger.record(action, outcome)
        self.emit(
            EventType.ACTION_EXEC, self.ledger.tick,
            action_type=outcome.action_type, target=outcome.target_colonist_id,
            success=outcome.success, error=outcome.error, parameters=outcome.parameters,
            via="mcp",
        )
        return {
            "ok": outcome.success,
            "action_type": action_type,
            "endpoint": endpoint,
            "error": outcome.error,
        }

    async def read(self, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        """GET a READ_CATALOG endpoint by name."""
        raw = READ_CATALOG.get(endpoint)
        if raw is None:
            known = ", ".join(sorted(READ_CATALOG))
            raise KeyError(f"Unknown read endpoint {endpoint!r}. Known: {known}")
        entry = cast(dict[str, Any], raw)
        path = str(entry["path"])
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            path = f"{path}?{query}"
        return await self.client.call(str(entry.get("method", "GET")), path)

    def brief_text(self) -> str:
        if not self.ledger.active or self.brief is None:
            return (
                "No tick is in progress. The environment will prompt you when the "
                "next turn starts."
            )
        return self.brief.to_text()

    def state_json(self) -> dict[str, Any]:
        if self.brief is None:
            return {}
        return dict(self.brief.state)

    @staticmethod
    def actions() -> list[dict[str, Any]]:
        return action_catalog()
