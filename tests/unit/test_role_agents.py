"""Tests for all RLE role agents."""

from __future__ import annotations

from unittest.mock import MagicMock

from felix_agent_sdk import AgentFactory
from felix_agent_sdk.core import HelixConfig, HelixGeometry
from rle.agents import register_rle_agents
from rle.agents.actions import ActionPlan, ActionType
from rle.agents.base_role import _SHARED_SYSTEM_PREFIX
from rle.agents.construction_planner import ConstructionPlanner
from rle.agents.defense_commander import DefenseCommander
from rle.agents.medical_officer import MedicalOfficer
from rle.agents.research_director import ResearchDirector
from rle.agents.resource_manager import ResourceManager
from rle.agents.social_overseer import SocialOverseer
from rle.rimapi.schemas import GameState

# ==================================================================
# ResourceManager
# ==================================================================


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


class TestResourceManagerFilter:
    def test_includes_resources(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["resources"]["food"] == 120.5

    def test_colonist_skills_filtered(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        colonist = filtered["colonists"][0]
        assert "shooting" not in colonist["skills"]
        assert colonist["skills"]["construction"] == 5

    def test_omits_threat_details(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["active_threats"] == 1
        assert "threats" not in filtered

    def test_omits_research(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert "research" not in filtered


class TestResourceManagerDeliberate:
    def test_produces_action_plan(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResourceManager("rm-01", mock_provider, helix, spawn_time=0.0)
        plan = agent.deliberate(sample_game_state, current_time=0.2)
        assert isinstance(plan, ActionPlan)
        assert plan.role == "resource_manager"


# ==================================================================
# DefenseCommander
# ==================================================================


class TestDefenseCommanderClassVars:
    def test_role_name(self) -> None:
        assert DefenseCommander.ROLE_NAME == "defense_commander"

    def test_allowed_actions(self) -> None:
        expected = {
            ActionType.DRAFT_COLONIST,
            ActionType.UNDRAFT_COLONIST,
            ActionType.MOVE_COLONIST,
            ActionType.NO_ACTION,
        }
        assert DefenseCommander.ALLOWED_ACTIONS == expected

    def test_temperature_range(self) -> None:
        assert DefenseCommander.TEMPERATURE_RANGE == (0.1, 0.6)


class TestDefenseCommanderFilter:
    def test_includes_threats(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = DefenseCommander("dc-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert len(filtered["threats"]) == 1
        assert filtered["threats"][0]["threat_type"] == "raid"

    def test_includes_combat_skills(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = DefenseCommander("dc-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        colonist = filtered["colonists"][0]
        assert "shooting" in colonist["skills"]
        # cooking/mining/construction are NOT combat skills
        assert "cooking" not in colonist["skills"]

    def test_includes_drafted_status(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = DefenseCommander("dc-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert "is_drafted" in filtered["colonists"][0]

    def test_omits_resources(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = DefenseCommander("dc-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert "resources" not in filtered


# ==================================================================
# ResearchDirector
# ==================================================================


class TestResearchDirectorClassVars:
    def test_role_name(self) -> None:
        assert ResearchDirector.ROLE_NAME == "research_director"

    def test_allowed_actions(self) -> None:
        expected = {
            ActionType.SET_RESEARCH_TARGET,
            ActionType.ASSIGN_RESEARCHER,
            ActionType.NO_ACTION,
        }
        assert ResearchDirector.ALLOWED_ACTIONS == expected


class TestResearchDirectorFilter:
    def test_includes_research(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResearchDirector("rd-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["research"]["current_project"] == "electricity"
        assert "stonecutting" in filtered["research"]["completed"]

    def test_colonists_have_intellectual_only(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResearchDirector("rd-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        colonist = filtered["colonists"][0]
        # Sample colonist has no "intellectual" skill
        assert colonist["skills"] == {}

    def test_omits_threats(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ResearchDirector("rd-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert "threats" not in filtered


# ==================================================================
# SocialOverseer
# ==================================================================


class TestSocialOverseerClassVars:
    def test_role_name(self) -> None:
        assert SocialOverseer.ROLE_NAME == "social_overseer"

    def test_allowed_actions(self) -> None:
        expected = {
            ActionType.SET_RECREATION_POLICY,
            ActionType.ASSIGN_SOCIAL_ACTIVITY,
            ActionType.NO_ACTION,
        }
        assert SocialOverseer.ALLOWED_ACTIONS == expected


class TestSocialOverseerFilter:
    def test_includes_mood_data(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = SocialOverseer("so-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["colony"]["mood_average"] == 0.68
        assert "mood" in filtered["colonists"][0]
        assert "needs" in filtered["colonists"][0]

    def test_flags_mood_crisis(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = SocialOverseer("so-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        # Sample colonist mood=0.72, no crisis
        assert filtered["mood_crisis"] is False

    def test_omits_resources(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = SocialOverseer("so-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert "resources" not in filtered


# ==================================================================
# ConstructionPlanner
# ==================================================================


class TestConstructionPlannerClassVars:
    def test_role_name(self) -> None:
        assert ConstructionPlanner.ROLE_NAME == "construction_planner"

    def test_allowed_actions(self) -> None:
        expected = {
            ActionType.PLACE_BLUEPRINT,
            ActionType.CANCEL_BLUEPRINT,
            ActionType.NO_ACTION,
        }
        assert ConstructionPlanner.ALLOWED_ACTIONS == expected


class TestConstructionPlannerFilter:
    def test_includes_construction_resources(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ConstructionPlanner("cp-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["resources"]["steel"] == 300
        assert filtered["resources"]["wood"] == 450
        assert "food" not in filtered["resources"]

    def test_includes_structures(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ConstructionPlanner("cp-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert "structures" in filtered["map"]

    def test_colonists_have_construction_only(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = ConstructionPlanner("cp-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        colonist = filtered["colonists"][0]
        assert colonist["skills"] == {"construction": 5}


# ==================================================================
# MedicalOfficer
# ==================================================================


class TestMedicalOfficerClassVars:
    def test_role_name(self) -> None:
        assert MedicalOfficer.ROLE_NAME == "medical_officer"

    def test_allowed_actions(self) -> None:
        expected = {
            ActionType.ASSIGN_BED_REST,
            ActionType.ADMINISTER_MEDICINE,
            ActionType.NO_ACTION,
        }
        assert MedicalOfficer.ALLOWED_ACTIONS == expected

    def test_temperature_range(self) -> None:
        assert MedicalOfficer.TEMPERATURE_RANGE == (0.1, 0.5)


class TestMedicalOfficerFilter:
    def test_includes_health_data(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = MedicalOfficer("mo-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        colonist = filtered["colonists"][0]
        assert "health" in colonist
        assert "injuries" in colonist

    def test_includes_medicine_supply(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = MedicalOfficer("mo-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert filtered["resources"]["medicine"] == 8

    def test_flags_disease_status(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = MedicalOfficer("mo-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        # Sample threat is "raid", not "disease"
        assert filtered["disease_active"] is False

    def test_omits_research(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        agent = MedicalOfficer("mo-01", mock_provider, helix, spawn_time=0.0)
        filtered = agent.filter_game_state(sample_game_state)
        assert "research" not in filtered


# ==================================================================
# Factory registration (all 6 agents)
# ==================================================================


class TestRegistration:
    def test_register_and_create_all(
        self, mock_provider: MagicMock, helix: HelixGeometry,
    ) -> None:
        register_rle_agents()
        try:
            factory = AgentFactory(mock_provider, HelixConfig.default())
            roles = [
                ("resource_manager", ResourceManager),
                ("defense_commander", DefenseCommander),
                ("research_director", ResearchDirector),
                ("social_overseer", SocialOverseer),
                ("construction_planner", ConstructionPlanner),
                ("medical_officer", MedicalOfficer),
            ]
            for role_name, expected_cls in roles:
                agent = factory.create_agent(role_name, agent_id=f"{role_name}-test")
                assert isinstance(agent, expected_cls)
                assert agent.agent_type == role_name
        finally:
            for role_name, _ in roles:
                AgentFactory._agent_types.pop(role_name, None)


# ==================================================================
# Shared system prompt prefix (KV cache optimization)
# ==================================================================


class TestSharedSystemPrefix:
    """All 6 agents must share _SHARED_SYSTEM_PREFIX at the start of their
    system prompt, with role-specific content at the end."""

    ALL_AGENT_CLASSES = [
        ("rm", ResourceManager),
        ("dc", DefenseCommander),
        ("rd", ResearchDirector),
        ("so", SocialOverseer),
        ("cp", ConstructionPlanner),
        ("mo", MedicalOfficer),
    ]

    def _make_agent_and_prompt(
        self, agent_id: str, cls: type, mock_provider: MagicMock,
        helix: HelixGeometry, sample_game_state: GameState,
    ) -> str:
        agent = cls(agent_id, mock_provider, helix, spawn_time=0.0)
        agent.spawn(0.0)
        agent.update_position(0.2)
        task = agent.build_task(sample_game_state)
        system_prompt, _ = agent.create_position_aware_prompt(task)
        return system_prompt

    def test_all_agents_share_common_prefix(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        prompts = []
        for agent_id, cls in self.ALL_AGENT_CLASSES:
            prompts.append(
                self._make_agent_and_prompt(
                    agent_id, cls, mock_provider, helix, sample_game_state,
                )
            )

        # All prompts must start with the exact shared prefix
        for prompt in prompts:
            assert prompt.startswith(_SHARED_SYSTEM_PREFIX), (
                f"Prompt does not start with _SHARED_SYSTEM_PREFIX:\n{prompt[:200]}"
            )

        # The shared prefix must be non-trivial (at least 100 chars)
        assert len(_SHARED_SYSTEM_PREFIX) > 100

    def test_role_specific_content_at_end(
        self, mock_provider: MagicMock, helix: HelixGeometry,
        sample_game_state: GameState,
    ) -> None:
        role_suffixes: dict[str, str] = {}
        for agent_id, cls in self.ALL_AGENT_CLASSES:
            prompt = self._make_agent_and_prompt(
                agent_id, cls, mock_provider, helix, sample_game_state,
            )
            # Strip shared prefix to get the role-specific tail
            suffix = prompt[len(_SHARED_SYSTEM_PREFIX):]
            role_suffixes[cls.ROLE_NAME] = suffix

        # Each agent's suffix must contain its role name
        for role_name, suffix in role_suffixes.items():
            assert role_name in suffix, (
                f"Role-specific suffix for {role_name} doesn't contain role name"
            )

        # All 6 suffixes must be distinct (role block differs)
        unique_suffixes = set(role_suffixes.values())
        assert len(unique_suffixes) == 6, (
            "Expected 6 distinct role-specific suffixes"
        )

    def test_shared_prefix_contains_json_schema(self) -> None:
        assert '"action_type"' in _SHARED_SYSTEM_PREFIX
        assert '"confidence"' in _SHARED_SYSTEM_PREFIX
        assert "Respond ONLY with valid JSON" in _SHARED_SYSTEM_PREFIX
