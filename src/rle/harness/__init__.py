"""Swappable harnesses — the decision-making side of an RLE run.

Public API for harness authors (kept stable; external harness packages depend
on it):

- :class:`BaseHarness`, :class:`StepResult`, :class:`HarnessContext`
- :class:`HarnessPlugin`, :class:`Availability`, :class:`EmptyOptions`
- :class:`TickObserver`, :class:`HarnessStepError`
- :func:`create_harness`, :func:`list_harnesses`, :func:`get_plugin`

Register a harness under the ``rle.harnesses`` entry-point group; see
``docs/harness-plugins.md``.
"""

from rle.harness.protocol import (
    Availability,
    BaseHarness,
    EmptyOptions,
    HarnessContext,
    HarnessPlugin,
    HarnessStepError,
    StepResult,
    TickObserver,
)
from rle.harness.registry import (
    ENTRY_POINT_GROUP,
    HarnessInfo,
    HarnessNotFoundError,
    HarnessOptionsError,
    HarnessUnavailableError,
    create_harness,
    get_plugin,
    harness_names,
    list_harnesses,
    parse_option_pairs,
    validate_options,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "Availability",
    "BaseHarness",
    "EmptyOptions",
    "HarnessContext",
    "HarnessInfo",
    "HarnessNotFoundError",
    "HarnessOptionsError",
    "HarnessPlugin",
    "HarnessStepError",
    "HarnessUnavailableError",
    "StepResult",
    "TickObserver",
    "create_harness",
    "get_plugin",
    "harness_names",
    "list_harnesses",
    "parse_option_pairs",
    "validate_options",
]
