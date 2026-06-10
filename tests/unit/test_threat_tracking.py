"""Tests for issue #25: threat filtering and draft-response tracking."""

from __future__ import annotations

import pytest

from rle.agents.actions import ActionPlan
from rle.orchestration.action_executor import ActionOutcome, ExecutionResult
from rle.orchestration.game_loop import RLEGameLoop, TickResult
from rle.rimapi.schemas import GameState, ThreatData
from rle.scoring.metrics import MetricContext, threat_response


def _loop_with_context() -> tuple[RLEGameLoop, MetricContext]:
    """A bare game loop carrying only the metric context (unit scope)."""
    loop = object.__new__(RLEGameLoop)
    ctx = MetricContext()
    loop._metric_context = ctx
    return loop, ctx


def _threat(tid: str, enemies: int = 3, level: float = 0.5) -> ThreatData:
    return ThreatData(
        threat_id=tid, threat_type="raid", faction="pirates",
        enemy_count=enemies, threat_level=level,
    )


def _tick_result(state: GameState) -> TickResult:
    return TickResult(
        tick=state.colony.tick, day=state.colony.day, macro_time=0.1,
        plan=ActionPlan(role="test", tick=1, actions=[]),
        execution=ExecutionResult(executed=0, failed=0, total=0),
        score=None,
    )


def _draft_outcome(success: bool = True, is_drafted: bool = True) -> ActionOutcome:
    return ActionOutcome(
        action_type="draft", endpoint="draft", target_colonist_id="181",
        success=success, parameters={"is_drafted": is_drafted},
    )


class TestThreatFiltering:
    def test_null_placeholder_not_counted(
        self, sample_game_state: GameState,
    ) -> None:
        loop, ctx = _loop_with_context()
        state = sample_game_state.model_copy(update={
            "threats": (_threat("phantom", enemies=0, level=0.0),),
        })
        loop._update_metric_context(_tick_result(state), state, tick_num=3)
        assert ctx.threats_seen == []
        assert threat_response(state, ctx) == 1.0

    def test_real_threat_recorded_with_seen_tick(
        self, sample_game_state: GameState,
    ) -> None:
        loop, ctx = _loop_with_context()
        state = sample_game_state.model_copy(update={"threats": (_threat("raid-1"),)})
        loop._update_metric_context(_tick_result(state), state, tick_num=4)
        assert [t.threat_id for t in ctx.threats_seen] == ["raid-1"]
        assert ctx.threat_seen_tick == {"raid-1": 4}

    def test_threat_while_already_drafted_is_instant_response(
        self, sample_game_state: GameState,
    ) -> None:
        loop, ctx = _loop_with_context()
        colonists = tuple(
            c.model_copy(update={"is_drafted": True})
            for c in sample_game_state.colonists
        )
        state = sample_game_state.model_copy(update={
            "threats": (_threat("raid-2"),), "colonists": colonists,
        })
        loop._update_metric_context(_tick_result(state), state, tick_num=5)
        assert ctx.first_draft_tick == {"raid-2": 0}
        assert threat_response(state, ctx) == 1.0


class TestDraftResponseRecording:
    def test_draft_records_delay_per_threat(self) -> None:
        loop, ctx = _loop_with_context()
        ctx.threats_seen.append(_threat("raid-1"))
        ctx.threat_seen_tick["raid-1"] = 4
        exec_result = ExecutionResult(
            executed=1, failed=0, total=1, outcomes=(_draft_outcome(),),
        )
        loop._record_draft_response(exec_result, tick_num=6)
        assert ctx.first_draft_tick == {"raid-1": 2}

    def test_undraft_does_not_count(self) -> None:
        loop, ctx = _loop_with_context()
        ctx.threats_seen.append(_threat("raid-1"))
        ctx.threat_seen_tick["raid-1"] = 4
        exec_result = ExecutionResult(
            executed=1, failed=0, total=1,
            outcomes=(_draft_outcome(is_drafted=False),),
        )
        loop._record_draft_response(exec_result, tick_num=6)
        assert ctx.first_draft_tick == {}

    def test_failed_draft_does_not_count(self) -> None:
        loop, ctx = _loop_with_context()
        ctx.threats_seen.append(_threat("raid-1"))
        ctx.threat_seen_tick["raid-1"] = 4
        exec_result = ExecutionResult(
            executed=0, failed=1, total=1,
            outcomes=(_draft_outcome(success=False),),
        )
        loop._record_draft_response(exec_result, tick_num=6)
        assert ctx.first_draft_tick == {}

    def test_first_response_is_not_overwritten(self) -> None:
        loop, ctx = _loop_with_context()
        ctx.threats_seen.append(_threat("raid-1"))
        ctx.threat_seen_tick["raid-1"] = 4
        ctx.first_draft_tick["raid-1"] = 1
        exec_result = ExecutionResult(
            executed=1, failed=0, total=1, outcomes=(_draft_outcome(),),
        )
        loop._record_draft_response(exec_result, tick_num=9)
        assert ctx.first_draft_tick == {"raid-1": 1}

    def test_metric_rewards_fast_response(
        self, sample_game_state: GameState,
    ) -> None:
        _, ctx = _loop_with_context()
        ctx.threats_seen.append(_threat("raid-1"))
        ctx.first_draft_tick["raid-1"] = 2
        # 2-tick response → 1 - 2/10 = 0.8
        assert threat_response(sample_game_state, ctx) == pytest.approx(0.8)
