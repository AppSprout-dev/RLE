"""OpenRouter model-only baseline (not a product or agent harness).

Scored like other ``HeadlessCliHarness`` tools: one prompt per tick, act
through the RLE MCP turn protocol (``get_brief`` / writes / ``end_turn``).
The model is called via OpenRouter's OpenAI-compatible ``/chat/completions``
API. Prompt engineering is ``TURN_RULES`` only.

This is a model baseline for attributing results to the model rather than
to a coding-agent product wrapper or the Felix multi-agent stack. It is not
XAI / ``raw-grok`` and is not comparable to ``felix`` or external product
harnesses as a decision architecture.

``felix-agent-sdk`` is not used. See ``docs/harness-plugins.md``.
"""

from rle.harness.raw_openrouter.plugin import PLUGIN, RawOpenRouterPlugin

__all__ = ["PLUGIN", "RawOpenRouterPlugin"]
