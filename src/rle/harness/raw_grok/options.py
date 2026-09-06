"""Options for the raw stock-grok model baseline."""

from __future__ import annotations

from pydantic import Field

from rle.harness.cli_base import HeadlessCliOptions


class RawGrokOptions(HeadlessCliOptions):
    """Stock ``grok`` binary + inherited MCP / turn knobs.

    ``turn_timeout_s`` defaults to 180 (``HeadlessCliOptions``). Comparisons
    against slower coding-agent harnesses should pass ``turn_timeout_s=300``.
    """

    binary: str = Field(
        default="grok",
        description="Stock grok executable (name or path).",
    )
