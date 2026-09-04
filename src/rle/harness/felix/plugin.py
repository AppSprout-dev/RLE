"""Entry-point plugin for the Felix multi-agent harness.

This module is the optional-dependency boundary for ``felix-agent-sdk``: it
is imported by the plugin registry on every ``--harness list``, so it must
not import the SDK at module load. The SDK-dependent modules are imported
inside the methods that need them (documented exception to the
no-inline-imports rule).
"""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from pydantic import BaseModel

from rle.harness.protocol import Availability, BaseHarness, HarnessContext

FELIX_DESCRIPTION = (
    "MapAnalyst + 6 role agents over Felix SDK CentralPost, merged by ActionResolver "
    "(the original RLE harness)."
)


class FelixPlugin:
    name = "felix"
    description = FELIX_DESCRIPTION

    def available(self) -> Availability:
        if find_spec("felix_agent_sdk") is None:
            return Availability.missing(
                "felix-agent-sdk is not installed — `uv sync --extra felix`",
            )
        return Availability.available()

    def option_schema(self) -> type[BaseModel]:
        from rle.harness.felix.options import FelixOptions  # noqa: PLC0415 - optional dep

        return FelixOptions

    def create(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        from rle.harness.felix.build import build_felix_harness  # noqa: PLC0415 - optional dep

        return build_felix_harness(ctx, options)

    def smoke(self, ctx: HarnessContext, options: BaseModel) -> BaseHarness:
        from rle.harness.felix.build import build_felix_harness  # noqa: PLC0415 - optional dep

        return build_felix_harness(ctx, options, smoke=True)

    def describe(self) -> dict[str, str]:
        info: dict[str, Any] = {"harness": self.name}
        if self.available().ok:
            from rle.harness.felix.harness import felix_sdk_version  # noqa: PLC0415

            info["felix_agent_sdk"] = felix_sdk_version()
        return info


PLUGIN = FelixPlugin()
