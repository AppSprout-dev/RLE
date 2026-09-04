"""Test utilities exported for harness plugin authors.

External harness packages depend on ``rimworld-learning-environment`` and use
these helpers so they never copy RLE internals:

- :class:`MockRimAPI` / :func:`make_mock_transport` — fake RIMAPI transport
- :func:`run_harness_smoke` — drive a plugin through ``RLEGameLoop`` for a
  few ticks against the mock and return the tick results
"""

from rle.testing.mock_rimapi import MOCK_ROUTES, MockRimAPI, make_mock_transport
from rle.testing.smoke import SmokeReport, run_harness_smoke

__all__ = [
    "MOCK_ROUTES",
    "MockRimAPI",
    "SmokeReport",
    "make_mock_transport",
    "run_harness_smoke",
]
