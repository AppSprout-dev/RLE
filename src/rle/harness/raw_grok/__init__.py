"""Raw stock-``grok`` model baseline (not a product harness).

Scored like other ``HeadlessCliHarness`` tools: one prompt per tick, act
through the RLE MCP turn protocol (``get_brief`` / writes / ``end_turn``).
Prompt engineering is ``TURN_RULES`` only — no tool-naming notes, no
isolated home, no MCP healthcheck, no extra_instructions by default.

This is a model baseline for attributing results to the model rather than
to a coding-agent product wrapper. It is not comparable to ``felix`` or
external product harnesses as a decision architecture.

``felix-agent-sdk`` is not used. See ``docs/harness-plugins.md``.
"""

from rle.harness.raw_grok.plugin import PLUGIN, RawGrokPlugin

__all__ = ["PLUGIN", "RawGrokPlugin"]
