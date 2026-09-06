"""RLE — RimWorld Learning Environment.

A harness x model benchmark: swappable harnesses (Felix multi-agent, an
unmanaged baseline, external coding agents over MCP, ...) manage a RimWorld
colony and are scored on the same footing. This top-level package is
framework-free; the Felix harness lives under ``rle.harness.felix`` behind
the optional ``felix`` extra.
"""

__version__ = "0.5.1"  # x-release-please-version

from rle.agents import (
    Action,
    ActionPlan,
    ActionPlanParseError,
    resolve_endpoint,
)
from rle.config import RLEConfig
from rle.harness import BaseHarness, HarnessContext, StepResult, create_harness
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
    "BaseHarness",
    "resolve_endpoint",
    "ColonistData",
    "ColonyData",
    "CompositeScorer",
    "CrisisState",
    "EvaluationResult",
    "ExecutionResult",
    "GameState",
    "GameStateManager",
    "HarnessContext",
    "MapData",
    "MetricContext",
    "RLEConfig",
    "RLEGameLoop",
    "ResearchData",
    "ResourceData",
    "RimAPIClient",
    "ScenarioConfig",
    "ScenarioEvaluator",
    "ScoreSnapshot",
    "StepResult",
    "StructureData",
    "ThreatData",
    "TickResult",
    "TimeSeriesRecorder",
    "WeatherData",
    "create_harness",
    "list_scenarios",
    "load_scenario",
]
