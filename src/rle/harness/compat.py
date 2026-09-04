"""Backward-compatibility shims for callers that predate the harness layer.

``RLEGameLoop(config, client, agents, no_agent=..., parallel=..., visualizer=...)``
still works: this module turns those legacy arguments into a harness. It is
the one place in core that reaches for the Felix harness by module path —
through ``importlib`` so that importing the loop never imports the SDK
(documented exception to the no-inline-imports rule: optional dependency).
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from typing import Any

from rle.harness.baseline import BaselineHarness
from rle.harness.protocol import BaseHarness

FELIX_HARNESS_MODULE = "rle.harness.felix.harness"


def build_legacy_harness(
    agents: Sequence[Any] | None,
    *,
    no_agent: bool = False,
    parallel: bool = True,
    visualizer: Any | None = None,
    role_timeout_s: float = 60.0,
) -> BaseHarness:
    if no_agent or not agents:
        return BaselineHarness()
    module = import_module(FELIX_HARNESS_MODULE)
    felix_cls = module.FelixHarness
    harness: BaseHarness = felix_cls(
        list(agents),
        parallel=parallel,
        role_timeout_s=role_timeout_s,
        visualizer=visualizer,
    )
    return harness
