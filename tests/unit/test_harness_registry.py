"""Tests for the harness plugin registry and the harness protocol surface."""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

from rle.agents.actions import ActionPlan
from rle.config import RLEConfig
from rle.harness import (
    Availability,
    BaseHarness,
    EmptyOptions,
    HarnessContext,
    HarnessNotFoundError,
    HarnessOptionsError,
    HarnessUnavailableError,
    StepResult,
    create_harness,
    get_plugin,
    harness_names,
    list_harnesses,
    parse_option_pairs,
    validate_options,
)
from rle.harness.baseline import BaselineHarness
from rle.harness.compat import build_legacy_harness
from rle.rimapi.client import RimAPIClient
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent


def _ctx(**overrides: object) -> HarnessContext:
    return HarnessContext(
        config=RLEConfig(tick_interval=0.0),
        client=RimAPIClient("http://test"),
        **overrides,  # type: ignore[arg-type]
    )


class TestBuiltinRegistration:
    def test_builtins_discoverable(self) -> None:
        names = harness_names()
        assert "baseline" in names
        assert "felix" in names

    def test_list_reports_package_and_availability(self) -> None:
        infos = {i.name: i for i in list_harnesses()}
        assert infos["baseline"].availability.ok
        assert infos["baseline"].package == "rimworld-learning-environment"
        assert infos["felix"].availability.ok  # felix extra installed in dev
        assert "Felix" in infos["felix"].description

    def test_unknown_name_lists_installed(self) -> None:
        with pytest.raises(HarnessNotFoundError, match="baseline"):
            get_plugin("does-not-exist")

    def test_create_baseline(self) -> None:
        harness = create_harness("baseline", _ctx())
        assert isinstance(harness, BaselineHarness)
        assert harness.name == "baseline"

    def test_create_felix_smoke_builds_seven_agents(self) -> None:
        harness = create_harness("felix", _ctx(), {"no_think": True}, smoke=True)
        assert harness.name == "felix"
        assert len(harness.agents) == 7  # type: ignore[attr-defined]

    def test_felix_options_validated(self) -> None:
        with pytest.raises(HarnessOptionsError, match="bogus"):
            create_harness("felix", _ctx(), {"bogus": 1}, smoke=True)

    def test_baseline_rejects_options(self) -> None:
        with pytest.raises(HarnessOptionsError):
            create_harness("baseline", _ctx(), {"anything": True})


class TestOptionParsing:
    def test_json_coercion(self) -> None:
        parsed = parse_option_pairs(["parallel=false", "role_timeout_s=12.5", "name=abc"])
        assert parsed == {"parallel": False, "role_timeout_s": 12.5, "name": "abc"}

    def test_bad_pair(self) -> None:
        with pytest.raises(HarnessOptionsError):
            parse_option_pairs(["novalue"])

    def test_validate_passthrough_model(self) -> None:
        plugin = get_plugin("baseline")
        opts = EmptyOptions()
        assert validate_options(plugin, opts) is opts


class _Opts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shout: bool = False


class _EchoHarness(BaseHarness):
    name: ClassVar[str] = "echo"

    def __init__(self, shout: bool) -> None:
        super().__init__()
        self.shout = shout
        self.steps = 0
        self.ended = 0
        self.torn_down = False

    async def step(
        self, state: GameState, tick: int, macro_time: float, events: list[RimAPIEvent],
    ) -> StepResult:
        self.steps += 1
        return StepResult(
            plan=ActionPlan(role="echo", tick=state.colony.tick, actions=[]),
            extras={"shout": self.shout},
        )

    async def on_tick_end(self, tick, state, step, execution, score) -> None:  # type: ignore[no-untyped-def]
        self.ended += 1
        await super().on_tick_end(tick, state, step, execution, score)

    async def teardown(self) -> None:
        self.torn_down = True


class _UnavailablePlugin:
    name = "ghost"
    description = "never runs"

    def available(self) -> Availability:
        return Availability.missing("ghost binary not on PATH")

    def option_schema(self) -> type[BaseModel]:
        return EmptyOptions

    def create(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        raise AssertionError("must not be called")

    def smoke(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        raise AssertionError("must not be called")

    def describe(self) -> dict[str, str]:
        return {}


class TestUnavailable:
    def test_unavailable_plugin_raises_with_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import rle.harness.registry as registry

        monkeypatch.setattr(registry, "get_plugin", lambda name: _UnavailablePlugin())
        with pytest.raises(HarnessUnavailableError, match="ghost binary"):
            registry.create_harness("ghost", _ctx())


class TestCompatShim:
    def test_no_agent_builds_baseline(self) -> None:
        assert isinstance(build_legacy_harness([], no_agent=True), BaselineHarness)
        assert isinstance(build_legacy_harness(None), BaselineHarness)

    def test_agents_build_felix(self) -> None:
        felix = create_harness("felix", _ctx(), smoke=True)
        rebuilt = build_legacy_harness(felix.agents, parallel=False)  # type: ignore[attr-defined]
        assert rebuilt.name == "felix"


class TestBaseHarnessDefaults:
    def test_ctx_before_setup_raises(self) -> None:
        with pytest.raises(RuntimeError):
            _ = _EchoHarness(shout=False).ctx

    async def test_setup_stores_ctx(self) -> None:
        h = _EchoHarness(shout=True)
        ctx = _ctx()
        await h.setup(ctx)
        assert h.ctx is ctx
        assert h.describe() == {"harness": "echo"}
