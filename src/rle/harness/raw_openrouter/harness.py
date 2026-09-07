"""Drive OpenRouter (OpenAI-compat) through the HeadlessCliHarness turn protocol.

Model-only baseline: one prompt per tick, the model acts through the in-process
RLE MCP tools (``get_brief`` / writes / ``end_turn``), ``TURN_RULES`` only.
No Felix roles, no coding-agent product, no XAI / grok binary.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

import httpx
from mcp.client.client import Client

from rle.harness.cli_base import HeadlessCliHarness, TurnResult
from rle.harness.protocol import HarnessStepError
from rle.harness.raw_openrouter.auth import resolve_api_key, resolve_base_url
from rle.harness.raw_openrouter.openai_compat import (
    assistant_message,
    complete_chat,
    extract_cost_usd,
    extract_generation_id,
    extract_usage,
    history_assistant_message,
    mcp_result_text,
    openai_tools_from_mcp,
    openrouter_headers,
    parse_tool_call,
)
from rle.harness.raw_openrouter.options import RawOpenRouterOptions

logger = logging.getLogger(__name__)


class RawOpenRouterHarness(HeadlessCliHarness):
    name: ClassVar[str] = "raw-openrouter"

    def __init__(self, options: RawOpenRouterOptions) -> None:
        super().__init__(options)
        self.opts = options
        self._mcp_url: str | None = None
        self._http: httpx.AsyncClient | None = None
        self._inflight: asyncio.Task[dict[str, Any]] | None = None

    def _api_key(self) -> str:
        key = resolve_api_key(self.opts.api_key, self.ctx.config.openrouter_api_key)
        if key is None:
            raise HarnessStepError(
                "OPENROUTER_API_KEY is not set — export it or pass "
                "--harness-opt api_key=...",
            )
        return key

    def _base_url(self) -> str:
        return resolve_base_url(self.opts.base_url, self.ctx.config.provider_base_url)

    def _model(self) -> str:
        model = self.opts.model or self.ctx.config.model
        if not model:
            raise HarnessStepError(
                "raw-openrouter needs --model (OpenRouter slug, e.g. "
                "google/gemini-3.8-flash)",
            )
        return model

    async def start_agent(self, mcp_url: str) -> None:
        self._mcp_url = mcp_url
        self._http = httpx.AsyncClient(
            base_url=self._base_url(),
            headers=openrouter_headers(
                self._api_key(),
                referer=self.opts.http_referer,
                title=self.opts.x_title,
            ),
            timeout=self.opts.turn_timeout_s,
        )
        logger.info(
            "raw-openrouter model=%s base=%s MCP %s",
            self._model(), self._base_url(), mcp_url,
        )

    async def send_turn(self, prompt: str) -> TurnResult:
        if self._mcp_url is None or self._http is None:
            raise HarnessStepError("raw-openrouter is not started")
        model = self._model()
        prompt_tokens = completion_tokens = reasoning_tokens = 0
        gen_ids: list[str] = []
        cost_sum = 0.0
        has_cost = False
        last_text = ""

        async with Client(self._mcp_url) as mcp:
            tools = openai_tools_from_mcp(await mcp.list_tools())
            messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
            ended = False
            for _round in range(self.opts.max_rounds):
                payload = await self._complete(messages, tools, model)
                p, c, r = extract_usage(payload)
                prompt_tokens += p
                completion_tokens += c
                reasoning_tokens += r
                gen_id = extract_generation_id(payload)
                if gen_id:
                    gen_ids.append(gen_id)
                cost = extract_cost_usd(payload)
                if cost is not None:
                    cost_sum += cost
                    has_cost = True
                message = assistant_message(payload)
                last_text = str(message.get("content") or last_text)
                tool_calls = message.get("tool_calls") or []
                messages.append(history_assistant_message(message))
                if not tool_calls:
                    break
                for tc in tool_calls:
                    name, args, tc_id = parse_tool_call(tc)
                    if not name:
                        continue
                    result = await mcp.call_tool(name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": mcp_result_text(result),
                    })
                    if name == "end_turn":
                        ended = True
                if ended:
                    break
            else:
                logger.warning(
                    "raw-openrouter hit max_rounds=%s without end_turn",
                    self.opts.max_rounds,
                )

        extras: dict[str, Any] = {
            "generation_ids": gen_ids,
            "kind": "model-baseline",
            "provider": "openrouter",
        }
        if has_cost:
            extras["cost_usd"] = round(cost_sum, 6)
            extras["cost_source"] = "billed"
        return TurnResult(
            text=last_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            extras=extras,
        )

    async def _complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str,
    ) -> dict[str, Any]:
        assert self._http is not None
        task = asyncio.create_task(
            complete_chat(self._http, model=model, messages=messages, tools=tools),
        )
        self._inflight = task
        try:
            return await task
        finally:
            if self._inflight is task:
                self._inflight = None

    async def abort_turn(self) -> None:
        task = self._inflight
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, HarnessStepError):
            pass
        if self._inflight is task:
            self._inflight = None

    async def stop_agent(self) -> None:
        await self.abort_turn()
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self._mcp_url = None

    def agent_versions(self) -> dict[str, str]:
        return {"kind": "model-baseline", "provider": "openrouter"}
