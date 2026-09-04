"""FelixHarness — the original RLE harness: MapAnalyst-first, six role agents
deliberating in parallel over Felix SDK's CentralPost hub-spoke bus, merged by
``ActionResolver``.

Everything Felix-specific that used to live in ``RLEGameLoop`` lives here:
hub/spoke wiring, per-agent timeouts, phase broadcasts, action-error and score
feedback, helix visualisation, generation-id / token accounting.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from contextlib import AbstractContextManager, nullcontext
from importlib.metadata import PackageNotFoundError, version
from typing import Any, ClassVar

from felix_agent_sdk.communication import CentralPost, MessageType, SpokeManager
from felix_agent_sdk.providers import ProviderError

from rle.agents.actions import ActionPlan, ActionPlanParseError, ExecutionResult
from rle.harness.felix.agents.base_role import RimWorldRoleAgent
from rle.harness.protocol import BaseHarness, HarnessContext, StepResult
from rle.orchestration.action_resolver import ActionResolver
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent
from rle.scoring.composite import ScoreSnapshot
from rle.tracking.event_log import EventType

logger = logging.getLogger(__name__)

# Truncation limits for human-readable text persisted to the event log /
# deliberation log. Keep these tight so the JSONL stays grep-able and small;
# the per-scenario *_deliberations.jsonl carries the full raw reasoning.
_ACTION_REASON_CHARS = 200
_PLAN_SUMMARY_CHARS = 300
_PARSE_FAILURE_RAW_CHARS = 500
# Full LLM completion text on successful deliberation (PROVIDER_CALL events).
# 16 KB headroom: frontier models emit multi-KB structured plans and the
# verbatim transcripts are first-class analysis artifacts; longer completions
# are tail-truncated so the parsed action JSON remains visible.
_RAW_OUTPUT_CHARS = 16384


def felix_sdk_version() -> str:
    try:
        return version("felix-agent-sdk")
    except PackageNotFoundError:
        return "unknown"


def phase_for(macro_time: float) -> str:
    """Helix macro phase for a normalised run position (0..1)."""
    if macro_time < 0.4:
        return "exploration"
    if macro_time < 0.7:
        return "analysis"
    return "synthesis"


class FelixHarness(BaseHarness):
    name: ClassVar[str] = "felix"

    def __init__(
        self,
        agents: list[RimWorldRoleAgent],
        *,
        parallel: bool = True,
        role_timeout_s: float = 60.0,
        visualizer: Any | None = None,
    ) -> None:
        super().__init__()
        self._agents = agents
        self._map_analyst: RimWorldRoleAgent | None = None
        self._role_agents: list[RimWorldRoleAgent] = []
        for agent in agents:
            if agent.ROLE_NAME == "map_analyst":
                self._map_analyst = agent
            else:
                self._role_agents.append(agent)
        self._parallel = parallel
        self._role_timeout_s = role_timeout_s
        self._visualizer = visualizer
        self._resolver = ActionResolver()
        self.last_phase: str = ""

        # Hub-spoke communication — agents read messages from their spokes.
        # Wired at construction so callers can inspect spokes before setup().
        self.hub = CentralPost(max_agents=max(1, len(agents)))
        self.spoke_manager = SpokeManager(self.hub)
        for agent in agents:
            spoke = self.spoke_manager.create_spoke(agent.agent_id, agent=agent)
            agent.attach_spoke(spoke)

    @property
    def agents(self) -> list[RimWorldRoleAgent]:
        return list(self._agents)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self, ctx: HarnessContext) -> None:
        await super().setup(ctx)
        if self._visualizer is not None:
            self.observers.append(_HelixRenderObserver(self._visualizer))

    async def teardown(self) -> None:
        # Final drain: a deliberation that timed out on the last tick may have
        # completed after the per-tick drain.
        self._drain_generation_ids()

    def run_context(self) -> AbstractContextManager[Any]:
        if self._visualizer is not None:
            return self._visualizer.live()  # type: ignore[no-any-return]
        return nullcontext()

    @property
    def visualizer(self) -> Any | None:
        return self._visualizer

    def describe(self) -> dict[str, str]:
        return {
            "harness": self.name,
            "agents": ",".join(a.ROLE_NAME for a in self._agents),
            "felix_agent_sdk": felix_sdk_version(),
        }

    # ------------------------------------------------------------------
    # Per-tick step
    # ------------------------------------------------------------------

    async def step(
        self, state: GameState, tick: int, macro_time: float,
        events: list[RimAPIEvent],
    ) -> StepResult:
        # Route previous tick's messages to agent spokes + broadcast phase changes
        messages_before = self.hub.total_messages_processed
        self.spoke_manager.process_all_messages()
        self._broadcast_phase_if_changed(macro_time)

        for agent in self._agents:
            agent.set_pending_events(events)
        for evt in events:
            self.ctx.emit(
                EventType.SSE_EVENT, tick,
                sse_type=evt.event_type, sse_data=str(evt.data)[:200],
            )

        plans: list[ActionPlan] = []

        # MapAnalyst deliberates FIRST (sequential, timeout-wrapped)
        if self._map_analyst:
            ma_agent, ma_plan = await self._deliberate_agent_with_timeout(
                self._map_analyst, state, macro_time, tick,
            )
            if ma_plan is not None:
                plans.append(ma_plan)
                self._update_visualizer_agent(ma_agent, ma_plan, macro_time)
                self._send_task_complete(ma_agent, ma_plan)
                # Route MapAnalyst output to role agent spokes immediately
                self.spoke_manager.process_all_messages()

        # Snapshot which agents have pending spoke messages (diagnostics)
        agents_with_messages: set[str] = set()
        for ra in self._role_agents:
            spoke = self.spoke_manager.get_spoke(ra.agent_id)
            if spoke and spoke.has_pending_messages():
                agents_with_messages.add(ra.agent_id)

        if self._parallel:
            results = await self._deliberate_parallel(state, macro_time, tick)
        else:
            results = await self._deliberate_sequential(state, macro_time, tick)

        agents_acted_with_messages = 0
        for agent, plan in results:
            if plan is None:
                continue
            plans.append(plan)
            if agent.agent_id in agents_with_messages:
                agents_acted_with_messages += 1
            self._update_visualizer_agent(agent, plan, macro_time)
            self._send_task_complete(agent, plan)

        # Capture generation IDs from every provider call this tick — parse
        # retries and failed deliberations bill tokens too.
        self._drain_generation_ids()

        # Resolve conflicts. Resolver + CentralPost counts are diagnostics in
        # the event log only — they no longer feed the composite (#51).
        resolved, resolver_stats = self._resolver.resolve(plans, state)
        self.ctx.emit(
            EventType.CONFLICT, tick,
            input_plans=len(plans),
            output_actions=len(resolved.actions),
            conflicts_detected=resolver_stats.conflicts_total,
            conflicts_resolved=resolver_stats.conflicts_resolved,
            messages_routed=self.hub.total_messages_processed - messages_before,
            agents_with_messages=len(agents_with_messages),
            agents_acted_with_messages=agents_acted_with_messages,
        )

        return StepResult(
            plan=resolved,
            proposals=tuple(plans),
            extras={
                "phase": self.last_phase,
                "conflicts_detected": resolver_stats.conflicts_total,
                "conflicts_resolved": resolver_stats.conflicts_resolved,
            },
        )

    async def on_tick_end(
        self, tick: int, state: GameState, step: StepResult,
        execution: ExecutionResult, score: ScoreSnapshot | None,
    ) -> None:
        # Surface per-action errors back to agents so they can avoid
        # re-proposing the same invalid action next tick.
        failed_outcomes = [o for o in execution.outcomes if not o.success and o.error]
        if failed_outcomes:
            error_summary = "; ".join(
                f"{o.action_type}({o.target_colonist_id or '-'}): {o.error}"
                for o in failed_outcomes[:10]
            )
            self.spoke_manager.broadcast_message(
                MessageType.STATUS_UPDATE,
                {
                    "tick": state.colony.tick,
                    "summary": f"Last tick action errors — DO NOT REPEAT: {error_summary}",
                    "action_errors": [
                        {
                            "action_type": o.action_type,
                            "target_colonist_id": o.target_colonist_id,
                            "error": o.error,
                        }
                        for o in failed_outcomes
                    ],
                },
                sender_id="hub",
            )

        if score:
            self.spoke_manager.broadcast_message(
                MessageType.STATUS_UPDATE,
                {
                    "tick": state.colony.tick,
                    "day": state.colony.day,
                    "composite_score": score.composite,
                    "metrics": score.metrics,
                },
                sender_id="hub",
            )

        await super().on_tick_end(tick, state, step, execution, score)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _send_task_complete(self, agent: RimWorldRoleAgent, plan: ActionPlan) -> None:
        spoke = self.spoke_manager.get_spoke(agent.agent_id)
        if spoke and spoke.is_connected:
            spoke.send_message(
                MessageType.TASK_COMPLETE,
                {
                    "role": plan.role,
                    "summary": plan.summary,
                    "confidence": plan.confidence,
                    "num_actions": len(plan.actions),
                    "action_types": [a.action_type for a in plan.actions],
                },
            )

    def _drain_generation_ids(self) -> None:
        tracker = self._ctx.cost_tracker if self._ctx else None
        if tracker is None:
            return
        for agent in self._agents:
            for gen_id in agent.drain_generation_ids():
                tracker.record_generation_id(gen_id)

    def _broadcast_phase_if_changed(self, macro_time: float) -> None:
        phase = phase_for(macro_time)
        if phase != self.last_phase:
            self.spoke_manager.broadcast_message(
                MessageType.PHASE_ANNOUNCE,
                {"phase": phase, "depth_ratio": macro_time},
                sender_id="hub",
            )
            self.last_phase = phase

    def _update_visualizer_agent(
        self, agent: RimWorldRoleAgent, plan: ActionPlan, macro_time: float,
    ) -> None:
        if self._visualizer is None:
            return
        self._visualizer.update(
            agent.agent_id,
            progress=macro_time,
            confidence=plan.confidence,
            phase=agent.position.phase,
            status=f"{len(plan.actions)} actions",
        )

    async def _deliberate_parallel(
        self, state: GameState, macro_time: float, tick: int,
    ) -> list[tuple[RimWorldRoleAgent, ActionPlan | None]]:
        return list(await asyncio.gather(*[
            self._deliberate_agent_with_timeout(a, state, macro_time, tick)
            for a in self._role_agents
        ]))

    async def _deliberate_sequential(
        self, state: GameState, macro_time: float, tick: int,
    ) -> list[tuple[RimWorldRoleAgent, ActionPlan | None]]:
        results: list[tuple[RimWorldRoleAgent, ActionPlan | None]] = []
        for agent in self._role_agents:
            results.append(
                await self._deliberate_agent_with_timeout(agent, state, macro_time, tick),
            )
        return results

    async def _deliberate_agent_with_timeout(
        self, agent: RimWorldRoleAgent, state: GameState, macro_time: float, tick: int,
    ) -> tuple[RimWorldRoleAgent, ActionPlan | None]:
        """Run one agent's deliberation with a hard timeout.

        On timeout: emits a deliberation_timeout ERROR event, records it in the
        deliberation log, and returns ``(agent, None)`` so the tick continues.
        """
        try:
            return await asyncio.wait_for(
                self._deliberate_agent(agent, state, macro_time, tick),
                timeout=self._role_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Agent %s deliberation timed out after %.1fs (tick %d)",
                agent.ROLE_NAME, self._role_timeout_s, tick,
            )
            self.parse_failures += 1
            self.deliberation_log.append({
                "tick": tick, "agent": agent.ROLE_NAME,
                "status": "deliberation_timeout",
                "reason": f"timed out after {self._role_timeout_s}s",
            })
            self.ctx.emit(
                EventType.ERROR, tick, agent=agent.ROLE_NAME,
                error_type="deliberation_timeout",
                reason=f"timed out after {self._role_timeout_s}s",
                timeout_s=self._role_timeout_s,
            )
            return agent, None

    async def _deliberate_agent(
        self, agent: RimWorldRoleAgent, state: GameState, macro_time: float, tick: int,
    ) -> tuple[RimWorldRoleAgent, ActionPlan | None]:
        t0 = _time.monotonic()
        try:
            plan = await agent.adeliberate(state, macro_time)
        except ActionPlanParseError as e:
            latency_ms = round((_time.monotonic() - t0) * 1000, 1)
            logger.warning(
                "Agent %s parse failure (tick %d): %s", agent.ROLE_NAME, tick, e.reason,
            )
            self.parse_failures += 1
            raw_truncated = (
                e.raw_content[:_PARSE_FAILURE_RAW_CHARS] if e.raw_content else None
            )
            self.deliberation_log.append({
                "tick": tick, "agent": agent.ROLE_NAME,
                "status": "parse_failure", "reason": e.reason,
                "raw": raw_truncated,
            })
            self.ctx.emit(
                EventType.ERROR, tick, agent=agent.ROLE_NAME,
                error_type="parse_failure", reason=e.reason, latency_ms=latency_ms,
                raw=raw_truncated,
            )
            return agent, None
        except ProviderError as e:
            latency_ms = round((_time.monotonic() - t0) * 1000, 1)
            logger.warning(
                "Agent %s provider error (tick %d): %s", agent.ROLE_NAME, tick, e,
            )
            self.parse_failures += 1
            self.deliberation_log.append({
                "tick": tick, "agent": agent.ROLE_NAME,
                "status": "provider_error", "reason": str(e),
            })
            self.ctx.emit(
                EventType.ERROR, tick, agent=agent.ROLE_NAME,
                error_type="provider_error", reason=str(e), latency_ms=latency_ms,
            )
            return agent, None

        latency_ms = round((_time.monotonic() - t0) * 1000, 1)
        self.parse_successes += 1
        actions_payload = [
            {"type": a.action_type, "target": a.target_colonist_id,
             "priority": a.priority, "reason": a.reason[:_ACTION_REASON_CHARS]}
            for a in plan.actions
        ]
        summary_truncated = plan.summary[:_PLAN_SUMMARY_CHARS]
        self.deliberation_log.append({
            "tick": tick, "agent": plan.role,
            "status": "success", "confidence": plan.confidence,
            "num_actions": len(plan.actions),
            "actions": actions_payload,
            "summary": summary_truncated,
        })
        self.ctx.emit(
            EventType.DELIBERATION, tick, agent=plan.role,
            latency_ms=latency_ms, confidence=plan.confidence,
            num_actions=len(plan.actions),
            actions=actions_payload,
            summary=summary_truncated,
        )

        usage = agent._last_usage
        if usage and isinstance(usage, dict):
            pt = usage.get("prompt_tokens", 0)
            ct = usage.get("completion_tokens", 0)
            rt = usage.get("reasoning_tokens", 0)
            if not isinstance(rt, int):
                rt = 0
            if isinstance(pt, int) and isinstance(ct, int):
                if self.ctx.cost_tracker:
                    self.ctx.cost_tracker.record_raw(pt, ct, rt)
                raw_output = agent._last_raw_output
                raw_output_truncated = (
                    raw_output[:_RAW_OUTPUT_CHARS] if raw_output else None
                )
                was_truncated = (
                    raw_output is not None and len(raw_output) > _RAW_OUTPUT_CHARS
                )
                self.ctx.emit(
                    EventType.PROVIDER_CALL, tick, agent=plan.role,
                    prompt_tokens=pt, completion_tokens=ct,
                    reasoning_tokens=rt,
                    raw_output=raw_output_truncated,
                    raw_output_truncated=was_truncated,
                )

        return agent, plan


class _HelixRenderObserver:
    """Renders the terminal helix at the end of each tick."""

    def __init__(self, visualizer: Any) -> None:
        self._visualizer = visualizer

    def on_tick_end(
        self, tick: int, day: int, step: StepResult,
        execution: ExecutionResult, score: ScoreSnapshot | None,
    ) -> None:
        extra: dict[str, str] = {
            "actions": f"{execution.executed}/{execution.total}",
        }
        if score:
            extra["score"] = f"{score.composite:.3f}"
        self._visualizer.render(tick=tick, day=day, extra_info=extra)
