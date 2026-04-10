"""Lightweight JSON repair for LLM outputs.

Handles common issues: markdown fences, trailing commas, extra text
around JSON objects, and control characters.
"""

from __future__ import annotations

import json
import re


def repair_json(raw: str) -> str:
    """Apply best-effort repairs to a JSON string.

    Fixes applied in order:
    1. Strip markdown code fences
    2. Extract first JSON object via brace-depth tracking
    3. Remove trailing commas before } or ]
    4. Strip control characters (except \\n, \\t, \\r)

    Returns the repaired string, or the original if repair fails.
    """
    try:
        text = raw

        # 1a. Strip <think>...</think> blocks (Nemotron, Qwen thinking mode)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # Also handle unclosed <think> (model cut off mid-thought)
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)

        # 1b. Strip markdown code fences
        text = re.sub(r"```(?:json)?\s*\n?", "", text)

        # 2. Extract first JSON object with brace-depth tracking
        text = _extract_first_object(text)

        # 3. Remove trailing commas before } or ]
        text = re.sub(r",\s*([}\]])", r"\1", text)

        # 4. Strip control characters except \n \t \r
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)

        return text
    except Exception:
        return raw


def try_parse_json(raw: str) -> dict[str, object] | None:
    """Attempt to repair and parse JSON into a dict.

    Returns None if parsing fails after repair.
    """
    try:
        repaired = repair_json(raw)
        result = json.loads(repaired)
        if isinstance(result, dict):
            return result
        return None
    except (json.JSONDecodeError, Exception):
        return None


def _extract_first_object(text: str) -> str:
    """Find the first { and its matching } respecting string quoting."""
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            if in_string:
                escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    # No matching close brace found — return from start to end
    return text[start:]
