"""Scaffold for harnesses that drive an external coding agent over MCP.

Tool-agnostic by design: a concrete harness (in its own package) implements
how to start the agent, hand it a prompt, and stop it. This base owns
everything else — hosting the RLE MCP server in-process, the per-tick brief,
the turn protocol (prompt → agent acts through tools → ``end_turn`` or idle
→ ledger drained into ``StepResult``), timeouts, cost/latency accounting,
and the deliberation log — so every CLI harness is scored identically.

Requires the ``mcp`` extra.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from rle.config import RLEConfig
from rle.harness.brief import ScenarioBrief, build_brief
from rle.harness.protocol import BaseHarness, HarnessContext, HarnessStepError, StepResult
from rle.mcp.host import McpHost
from rle.mcp.ledger import TickLedger
from rle.mcp.listen import McpListenSettings, first_host, first_not_none, resolve_mcp_listen
from rle.mcp.server import build_server
from rle.mcp.session import McpSession
from rle.orchestration.action_executor import ActionExecutor
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent
from rle.tracking.event_log import EventType

logger = logging.getLogger(__name__)

_RAW_OUTPUT_CHARS = 16384

TURN_RULES = (
    "Rules for this turn:\n"
    "1. Call get_brief first. Use MAP_SUMMARY coordinates verbatim — never invent positions.\n"
    "2. Act only through the RLE tools (never shell into the game). Pawn ids are integers.\n"
    "3. Each tool call executes immediately and returns {ok, error}; do not repeat a failed call "
    "with the same arguments.\n"
    "4. When you have issued this tick's writes, call end_turn with a one-line summary. "
    "Doing nothing is allowed — still call end_turn.\n"
)


class HeadlessCliOptions(BaseModel):
    """Options common to every CLI-agent harness; subclasses extend."""

    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(
        default=None,
        description="Model identifier handed to the agent (defaults to RLEConfig.model).",
    )
    turn_timeout_s: float = Field(
        default=180.0,
        description="Hard cap on one turn. The agent is aborted and the tick scored as-is.",
    )
    idle_grace_s: float = Field(
        default=3.0,
        description=(
            "If the agent finishes responding without calling end_turn, wait this long "
            "for late tool calls before closing the tick."
        ),
    )
    extra_instructions: str = Field(
        default="",
        description="Appended to every turn prompt (harness-side prompt engineering).",
    )
    mcp_container_reachable: bool | None = Field(
        default=None,
        description=(
            "Bind MCP on 0.0.0.0 and advertise http://host.docker.internal:<port>/mcp "
            "so a Docker agent can reach host RimWorld/RLE. None inherits RLEConfig / "
            "MCP_CONTAINER_REACHABLE. Does not affect --docker (RIMAPI in a container)."
        ),
    )
    mcp_bind_host: str | None = Field(
        default=None,
        description="MCP listen address. None inherits RLEConfig / MCP_BIND_HOST.",
    )
    mcp_advertise_host: str | None = Field(
        default=None,
        description=(
            "Hostname in the MCP URL given to the agent. None inherits "
            "RLEConfig / MCP_ADVERTISE_HOST."
        ),
    )
    mcp_port: int | None = Field(
        default=None,
        description=(
            "MCP listen port (8766 in container-reachable mode; 0 = ephemeral). "
            "None inherits RLEConfig / MCP_PORT."
        ),
    )

    def mcp_listen(self, config: RLEConfig) -> McpListenSettings:
        """Merge harness-opt overrides onto RLEConfig, then apply mode defaults."""
        container = first_not_none(self.mcp_container_reachable, config.mcp_container_reachable)
        return resolve_mcp_listen(
            container_reachable=bool(container),
            bind_host=first_host(self.mcp_bind_host, config.mcp_bind_host),
            advertise_host=first_host(self.mcp_advertise_host, config.mcp_advertise_host),
            port=first_not_none(self.mcp_port, config.mcp_port),
        )


@dataclass
class TurnResult:
    """What the agent produced for one prompt."""

    text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


class HeadlessCliHarness(BaseHarness, ABC):
    name: ClassVar[str] = "headless-cli"

    def __init__(self, options: HeadlessCliOptions) -> None:
        super().__init__()
        self.options = options
        self._session: McpSession | None = None
        self._host: McpHost | None = None
        self._agent_started = False

    # ------------------------------------------------------------------
    # Tool-specific hooks
    # ------------------------------------------------------------------

    @abstractmethod
    async def start_agent(self, mcp_url: str) -> None:
        """Launch or attach to the agent and register the RLE MCP server."""

    @abstractmethod
    async def send_turn(self, prompt: str) -> TurnResult:
        """Deliver one turn prompt and return when the agent has finished responding."""

    @abstractmethod
    async def stop_agent(self) -> None:
        """Abort any in-flight turn and shut the agent down."""

    async def abort_turn(self) -> None:
        """Called on timeout; default just stops and restarts nothing."""
        return None

    def agent_versions(self) -> dict[str, str]:
        """Version info for run metadata (binary --version etc.)."""
        return {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def session(self) -> McpSession:
        if self._session is None:
            raise RuntimeError("setup() has not been called")
        return self._session

    @property
    def mcp_url(self) -> str:
        if self._host is None:
            raise RuntimeError("setup() has not been called")
        return self._host.url

    async def setup(self, ctx: HarnessContext) -> None:
        await super().setup(ctx)
        ledger = TickLedger(harness_name=self.name)
        self._session = McpSession(
            client=ctx.client, executor=ActionExecutor(ctx.client), ledger=ledger, emit=ctx.emit,
        )
        listen = self.options.mcp_listen(ctx.config)
        self._host = McpHost(build_server(self._session), listen)
        url = await self._host.start()
        logger.info(
            "MCP host listening on %s:%s, advertising %s",
            self._host.bind_host, self._host.port, url,
        )
        await self.start_agent(url)
        self._agent_started = True

    async def teardown(self) -> None:
        if self._agent_started:
            try:
                await self.stop_agent()
            except Exception:
                logger.debug("stop_agent failed", exc_info=True)
            self._agent_started = False
        if self._host is not None:
            await self._host.stop()

    def describe(self) -> dict[str, str]:
        info = {"harness": self.name, "model": self.options.model or self.ctx.config.model}
        info.update(self.agent_versions())
        return info

    # ------------------------------------------------------------------
    # Turn protocol
    # ------------------------------------------------------------------

    def render_prompt(self, brief: ScenarioBrief) -> str:
        parts = [
            f"RLE turn — tick {brief.tick}, day {brief.day}. "
            "You manage this RimWorld colony through the `rle` MCP tools.",
            TURN_RULES,
        ]
        if self.options.extra_instructions:
            parts.append(self.options.extra_instructions)
        parts.append(
            "Brief preview (call get_brief for the full version):\n"
            + brief.to_text()[:4000],
        )
        return "\n\n".join(parts)

    async def step(
        self, state: GameState, tick: int, macro_time: float, events: list[RimAPIEvent],
    ) -> StepResult:
        session = self.session
        brief = build_brief(
            state, tick=tick, macro_time=macro_time, scenario=self.ctx.scenario, events=events,
        )
        session.begin_tick(tick, state, brief)
        prompt = self.render_prompt(brief)

        t0 = _time.monotonic()
        status = "success"
        turn = TurnResult()
        try:
            turn = await asyncio.wait_for(
                self._run_turn(prompt, session.ledger), timeout=self.options.turn_timeout_s,
            )
        except asyncio.TimeoutError:
            status = "turn_timeout"
            logger.warning("%s turn timed out after %.0fs (tick %d)",
                           self.name, self.options.turn_timeout_s, tick)
            await self.abort_turn()
        except HarnessStepError as exc:
            status = "agent_error"
            logger.warning("%s agent error (tick %d): %s", self.name, tick, exc)
            turn = TurnResult(text=str(exc))
        latency_ms = round((_time.monotonic() - t0) * 1000, 1)

        step = session.ledger.finish()
        if status == "success":
            self.parse_successes += 1
        else:
            self.parse_failures += 1

        n_actions = len(step.plan.actions)
        self.deliberation_log.append({
            "tick": tick, "agent": self.name, "status": status,
            "num_actions": n_actions, "summary": step.plan.summary,
            "latency_ms": latency_ms,
        })
        self.ctx.emit(
            EventType.DELIBERATION if status == "success" else EventType.ERROR, tick,
            agent=self.name, latency_ms=latency_ms, num_actions=n_actions,
            summary=step.plan.summary, error_type=None if status == "success" else status,
        )
        if turn.prompt_tokens or turn.completion_tokens:
            if self.ctx.cost_tracker:
                self.ctx.cost_tracker.record_raw(
                    turn.prompt_tokens, turn.completion_tokens, turn.reasoning_tokens,
                )
            self.ctx.emit(
                EventType.PROVIDER_CALL, tick, agent=self.name,
                prompt_tokens=turn.prompt_tokens, completion_tokens=turn.completion_tokens,
                reasoning_tokens=turn.reasoning_tokens,
                raw_output=turn.text[:_RAW_OUTPUT_CHARS],
                raw_output_truncated=len(turn.text) > _RAW_OUTPUT_CHARS,
            )

        extras = {**step.extras, "status": status, "latency_ms": latency_ms, **turn.extras}
        return StepResult(
            plan=step.plan, execution=step.execution, proposals=step.proposals, extras=extras,
        )

    async def _run_turn(self, prompt: str, ledger: TickLedger) -> TurnResult:
        """Prompt the agent, then wait for end_turn (or a short idle grace)."""
        send = asyncio.create_task(self.send_turn(prompt))
        done_wait = asyncio.create_task(ledger.turn_done.wait())
        try:
            await asyncio.wait({send, done_wait}, return_when=asyncio.FIRST_COMPLETED)
            if send.done():
                result = send.result()
                if not ledger.turn_done.is_set():
                    # Agent replied without end_turn: allow trailing tool calls.
                    try:
                        await asyncio.wait_for(
                            ledger.turn_done.wait(), timeout=self.options.idle_grace_s,
                        )
                    except asyncio.TimeoutError:
                        pass
                return result
            # end_turn arrived first; let the agent finish its reply briefly.
            try:
                return await asyncio.wait_for(send, timeout=self.options.idle_grace_s)
            except asyncio.TimeoutError:
                send.cancel()
                return TurnResult(text="(agent still responding after end_turn)")
        finally:
            for task in (send, done_wait):
                if not task.done():
                    task.cancel()
