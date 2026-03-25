"""Tests for ActionResolver conflict resolution."""

from __future__ import annotations

import pytest
from rle.agents.actions import Action, ActionPlan, ActionType
from rle.orchestration.action_resolver import (
    ActionResolver,
)
from rle.rimapi.schemas import (
    ColonistData,
    ColonyData,
    GameState,
    MapData,
    ResearchData,
    ResourceData,
    ThreatData,
    WeatherData,
)


def _make_state(
    threats: list[ThreatData] | None = None,
    colonist_health: float = 0.95,
) -> GameState:
    """Build a minimal GameState for resolver tests."""
    return GameState(
        colony=ColonyData(
            name="Test", wealth=1000.0, day=5, tick=300000,
            population=1, mood_average=0.7, food_days=10.0,
        ),
        colonists=[
            ColonistData(
                colonist_id="col_01", name="Tester", health=colonist_health,
                mood=0.7, skills={}, traits=[], current_job=None,
                is_drafted=False, needs={}, injuries=[], position=(0, 0),
            ),
        ],
        resources=ResourceData(
            food=100.0, medicine=5, steel=200, wood=300,
            components=10, silver=500, power_net=100.0,
        ),
        map=MapData(
            size=(250, 250), biome="temperate_forest", season="summer",
            temperature=22.0, structures=[],
        ),
        research=ResearchData(
            current_project=None, progress=0.0, completed=[], available=[],
        ),
        threats=threats or [],
        weather=WeatherData(condition="clear", temperature=22.0, outdoor_severity=0.0),
        timestamp=0.0,
    )


def _plan(role: str, actions: list[Action], confidence: float = 0.5) -> ActionPlan:
    return ActionPlan(role=role, tick=1, actions=actions, confidence=confidence)


# ------------------------------------------------------------------
# Basic resolution
# ------------------------------------------------------------------


class TestNoConflicts:
    def test_different_pawns_all_kept(self) -> None:
        resolver = ActionResolver()
        plans = [
            _plan("resource_manager", [
                Action(action_type=ActionType.SET_WORK_PRIORITY,
                       target_colonist_id="col_01", priority=3),
            ]),
            _plan("defense_commander", [
                Action(action_type=ActionType.DRAFT_COLONIST,
                       target_colonist_id="col_02", priority=2),
            ]),
        ]
        state = _make_state()
        result = resolver.resolve(plans, state)
        assert result.role == "orchestrator"
        assert len(result.actions) == 2

    def test_empty_plans(self) -> None:
        resolver = ActionResolver()
        state = _make_state()
        result = resolver.resolve([], state)
        assert result.actions == []
        assert result.role == "orchestrator"


# ------------------------------------------------------------------
# Same-pawn conflicts (Rule 2)
# ------------------------------------------------------------------


class TestSamePawnConflicts:
    def test_higher_priority_wins(self) -> None:
        resolver = ActionResolver()
        plans = [
            _plan("resource_manager", [
                Action(action_type=ActionType.SET_WORK_PRIORITY,
                       target_colonist_id="col_01", priority=5),
            ]),
            _plan("defense_commander", [
                Action(action_type=ActionType.DRAFT_COLONIST,
                       target_colonist_id="col_01", priority=1),
            ]),
        ]
        state = _make_state()
        result = resolver.resolve(plans, state)
        assert len(result.actions) == 1
        assert result.actions[0].action_type == ActionType.DRAFT_COLONIST

    def test_confidence_tiebreak(self) -> None:
        resolver = ActionResolver()
        plans = [
            _plan("resource_manager", [
                Action(action_type=ActionType.SET_WORK_PRIORITY,
                       target_colonist_id="col_01", priority=3),
            ], confidence=0.9),
            _plan("social_overseer", [
                Action(action_type=ActionType.ASSIGN_SOCIAL_ACTIVITY,
                       target_colonist_id="col_01", priority=3),
            ], confidence=0.4),
        ]
        state = _make_state()
        result = resolver.resolve(plans, state)
        assert len(result.actions) == 1
        # Same action.priority (3), same role_priority (3 vs 5), RM wins on role
        # Actually RM has role_priority=3, SO has 5, so RM wins
        assert result.actions[0].action_type == ActionType.SET_WORK_PRIORITY


