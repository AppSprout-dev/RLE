"""A scripted stand-in for an external coding agent (smoke tests).

Connects to the RLE MCP server like a real agent would, reads the brief,
issues a fixed script of tool calls, and ends the turn. External harness
packages use :class:`ScriptedMcpHarness` for their ``plugin.smoke`` so the
full MCP round trip is exercised in CI without the real binary.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from mcp.client.client import Client

from rle.harness.cli_base import HeadlessCliHarness, HeadlessCliOptions, TurnResult

DEFAULT_SCRIPT: tuple[tuple[str, dict[str, Any]], ...] = (
    ("get_brief", {}),
    ("research_target", {"parameters": {"project": "Electricity"}, "reason": "smoke"}),
    ("end_turn", {"summary": "scripted smoke turn"}),
)


class ScriptedMcpHarness(HeadlessCliHarness):
    """Plays a fixed tool-call script through the MCP server each turn."""

    name: ClassVar[str] = "scripted-mcp"

    def __init__(
        self,
        options: HeadlessCliOptions | None = None,
        script: Sequence[tuple[str, dict[str, Any]]] = DEFAULT_SCRIPT,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(options or HeadlessCliOptions())
        self.script = list(script)
        self.turns: list[str] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        if name:
            self.name = name  # type: ignore[misc]  # per-instance override for plugins
        self._url: str | None = None

    async def start_agent(self, mcp_url: str) -> None:
        self._url = mcp_url

    async def send_turn(self, prompt: str) -> TurnResult:
        assert self._url is not None
        self.turns.append(prompt)
        texts: list[str] = []
        async with Client(self._url) as client:
            for tool, args in self.script:
                result = await client.call_tool(tool, args)
                self.calls.append((tool, args))
                content = getattr(result, "content", None) or []
                if content:
                    texts.append(str(getattr(content[0], "text", "")))
        return TurnResult(
            text="\n".join(texts), prompt_tokens=len(prompt) // 4, completion_tokens=32,
        )

    async def stop_agent(self) -> None:
        self._url = None

    def agent_versions(self) -> dict[str, str]:
        return {"scripted_agent": "1"}
