"""Per-tick write ledger shared between the MCP tools and the harness.

Tool-using harnesses act *during* their turn (they need tool results to
decide the next call), so nothing is left for the loop to execute. The ledger
records every write attempted in the current tick and turns it into the
``StepResult`` the environment scores. No ``mcp`` import here — the harness
base and the scorer depend on this module even when the MCP extra is absent.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from rle.agents.actions import Action, ActionOutcome, ActionPlan, ExecutionResult
from rle.harness.protocol import StepResult


class NoActiveTickError(RuntimeError):
    """A write arrived while the environment was not inside a harness step."""


@dataclass
class TickLedger:
    harness_name: str = "mcp"
    active: bool = False
    tick: int = -1
    game_tick: int = 0
    actions: list[Action] = field(default_factory=list)
    outcomes: list[ActionOutcome] = field(default_factory=list)
    summary: str = ""
    extras: dict[str, Any] = field(default_factory=dict)
    turn_done: asyncio.Event = field(default_factory=asyncio.Event)

    def begin(self, tick: int, game_tick: int) -> None:
        self.active = True
        self.tick = tick
        self.game_tick = game_tick
        self.actions = []
        self.outcomes = []
        self.summary = ""
        self.extras = {}
        self.turn_done = asyncio.Event()

    def require_active(self) -> None:
        if not self.active:
            raise NoActiveTickError(
                "No tick is in progress — the environment is between turns. "
                "Wait for the next prompt before acting.",
            )

    def record(self, action: Action, outcome: ActionOutcome | None) -> None:
        self.require_active()
        self.actions.append(action)
        if outcome is not None:
            self.outcomes.append(outcome)

    def end_turn(self, summary: str = "") -> None:
        if summary:
            self.summary = summary
        self.turn_done.set()

    def finish(self) -> StepResult:
        """Close the tick and package what happened as a StepResult."""
        self.active = False
        executed = sum(1 for o in self.outcomes if o.success)
        failed = len(self.outcomes) - executed
        plan = ActionPlan(
            role=self.harness_name,
            tick=self.game_tick,
            actions=list(self.actions),
            summary=self.summary or f"{len(self.actions)} tool call(s)",
        )
        execution = ExecutionResult(
            executed=executed,
            failed=failed,
            total=len(self.outcomes),
            outcomes=tuple(self.outcomes),
        )
        return StepResult(
            plan=plan,
            execution=execution,
            proposals=(plan,),
            extras={"turn_ended": self.turn_done.is_set(), **self.extras},
        )
