"""Entry-point plugin for the raw stock-grok model baseline.

Cheap to import: the MCP-dependent harness is loaded only in ``create`` /
``smoke``. ``available()`` probes PATH and the ``mcp`` extra.
"""

from __future__ import annotations

from importlib.util import find_spec

from pydantic import BaseModel

from rle.harness.protocol import Availability, BaseHarness, HarnessContext
from rle.harness.raw_grok.binary import binary_version, resolve_binary

RAW_GROK_DESCRIPTION = (
    "MODEL BASELINE: stock grok binary, one HeadlessCliHarness turn per tick "
    "(TURN_RULES only). Not a product harness — do not compare to felix or "
    "external coding-agent packages as an architecture."
)


class RawGrokPlugin:
    name = "raw-grok"
    description = RAW_GROK_DESCRIPTION

    def available(self) -> Availability:
        if find_spec("mcp") is None:
            return Availability.missing(
                "mcp extra is not installed — `uv sync --extra mcp`",
            )
        if resolve_binary("grok") is None:
            return Availability.missing(
                "stock grok binary not on PATH — install grok or pass "
                "--harness-opt binary=/path/to/grok",
            )
        return Availability.available()

    def option_schema(self) -> type[BaseModel]:
        from rle.harness.raw_grok.options import RawGrokOptions  # noqa: PLC0415

        return RawGrokOptions

    def create(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        from rle.harness.raw_grok.harness import RawGrokHarness  # noqa: PLC0415
        from rle.harness.raw_grok.options import RawGrokOptions  # noqa: PLC0415

        assert isinstance(options, RawGrokOptions)
        if resolve_binary(options.binary) is None:
            raise RuntimeError(
                f"stock grok binary {options.binary!r} not found; "
                "set --harness-opt binary=...",
            )
        return RawGrokHarness(options)

    def smoke(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        from rle.harness.raw_grok.options import RawGrokOptions  # noqa: PLC0415
        from rle.testing.scripted_agent import ScriptedMcpHarness  # noqa: PLC0415

        assert isinstance(options, RawGrokOptions)
        return ScriptedMcpHarness(options, name=self.name)

    def describe(self) -> dict[str, str]:
        info = {"harness": self.name, "kind": "model-baseline"}
        if self.available().ok:
            info["grok"] = binary_version("grok")
        return info


PLUGIN = RawGrokPlugin()