# ------------------------------------------------------------------
# Emergency priority (Rule 1)
# ------------------------------------------------------------------


class TestEmergencyPriority:
    def test_raid_promotes_defense_commander(self) -> None:
        resolver = ActionResolver()
        raid = ThreatData(
            threat_id="t_01", threat_type="raid", faction="pirate",
            enemy_count=10, threat_level=0.8,
        )
        plans = [
            _plan("resource_manager", [
                Action(action_type=ActionType.SET_WORK_PRIORITY,
                       target_colonist_id="col_01", priority=1),
            ], confidence=0.9),
            _plan("defense_commander", [
                Action(action_type=ActionType.DRAFT_COLONIST,
                       target_colonist_id="col_01", priority=1),
            ], confidence=0.5),
        ]
        state = _make_state(threats=[raid])
        result = resolver.resolve(plans, state)
        assert len(result.actions) == 1
        # DC gets role_priority=1 during raid, RM stays at 3
        assert result.actions[0].action_type == ActionType.DRAFT_COLONIST

    def test_disease_promotes_medical_officer(self) -> None:
        resolver = ActionResolver()
        disease = ThreatData(
            threat_id="t_02", threat_type="disease", faction=None,
            enemy_count=0, threat_level=0.3,
        )
        plans = [
            _plan("social_overseer", [
                Action(action_type=ActionType.ASSIGN_SOCIAL_ACTIVITY,
                       target_colonist_id="col_01", priority=2),
            ]),
            _plan("medical_officer", [
                Action(action_type=ActionType.ASSIGN_BED_REST,
                       target_colonist_id="col_01", priority=2),
            ]),
        ]
        state = _make_state(threats=[disease])
        result = resolver.resolve(plans, state)
        assert len(result.actions) == 1
        assert result.actions[0].action_type == ActionType.ASSIGN_BED_REST

    def test_low_health_triggers_medical_emergency(self) -> None:
        resolver = ActionResolver()
        plans = [
            _plan("resource_manager", [
                Action(action_type=ActionType.SET_WORK_PRIORITY,
                       target_colonist_id="col_01", priority=2),
            ]),
            _plan("medical_officer", [
                Action(action_type=ActionType.ASSIGN_BED_REST,
                       target_colonist_id="col_01", priority=2),
            ]),
        ]
        state = _make_state(colonist_health=0.3)
        result = resolver.resolve(plans, state)
        assert len(result.actions) == 1
        assert result.actions[0].action_type == ActionType.ASSIGN_BED_REST


# ------------------------------------------------------------------
# Colony-level deduplication
# ------------------------------------------------------------------


class TestColonyActions:
    def test_dedup_by_action_type(self) -> None:
        resolver = ActionResolver()
        plans = [
            _plan("research_director", [
                Action(action_type=ActionType.SET_RESEARCH_TARGET,
                       parameters={"project": "electricity"}),
            ], confidence=0.8),
            _plan("resource_manager", [
                Action(action_type=ActionType.SET_RESEARCH_TARGET,
                       parameters={"project": "battery"}),
            ], confidence=0.5),
        ]
        state = _make_state()
        result = resolver.resolve(plans, state)
        research_actions = [
            a for a in result.actions
            if a.action_type == ActionType.SET_RESEARCH_TARGET
        ]
        assert len(research_actions) == 1


# ------------------------------------------------------------------
# CrisisState
# ------------------------------------------------------------------


