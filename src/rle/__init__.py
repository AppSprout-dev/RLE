"""RLE — RimWorld Learning Environment.

Multi-agent benchmark where Felix Agent SDK agents play RimWorld.
"""

__version__ = "0.1.0"

from rle.agents import (
    Action,
    ActionPlan,
    ActionPlanParseError,
    ActionType,
    ConstructionPlanner,
    DefenseCommander,
    MedicalOfficer,
    ResearchDirector,
    ResourceManager,
    RimWorldRoleAgent,
    SocialOverseer,
    register_rle_agents,
)
from rle.config import RLEConfig
from rle.orchestration import (
    ActionExecutor,
    ActionResolver,
    CrisisState,
    ExecutionResult,
    GameStateManager,
    RLEGameLoop,
    TickResult,
)
from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import (
    ColonistData,
    ColonyData,
    GameState,
    MapData,
    ResearchData,
    ResourceData,
    StructureData,
    ThreatData,
    WeatherData,
)
from rle.scenarios import (
    EvaluationResult,
    ScenarioConfig,
    ScenarioEvaluator,
    list_scenarios,
    load_scenario,
)
from rle.scoring import (
    ALL_METRICS,
    CompositeScorer,
    MetricContext,
    ScoreSnapshot,
    TimeSeriesRecorder,
)

__all__ = [
    "ALL_METRICS",
    "Action",
    "ActionExecutor",
    "ActionPlan",
    "ActionPlanParseError",
    "ActionResolver",
    "ActionType",
    "ColonistData",
    "ColonyData",
    "CompositeScorer",
    "ConstructionPlanner",
    "CrisisState",
    "DefenseCommander",
    "EvaluationResult",
    "ExecutionResult",
    "GameState",
    "GameStateManager",
    "MapData",
    "MedicalOfficer",
    "MetricContext",
    "RLEConfig",
    "RLEGameLoop",
    "ResearchData",
    "ResearchDirector",
    "ResourceData",
    "ResourceManager",
    "RimAPIClient",
    "RimWorldRoleAgent",
    "ScenarioConfig",
    "ScenarioEvaluator",
    "ScoreSnapshot",
    "SocialOverseer",
    "StructureData",
    "ThreatData",
    "TickResult",
    "TimeSeriesRecorder",
    "WeatherData",
    "list_scenarios",
    "load_scenario",
    "register_rle_agents",
]
