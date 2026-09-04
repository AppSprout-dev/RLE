"""Harness-neutral action vocabulary.

``Action`` / ``ActionPlan`` are what every harness hands the environment;
``json_repair`` is a generic LLM-output cleaner any LLM-backed harness can
reuse. The Felix role agents that used to live here are now
``rle.harness.felix.agents`` — this package must stay importable without
``felix-agent-sdk``.
"""

from rle.agents.actions import Action, ActionPlan, ActionPlanParseError, resolve_endpoint
from rle.agents.json_repair import repair_json, try_parse_json

__all__ = [
    "Action",
    "ActionPlan",
    "ActionPlanParseError",
    "repair_json",
    "resolve_endpoint",
    "try_parse_json",
]
