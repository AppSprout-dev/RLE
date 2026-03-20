"""Tests for ResourceManager role agent."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from felix_agent_sdk import AgentFactory
from felix_agent_sdk.core import HelixConfig, HelixGeometry
from rle.agents import register_rle_agents
from rle.agents.actions import ActionPlan, ActionType
from rle.agents.resource_manager import ResourceManager
from rle.rimapi.schemas import GameState

# ------------------------------------------------------------------
# Construction & class vars
# ------------------------------------------------------------------


class TestResourceManagerClassVars:
    def test_role_name(self) -> None:
        assert ResourceManager.ROLE_NAME == "resource_manager"

    def test_allowed_actions(self) -> None:
        expected = {
            ActionType.SET_WORK_PRIORITY,
            ActionType.HAUL_RESOURCE,
            ActionType.SET_GROWING_ZONE,
            ActionType.TOGGLE_POWER,
            ActionType.NO_ACTION,
        }
        assert ResourceManager.ALLOWED_ACTIONS == expected

    def test_temperature_range(self) -> None:
        assert ResourceManager.TEMPERATURE_RANGE == (0.2, 0.7)


# ------------------------------------------------------------------
# filter_game_state
# ------------------------------------------------------------------


class TestFilterGameState:
    def test_includes_resources(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert "resources" in filtered
        assert filtered["resources"]["food"] == 120.5
        assert filtered["resources"]["steel"] == 300

    def test_includes_colony_summary(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["colony"]["day"] == 12
        assert filtered["colony"]["food_days"] == 8.5
        assert filtered["colony"]["population"] == 3

    def test_colonist_skills_filtered_to_resource_relevant(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        colonist = filtered["colonists"][0]
        # Sample colonist has: shooting=8, construction=5, cooking=3, mining=6
        # shooting is NOT a resource skill
        assert "shooting" not in colonist["skills"]
        assert colonist["skills"]["construction"] == 5
        assert colonist["skills"]["cooking"] == 3
        assert colonist["skills"]["mining"] == 6

    def test_includes_weather_and_season(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["weather"]["condition"] == "clear"
        assert filtered["season"] == "summer"

    def test_threat_count_not_details(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["active_threats"] == 1
        assert "threats" not in filtered
        assert "threat_type" not in json.dumps(filtered)

    def test_omits_research_and_structures(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        flat = json.dumps(filtered)
        assert "research" not in filtered
        assert "structures" not in flat


# ------------------------------------------------------------------
# Prompts
# ------------------------------------------------------------------


class TestResourceManagerPrompts:
    def test_task_description(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        desc = agent._get_task_description()
        assert "food" in desc.lower()
        assert "material" in desc.lower()
        assert "power" in desc.lower()

    def test_role_description(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        desc = agent._get_role_description()
        assert "economy" in desc.lower()
        assert "food_days" in desc


# ------------------------------------------------------------------
# Full deliberation pipeline
# ------------------------------------------------------------------


class TestResourceManagerDeliberate:
    def test_produces_action_plan(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        plan = agent.deliberate(sample_game_state, current_time=0.2)
        assert isinstance(plan, ActionPlan)
        assert plan.role == "resource_manager"
        assert plan.tick == 720000

    def test_actions_within_allowed_set(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        plan = agent.deliberate(sample_game_state, current_time=0.2)
        for action in plan.actions:
            assert action.action_type in ResourceManager.ALLOWED_ACTIONS


# ------------------------------------------------------------------
# Factory registration
# ------------------------------------------------------------------


class TestRegistration:
    def test_register_and_create(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        register_rle_agents()
        try:
            factory = AgentFactory(mock_provider, HelixConfig.default())
            agent = factory.create_agent("resource_manager", agent_id="rm-test")
            assert isinstance(agent, ResourceManager)
            assert agent.agent_type == "resource_manager"
        finally:
            # Clean up shared ClassVar to avoid polluting other tests
            AgentFactory._agent_types.pop("resource_manager", None)
