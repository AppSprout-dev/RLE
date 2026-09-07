"""Entry-point plugin for the OpenRouter model-only baseline.

Cheap to import: the MCP-dependent harness is loaded only in ``create`` /
``smoke``. ``available()`` probes the ``mcp`` extra and an OpenRouter key.
"""

from __future__ import annotations

from importlib.util import find_spec

from pydantic import BaseModel

from rle.harness.protocol import Availability, BaseHarness, HarnessContext
from rle.harness.raw_openrouter.auth import config_openrouter_key, resolve_api_key

RAW_OPENROUTER_DESCRIPTION = (
    "MODEL BASELINE: OpenRouter OpenAI-compat chat completions, one "
    "HeadlessCliHarness turn per tick (TURN_RULES only). Not XAI / raw-grok. "
    "Not a product or agent harness — do not compare to felix or external "
    "coding-agent packages as an architecture."
)


class RawOpenRouterPlugin:
    name = "raw-openrouter"
    description = RAW_OPENROUTER_DESCRIPTION

    def available(self) -> Availability:
        if find_spec("mcp") is None:
            return Availability.missing(
                "mcp extra is not installed — `uv sync --extra mcp`",
            )
        if resolve_api_key(config_key=config_openrouter_key()) is None:
            return Availability.missing(
                "OPENROUTER_API_KEY is not set — export it or pass "
                "--harness-opt api_key=...",
            )
        return Availability.available()

    def option_schema(self) -> type[BaseModel]:
        from rle.harness.raw_openrouter.options import RawOpenRouterOptions  # noqa: PLC0415

        return RawOpenRouterOptions

    def create(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        from rle.harness.raw_openrouter.harness import RawOpenRouterHarness  # noqa: PLC0415
        from rle.harness.raw_openrouter.options import RawOpenRouterOptions  # noqa: PLC0415

        assert isinstance(options, RawOpenRouterOptions)
        if resolve_api_key(options.api_key, ctx.config.openrouter_api_key) is None:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set; export it or pass "
                "--harness-opt api_key=...",
            )
        return RawOpenRouterHarness(options)

    def smoke(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        from rle.harness.raw_openrouter.options import RawOpenRouterOptions  # noqa: PLC0415
        from rle.testing.scripted_agent import ScriptedMcpHarness  # noqa: PLC0415

        assert isinstance(options, RawOpenRouterOptions)
        return ScriptedMcpHarness(options, name=self.name)

    def describe(self) -> dict[str, str]:
        return {
            "harness": self.name,
            "kind": "model-baseline",
            "provider": "openrouter",
        }


PLUGIN = RawOpenRouterPlugin()
