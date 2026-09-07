"""OpenAI-compatible chat/completions helpers for the OpenRouter model baseline.

Framework-free: httpx only. No Felix SDK, no XAI / grok binary, no MCP import.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from rle.agents.json_repair import try_parse_json
from rle.harness.protocol import HarnessStepError
from rle.harness.raw_openrouter.auth import DEFAULT_REFERER, DEFAULT_TITLE


def openrouter_headers(
    api_key: str,
    *,
    referer: str = DEFAULT_REFERER,
    title: str = DEFAULT_TITLE,
) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": title,
    }


def extract_generation_id(payload: dict[str, Any]) -> str | None:
    """OpenRouter chat-completion ``id`` (``gen-...``) for ``/generation`` billing."""
    gen_id = payload.get("id")
    return gen_id if isinstance(gen_id, str) and gen_id else None


def extract_usage(payload: dict[str, Any]) -> tuple[int, int, int]:
    """Return ``(prompt, completion, reasoning)`` tokens; never raises."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0
    prompt = _as_int(usage.get("prompt_tokens"))
    completion = _as_int(usage.get("completion_tokens"))
    details = usage.get("completion_tokens_details")
    reasoning = 0
    if isinstance(details, dict):
        reasoning = _as_int(details.get("reasoning_tokens"))
    if not reasoning:
        reasoning = _as_int(usage.get("reasoning_tokens"))
    return prompt, completion, reasoning


def extract_cost_usd(payload: dict[str, Any]) -> float | None:
    """Native USD from OpenRouter ``usage.cost`` when ``usage.include`` was set."""
    usage = payload.get("usage")
    raw: Any = usage.get("cost") if isinstance(usage, dict) else None
    if raw is None:
        raw = payload.get("cost")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def iter_mcp_tools(listed: Any) -> list[Any]:
    """Normalize ``Client.list_tools()`` (list or ``.tools`` container)."""
    if listed is None:
        return []
    if isinstance(listed, (list, tuple)):
        return list(listed)
    tools = getattr(listed, "tools", None)
    if tools is not None:
        return list(tools)
    return []


def mcp_tool_to_openai(tool: Any) -> dict[str, Any]:
    """Map one MCP tool descriptor to an OpenAI ``tools[]`` function entry."""
    name = _tool_attr(tool, "name")
    description = _tool_attr(tool, "description") or ""
    schema = _tool_attr(tool, "inputSchema")
    if schema is None:
        schema = _tool_attr(tool, "input_schema")
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump()
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": str(name or ""),
            "description": str(description),
            "parameters": schema,
        },
    }


def openai_tools_from_mcp(listed: Any) -> list[dict[str, Any]]:
    return [mcp_tool_to_openai(tool) for tool in iter_mcp_tools(listed)]


def assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise HarnessStepError("OpenRouter completion had no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise HarnessStepError("OpenRouter choice was not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise HarnessStepError("OpenRouter choice had no message")
    return message


def history_assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    """Assistant turn as the API expects it on the next request."""
    out: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
    tool_calls = message.get("tool_calls")
    if tool_calls:
        out["tool_calls"] = tool_calls
    return out


def parse_tool_call(tc: Any) -> tuple[str, dict[str, Any], str]:
    """Return ``(name, arguments, tool_call_id)`` from an OpenAI tool_call."""
    if not isinstance(tc, dict):
        return "", {}, ""
    fn = tc.get("function")
    if not isinstance(fn, dict):
        fn = {}
    name = str(fn.get("name") or "")
    args = _parse_arguments(fn.get("arguments"))
    tc_id = str(tc.get("id") or name)
    return name, args, tc_id


def mcp_result_text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            parts.append(str(text))
        elif isinstance(item, dict) and item.get("text"):
            parts.append(str(item["text"]))
    if parts:
        return "\n".join(parts)
    if isinstance(result, str):
        return result
    return json.dumps(result, default=str) if result is not None else ""


async def complete_chat(
    client: httpx.AsyncClient,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    path: str = "/chat/completions",
) -> dict[str, Any]:
    """POST one OpenAI-compat chat completion. Raises ``HarnessStepError``."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "usage": {"include": True},
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    try:
        resp = await client.post(path, json=body)
    except httpx.HTTPError as exc:
        raise HarnessStepError(f"OpenRouter request failed: {exc}") from exc
    if resp.status_code != 200:
        raise HarnessStepError(
            f"OpenRouter HTTP {resp.status_code}: {resp.text[:800]}",
        )
    try:
        data: Any = resp.json()
    except json.JSONDecodeError as exc:
        raise HarnessStepError(
            f"OpenRouter returned non-JSON: {resp.text[:400]}",
        ) from exc
    if not isinstance(data, dict):
        raise HarnessStepError("OpenRouter returned a non-object completion")
    error = data.get("error")
    if error:
        msg = error.get("message", error) if isinstance(error, dict) else error
        raise HarnessStepError(f"OpenRouter error: {msg}")
    if not data.get("choices"):
        raise HarnessStepError("OpenRouter completion had no choices")
    return data


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        loaded: Any = json.loads(raw)
    except json.JSONDecodeError:
        parsed = try_parse_json(raw)
        return parsed if parsed is not None else {}
    return loaded if isinstance(loaded, dict) else {}


def _tool_attr(tool: Any, key: str) -> Any:
    if isinstance(tool, dict):
        return tool.get(key)
    return getattr(tool, key, None)


def _as_int(raw: Any) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0
