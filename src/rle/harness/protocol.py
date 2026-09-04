"""Harness protocol — the seam between the RLE environment and whatever
decides what the colony does each tick.

The environment (``RLEGameLoop``) owns the game: pause/unpause, state
refresh, action execution, scoring, evaluation, export. A *harness* owns the
decision-making: one or many LLM agents, a coding agent attached over MCP, a
scripted policy, or nothing at all (the unmanaged baseline). Harnesses are
benchmarked side by side with models, so nothing in this module may depend on
any particular agent framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from rle.agents.actions import ActionPlan
from rle.orchestration.action_executor import ExecutionResult
from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent
from rle.scoring.composite import ScoreSnapshot
from rle.tracking.cost_tracker import CostTracker
from rle.tracking.event_log import EventLog, EventType

if TYPE_CHECKING:
    from rle.config import RLEConfig
    from rle.scenarios.schema import ScenarioConfig


class HarnessStepError(Exception):
    """A harness failed to produce a step. The loop records an ERROR event and
    treats the tick as having no actions; the run continues."""


class StepResult(BaseModel):
    """What a harness hands back for one tick.

    ``plan`` is the merged set of actions to apply. ``execution`` is set when
    the harness has *already* applied its writes (coding agents acting through
    the RLE MCP server see tool results inside their turn, so nothing is left
    for the loop to execute); when it is ``None`` the loop runs
    ``ActionExecutor`` itself. ``proposals`` are optional per-sub-agent plans
    kept for dashboards and post-hoc analysis; ``extras`` is a free-form bag
    for harness-specific telemetry (helix phase, session ids, ...).
    """

    model_config = ConfigDict(frozen=True)

    plan: ActionPlan
    execution: ExecutionResult | None = None
    proposals: tuple[ActionPlan, ...] = ()
    extras: dict[str, Any] = {}


@dataclass
class HarnessContext:
    """Everything the environment lends a harness for the duration of a run."""

    config: RLEConfig
    client: RimAPIClient
    expected_duration_days: int = 60
    initial_population: int = 3
    scenario: ScenarioConfig | None = None
    event_log: EventLog | None = None
    cost_tracker: CostTracker | None = None
    tick_timeout_s: float | None = None
    smoke: bool = False
    extras: dict[str, Any] = field(default_factory=dict)

    def emit(
        self, event_type: EventType, tick: int,
        agent: str | None = None, **data: object,
    ) -> None:
        """Emit to the run's event log if one is configured."""
        if self.event_log is not None:
            self.event_log.emit(event_type, tick, agent=agent, **data)


@runtime_checkable
class TickObserver(Protocol):
    """Receives the end-of-tick summary (visualisers, recorders, cameras)."""

    def on_tick_end(
        self, tick: int, day: int, step: StepResult,
        execution: ExecutionResult, score: ScoreSnapshot | None,
    ) -> None: ...


class BaseHarness(ABC):
    """Base class every harness derives from.

    Lifecycle per run: ``setup`` once, then per tick ``step`` followed by
    ``on_tick_end`` (after execution + scoring), then ``teardown``. Subclasses
    should keep ``deliberation_log`` / ``parse_successes`` / ``parse_failures``
    updated so run reports stay uniform across harnesses.
    """

    name: ClassVar[str] = "base"

    def __init__(self) -> None:
        self.deliberation_log: list[dict[str, object]] = []
        self.parse_successes = 0
        self.parse_failures = 0
        self.observers: list[TickObserver] = []
        self._ctx: HarnessContext | None = None

    @property
    def ctx(self) -> HarnessContext:
        if self._ctx is None:
            raise RuntimeError(f"{type(self).__name__}.setup() has not been called")
        return self._ctx

    async def setup(self, ctx: HarnessContext) -> None:
        self._ctx = ctx

    @abstractmethod
    async def step(
        self, state: GameState, tick: int, macro_time: float,
        events: list[RimAPIEvent],
    ) -> StepResult:
        """Decide (and optionally apply) this tick's actions."""

    async def on_tick_end(
        self, tick: int, state: GameState, step: StepResult,
        execution: ExecutionResult, score: ScoreSnapshot | None,
    ) -> None:
        """Feedback hook after execution and scoring. Default: notify observers."""
        for observer in self.observers:
            observer.on_tick_end(state.colony.tick, state.colony.day, step, execution, score)

    async def teardown(self) -> None:
        return None

    def run_context(self) -> AbstractContextManager[Any]:
        """Context the loop enters around ``run()`` (e.g. a live terminal UI)."""
        return nullcontext()

    def describe(self) -> dict[str, str]:
        """Version / identity info recorded in run metadata."""
        return {"harness": self.name}


class Availability(BaseModel):
    """Whether a plugin can run here, and if not, why."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    reason: str = ""

    @classmethod
    def available(cls) -> Availability:
        return cls(ok=True)

    @classmethod
    def missing(cls, reason: str) -> Availability:
        return cls(ok=False, reason=reason)


class HarnessPlugin(Protocol):
    """Entry-point contract under the ``rle.harnesses`` group.

    A plugin is a module-level object (conventionally ``PLUGIN``) whose
    ``create`` builds a harness from validated options. ``available`` must be
    cheap and must not import optional dependencies at module load — probe
    for them inside the method.
    """

    name: str
    description: str

    def available(self) -> Availability: ...

    def option_schema(self) -> type[BaseModel]: ...

    def create(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness: ...

    def smoke(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness: ...

    def describe(self) -> dict[str, str]: ...


class EmptyOptions(BaseModel):
    """Option schema for harnesses that take no options."""

    model_config = ConfigDict(extra="forbid")


OptionsFactory = Callable[[], type[BaseModel]]
