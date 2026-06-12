"""Tests for the RimWorldRoleAgent base class."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from felix_agent_sdk import LLMResult
from felix_agent_sdk.core import HelixGeometry
from felix_agent_sdk.providers.types import CompletionResult, MessageRole

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
# no-think prefill gating
# ------------------------------------------------------------------


class TestNoThinkPrefill:
    def test_prefill_appended_for_openai_provider(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        mock_provider.provider_name = "openai"
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        agent.set_no_think(True)
        agent._call_provider("sys", "user", 0.5, 100)

        messages = mock_provider.complete.call_args[0][0]
        assert messages[-1].role == MessageRole.ASSISTANT
        assert messages[-1].content == "</think>"

    @pytest.mark.parametrize("provider_name", ["anthropic", "claudecode"])
    def test_prefill_skipped_for_prefill_rejecting_providers(
        self, mock_provider: MagicMock, helix: HelixGeometry, provider_name: str,
    ) -> None:
        mock_provider.provider_name = provider_name
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        agent.set_no_think(True)
        agent._call_provider("sys", "user", 0.5, 100)

        messages = mock_provider.complete.call_args[0][0]
        assert all(m.role != MessageRole.ASSISTANT for m in messages)

    def test_no_prefill_when_disabled(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        mock_provider.provider_name = "openai"
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        agent._call_provider("sys", "user", 0.5, 100)

        messages = mock_provider.complete.call_args[0][0]
        assert all(m.role != MessageRole.ASSISTANT for m in messages)


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

    def test_aliased_action_type_accepted_via_catalog(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        class _CanonicalAgent(_DummyRoleAgent):
            ALLOWED_ACTIONS: ClassVar[set[str]] = {"work_priority", "no_action"}

        agent = _CanonicalAgent("d-01", mock_provider, helix, spawn_time=0.0)
        # Model emits the legacy alias; the canonical key is what's allowed
        result = self._make_result(
            '{"actions": [{"action_type": "set_work_priority", '
            '"target_colonist_id": "181", "parameters": {"Growing": 1}}], '
            '"summary": "ok", "confidence": 0.9}'
        )
        plan = agent.parse_action_plan(result, tick=1)
        assert len(plan.actions) == 1
        assert plan.actions[0].action_type == "set_work_priority"

    def test_missing_actions_key_raises(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        # Valid JSON in a model-invented shape (what Fable 5 produced live)
        result = self._make_result(
            '{"threat_assessment": {"condition": "GREEN"}, '
            '"defensive_actions": [{"priority": "HIGH"}]}'
        )
        with pytest.raises(ActionPlanParseError) as exc_info:
            agent.parse_action_plan(result, tick=1)
        assert '"actions"' in exc_info.value.reason
        # The retry correction prompt embeds the reason, so it must carry
        # the full expected schema
        assert "action_type" in exc_info.value.reason

    def test_actions_not_a_list_raises(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        result = self._make_result('{"actions": {"action_type": "no_action"}}')
        with pytest.raises(ActionPlanParseError) as exc_info:
            agent.parse_action_plan(result, tick=1)
        assert "must be a list" in exc_info.value.reason

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


# ------------------------------------------------------------------
# adeliberate (async path via provider.acomplete, felix 0.3.0)
# ------------------------------------------------------------------


class TestADeliberate:
    async def test_full_pipeline_uses_acomplete(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        mock_provider.acomplete.return_value = mock_provider.complete.return_value
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        plan = await agent.adeliberate(sample_game_state, current_time=0.2)
        assert isinstance(plan, ActionPlan)
        assert plan.role == "dummy"
        assert plan.tick == 720000
        assert agent._last_action_plan is plan
        mock_provider.acomplete.assert_called_once()
        mock_provider.complete.assert_not_called()

    async def test_acall_falls_back_to_sync_when_async_unsupported(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        mock_provider.acomplete.side_effect = NotImplementedError("no async")
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        result = await agent._acall_provider("sys", "user", 0.5, 100)
        assert result is mock_provider.complete.return_value
        mock_provider.complete.assert_called_once()

    async def test_acall_records_last_output_and_usage(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        completion = mock_provider.complete.return_value
        mock_provider.acomplete.return_value = completion
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        await agent._acall_provider("sys", "user", 0.5, 100)
        assert agent._last_raw_output == completion.content
        assert agent._last_usage == completion.usage

    async def test_acall_applies_no_think_prefill(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        mock_provider.provider_name = "openai"
        mock_provider.acomplete.return_value = mock_provider.complete.return_value
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        agent.set_no_think(True)
        await agent._acall_provider("sys", "user", 0.5, 100)
        messages = mock_provider.acomplete.call_args[0][0]
        assert messages[-1].role == MessageRole.ASSISTANT
        assert messages[-1].content == "</think>"


# ------------------------------------------------------------------
# reasoning-token extraction (issue #33: thinking-model cost undercount)
# ------------------------------------------------------------------


class TestReasoningTokenExtraction:
    def test_none_raw_response(self) -> None:
        assert RimWorldRoleAgent._extract_reasoning_tokens(None) == 0

    def test_openai_object_shape(self) -> None:
        details = SimpleNamespace(reasoning_tokens=4096)
        usage = SimpleNamespace(completion_tokens_details=details)
        raw = SimpleNamespace(usage=usage)
        assert RimWorldRoleAgent._extract_reasoning_tokens(raw) == 4096

    def test_openrouter_dict_shape(self) -> None:
        raw = {"usage": {"completion_tokens_details": {"reasoning_tokens": 1234}}}
        assert RimWorldRoleAgent._extract_reasoning_tokens(raw) == 1234

    def test_reasoning_directly_on_usage(self) -> None:
        raw = {"usage": {"reasoning_tokens": 77}}
        assert RimWorldRoleAgent._extract_reasoning_tokens(raw) == 77

    def test_absent_reasoning_returns_zero(self) -> None:
        raw = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        assert RimWorldRoleAgent._extract_reasoning_tokens(raw) == 0

    def test_unparseable_returns_zero(self) -> None:
        raw = {"usage": {"completion_tokens_details": {"reasoning_tokens": "lots"}}}
        assert RimWorldRoleAgent._extract_reasoning_tokens(raw) == 0

    def test_record_completion_merges_reasoning_into_usage(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        result = CompletionResult(
            content="{}",
            model="mock",
            usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            raw_response={"usage": {"completion_tokens_details": {"reasoning_tokens": 900}}},
        )
        agent._record_completion(result)
        assert agent._last_usage is not None
        assert agent._last_usage["reasoning_tokens"] == 900
        # original usage dict on the result is not mutated
        assert "reasoning_tokens" not in result.usage


# ------------------------------------------------------------------
# generation-ID capture (billed-cost reconciliation against OpenRouter)
# ------------------------------------------------------------------


class TestGenerationIdExtraction:
    def test_none_raw_response(self) -> None:
        assert RimWorldRoleAgent._extract_generation_id(None) is None

    def test_dict_shape(self) -> None:
        assert RimWorldRoleAgent._extract_generation_id({"id": "gen-abc123"}) == "gen-abc123"

    def test_object_shape(self) -> None:
        raw = SimpleNamespace(id="gen-xyz")
        assert RimWorldRoleAgent._extract_generation_id(raw) == "gen-xyz"

    def test_non_string_id_returns_none(self) -> None:
        assert RimWorldRoleAgent._extract_generation_id({"id": 12345}) is None

    def test_empty_string_returns_none(self) -> None:
        assert RimWorldRoleAgent._extract_generation_id({"id": ""}) is None


class TestGenerationIdAccumulation:
    def _result(self, gen_id: str) -> CompletionResult:
        return CompletionResult(
            content="{}",
            model="mock",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw_response={"id": gen_id, "usage": {}},
        )

    def test_every_completion_accumulates(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        """Parse retries call _record_completion again — both IDs must
        survive so failed-parse tokens are still billed (issue #04)."""
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        agent._record_completion(self._result("gen-1"))
        agent._record_completion(self._result("gen-2"))
        assert agent.drain_generation_ids() == ["gen-1", "gen-2"]

    def test_drain_clears(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        agent._record_completion(self._result("gen-1"))
        agent.drain_generation_ids()
        assert agent.drain_generation_ids() == []

    def test_no_id_in_raw_response_is_skipped(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = _DummyRoleAgent("d-01", mock_provider, helix, spawn_time=0.0)
        result = CompletionResult(
            content="{}", model="mock",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw_response={"usage": {}},
        )
        agent._record_completion(result)
        assert agent.drain_generation_ids() == []
