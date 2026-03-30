"""Tests for the RimWorldRoleAgent base class."""

from __future__ import annotations

import json
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from felix_agent_sdk import LLMResult
from felix_agent_sdk.core import HelixGeometry
from felix_agent_sdk.providers.types import CompletionResult
from rle.agents.actions import ActionPlan, ActionPlanParseError
from rle.agents.base_role import RimWorldRoleAgent
from rle.rimapi.schemas import GameState

# ------------------------------------------------------------------
# Minimal concrete subclass for testing the abstract base
# ------------------------------------------------------------------


class _DummyRoleAgent(RimWorldRoleAgent):
    ROLE_NAME: ClassVar[str] = "dummy"
    ALLOWED_ACTIONS: ClassVar[set[str]] = {
        "set_work_priority",
        "no_action",
    }
    TEMPERATURE_RANGE: ClassVar[tuple[float, float]] = (0.3, 0.8)

    def filter_game_state(self, state: GameState) -> dict[str, Any]:
        return {
            "colony": {"day": state.colony.day, "population": state.colony.population},
            "food": state.resources.food,
        }

    def _get_task_description(self) -> str:
        return "Dummy task for testing."

    def _get_role_description(self) -> str:
        return "A dummy role agent used in unit tests."


# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


class TestConstruction:
    def test_agent_type_from_role_name(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        assert agent.agent_type == "dummy"

    def test_temperature_range_from_classvar(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        assert agent.temperature_range == (0.3, 0.8)

    def test_last_action_plan_initially_none(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        assert agent._last_action_plan is None


# ------------------------------------------------------------------
# build_task
# ------------------------------------------------------------------


class TestBuildTask:
    def test_returns_llm_task(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        task = agent.build_task(sample_game_state)
        assert task.task_id == "dummy-tick-720000"
        assert task.description == "Dummy task for testing."

    def test_context_is_filtered_json(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        task = agent.build_task(sample_game_state)
        ctx = json.loads(task.context)
        assert ctx["colony"]["day"] == 12
        assert ctx["food"] == 120.5
        # Should NOT contain full game state keys
        assert "research" not in ctx
        assert "threats" not in ctx

    def test_metadata_contains_allowed_actions(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        task = agent.build_task(sample_game_state)
        assert "set_work_priority" in task.metadata["allowed_actions"]
        assert "no_action" in task.metadata["allowed_actions"]
        assert task.metadata["role"] == "dummy"
        assert task.metadata["tick"] == 720000


# ------------------------------------------------------------------
# create_position_aware_prompt
# ------------------------------------------------------------------


class TestCreatePositionAwarePrompt:
    def _make_agent_at_progress(
        self, provider: MagicMock, helix: HelixGeometry, progress: float,
    ) -> _DummyRoleAgent:
        agent = _DummyRoleAgent(
            "d-01", provider, helix, spawn_time=0.0, velocity=1.0,
        )
        agent.spawn(0.0)
        agent.update_position(progress)
        return agent

    def test_exploration_phase(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = self._make_agent_at_progress(mock_provider, helix, 0.1)
        task = agent.build_task(sample_game_state)
        system, user = agent.create_position_aware_prompt(task)
        assert "EXPLORATION" in system
        assert "diverse" in system.lower() or "broadly" in system.lower()

    def test_analysis_phase(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = self._make_agent_at_progress(mock_provider, helix, 0.5)
        task = agent.build_task(sample_game_state)
        system, user = agent.create_position_aware_prompt(task)
        assert "ANALYSIS" in system
        assert "trade-off" in system.lower() or "prioritize" in system.lower()

    def test_synthesis_phase(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = self._make_agent_at_progress(mock_provider, helix, 0.9)
        task = agent.build_task(sample_game_state)
        system, user = agent.create_position_aware_prompt(task)
        assert "SYNTHESIS" in system
        assert "decisive" in system.lower()

    def test_system_prompt_has_json_schema(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = self._make_agent_at_progress(mock_provider, helix, 0.1)
        task = agent.build_task(sample_game_state)
        system, _ = agent.create_position_aware_prompt(task)
        assert "action_type" in system
        assert "JSON" in system

    def test_system_prompt_has_allowed_actions(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = self._make_agent_at_progress(mock_provider, helix, 0.1)
        task = agent.build_task(sample_game_state)
        system, _ = agent.create_position_aware_prompt(task)
        assert "set_work_priority" in system
        assert "ALLOWED ACTIONS" in system

    def test_user_prompt_contains_game_state(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = self._make_agent_at_progress(mock_provider, helix, 0.1)
        task = agent.build_task(sample_game_state)
        _, user = agent.create_position_aware_prompt(task)
        assert "colony state" in user.lower()
        assert "120.5" in user  # food value from fixture

    def test_context_history_in_user_prompt(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = self._make_agent_at_progress(mock_provider, helix, 0.1)
        history = [{"agent_id": "defense_commander", "content": "Drafted 2 colonists."}]
        task = agent.build_task(sample_game_state, context_history=history)
        _, user = agent.create_position_aware_prompt(task)
        assert "defense_commander" in user
        assert "Drafted 2 colonists" in user


# ------------------------------------------------------------------
# parse_action_plan
# ------------------------------------------------------------------


class TestParseActionPlan:
    def _make_result(self, content: str) -> LLMResult:
        return LLMResult(
            agent_id="d-01",
            task_id="dummy-tick-1",
            content=content,
            position_info={},
            completion_result=CompletionResult(
                content=content, model="mock", usage={},
            ),
            processing_time=0.1,
            confidence=0.5,
            temperature_used=0.5,
            token_budget_used=100,
        )

    def test_valid_json(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_action_plan_json: str,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        result = self._make_result(sample_action_plan_json)
        plan = agent.parse_action_plan(result, tick=720000)
        assert isinstance(plan, ActionPlan)
        assert plan.role == "dummy"
        assert plan.tick == 720000
        assert len(plan.actions) == 1
        assert plan.actions[0].action_type == "set_work_priority"
        assert plan.summary == "Prioritizing food production due to low food_days."

    def test_markdown_fences_stripped(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        raw = '```json\n{"actions": [], "summary": "ok"}\n```'
        result = self._make_result(raw)
        plan = agent.parse_action_plan(result, tick=1)
        assert isinstance(plan, ActionPlan)
        assert plan.actions == []

    def test_invalid_json_raises(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        result = self._make_result("This is not JSON at all")
        with pytest.raises(ActionPlanParseError) as exc_info:
            agent.parse_action_plan(result, tick=1)
        assert "Invalid JSON" in exc_info.value.reason

    def test_unknown_action_type_skipped(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        data = {
            "actions": [
                {"action_type": "totally_fake_action"},
                {"action_type": "set_work_priority", "priority": 3, "reason": "ok"},
            ],
            "summary": "mixed",
        }
        result = self._make_result(json.dumps(data))
        plan = agent.parse_action_plan(result, tick=1)
        assert len(plan.actions) == 1
        assert plan.actions[0].action_type == "set_work_priority"

    def test_disallowed_action_filtered(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        data = {
            "actions": [
                {"action_type": "draft_colonist", "target_colonist_id": "col_01"},
            ],
            "summary": "tried to draft",
        }
        result = self._make_result(json.dumps(data))
        plan = agent.parse_action_plan(result, tick=1)
        assert len(plan.actions) == 0  # draft_colonist not in ALLOWED_ACTIONS

    def test_empty_actions_ok(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        result = self._make_result('{"actions": [], "summary": "nothing to do"}')
        plan = agent.parse_action_plan(result, tick=1)
        assert plan.actions == []
        assert plan.summary == "nothing to do"

    def test_defaults_for_missing_fields(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        data = {
            "actions": [{"action_type": "no_action"}],
        }
        result = self._make_result(json.dumps(data))
        plan = agent.parse_action_plan(result, tick=1)
        assert plan.summary == ""
        assert plan.actions[0].priority == 5
        assert plan.actions[0].reason == ""


# ------------------------------------------------------------------
# deliberate
# ------------------------------------------------------------------


class TestDeliberate:
    def test_full_pipeline(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        plan = agent.deliberate(sample_game_state, current_time=0.2)
        assert isinstance(plan, ActionPlan)
        assert plan.role == "dummy"
        assert plan.tick == 720000
        assert agent._last_action_plan is plan
        # Provider was called exactly once
        mock_provider.complete.assert_called_once()