class TestCrisisDetection:
    def test_no_crisis(self) -> None:
        resolver = ActionResolver()
        state = _make_state()
        crisis = resolver._detect_crisis(state)
        assert not crisis.raid_active
        assert not crisis.medical_emergency
        assert not crisis.disease_active

    def test_raid_detected(self) -> None:
        resolver = ActionResolver()
        raid = ThreatData(
            threat_id="t_01", threat_type="raid", faction="pirate",
            enemy_count=5, threat_level=0.7,
        )
        state = _make_state(threats=[raid])
        crisis = resolver._detect_crisis(state)
        assert crisis.raid_active
        assert crisis.max_threat_level == pytest.approx(0.7)

    def test_disease_detected(self) -> None:
        resolver = ActionResolver()
        disease = ThreatData(
            threat_id="t_02", threat_type="disease", faction=None,
            enemy_count=0, threat_level=0.2,
        )
        state = _make_state(threats=[disease])
        crisis = resolver._detect_crisis(state)
        assert crisis.disease_active
        assert crisis.medical_emergency


# ------------------------------------------------------------------
# Peacetime NO_ACTION preference (do no harm)
# ------------------------------------------------------------------


class TestPeacetimeNoAction:
    def test_no_action_wins_during_peacetime(self) -> None:
        """When no crisis is active, NO_ACTION beats a regular action for same pawn."""
        resolver = ActionResolver()
        plans = [
            _plan("resource_manager", [
                Action(action_type=ActionType.SET_WORK_PRIORITY,
                       target_colonist_id="col_01", priority=3),
            ], confidence=0.9),
            _plan("social_overseer", [
                Action(action_type=ActionType.NO_ACTION,
                       target_colonist_id="col_01", priority=5),
            ], confidence=0.5),
        ]
        state = _make_state()  # No threats = peacetime
        result = resolver.resolve(plans, state)
        pawn_actions = [a for a in result.actions if a.target_colonist_id == "col_01"]
        assert len(pawn_actions) == 1
        assert pawn_actions[0].action_type == ActionType.NO_ACTION

    def test_real_action_wins_during_raid(self) -> None:
        """During a raid, regular actions beat NO_ACTION."""
        resolver = ActionResolver()
        raid = ThreatData(
            threat_id="t_01", threat_type="raid", faction="pirate",
            enemy_count=10, threat_level=0.8,
        )
        plans = [
            _plan("defense_commander", [
                Action(action_type=ActionType.DRAFT_COLONIST,
                       target_colonist_id="col_01", priority=1),
            ]),
            _plan("resource_manager", [
                Action(action_type=ActionType.NO_ACTION,
                       target_colonist_id="col_01", priority=5),
            ]),
        ]
        state = _make_state(threats=[raid])
        result = resolver.resolve(plans, state)
        pawn_actions = [a for a in result.actions if a.target_colonist_id == "col_01"]
        assert len(pawn_actions) == 1
        assert pawn_actions[0].action_type == ActionType.DRAFT_COLONIST

    def test_real_action_wins_during_medical_emergency(self) -> None:
        """During a medical emergency, regular actions beat NO_ACTION."""
        resolver = ActionResolver()
        plans = [
            _plan("medical_officer", [
                Action(action_type=ActionType.ASSIGN_BED_REST,
                       target_colonist_id="col_01", priority=2),
            ]),
            _plan("resource_manager", [
                Action(action_type=ActionType.NO_ACTION,
                       target_colonist_id="col_01", priority=5),
            ]),
        ]
        state = _make_state(colonist_health=0.3)  # medical emergency
        result = resolver.resolve(plans, state)
        pawn_actions = [a for a in result.actions if a.target_colonist_id == "col_01"]
        assert len(pawn_actions) == 1
        assert pawn_actions[0].action_type == ActionType.ASSIGN_BED_REST


# ------------------------------------------------------------------
# Merged plan metadata
# ------------------------------------------------------------------


class TestMergedPlan:
    def test_role_is_orchestrator(self) -> None:
        resolver = ActionResolver()
        plans = [_plan("resource_manager", [
            Action(action_type=ActionType.NO_ACTION),
        ])]
        state = _make_state()
        result = resolver.resolve(plans, state)
        assert result.role == "orchestrator"

    def test_confidence_is_average(self) -> None:
        resolver = ActionResolver()
        plans = [
            _plan("resource_manager", [], confidence=0.8),
            _plan("defense_commander", [], confidence=0.6),
        ]
        state = _make_state()
        result = resolver.resolve(plans, state)
        assert result.confidence == pytest.approx(0.7)
