"""Host the RLE MCP server in-process over streamable HTTP.

Harnesses that drive an external coding agent start one of these so the
agent's MCP client and the environment share a single ledger in memory.
"""

from __future__ import annotations

import asyncio
import socket

import uvicorn
from mcp.server.mcpserver import MCPServer

MCP_PATH = "/mcp"


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


class McpHost:
    def __init__(self, server: MCPServer, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self._server = server
        self._host = host
        self._port = port or free_port(host)
        self._uvicorn: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}{MCP_PATH}"

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, *, timeout_s: float = 10.0) -> str:
        if self.running:
            return self.url
        app = self._server.streamable_http_app(
            streamable_http_path=MCP_PATH, host=self._host, stateless_http=True,
        )
        config = uvicorn.Config(app, host=self._host, port=self._port, log_level="warning")
        self._uvicorn = uvicorn.Server(config)
        self._task = asyncio.create_task(self._uvicorn.serve())
        deadline = asyncio.get_running_loop().time() + timeout_s
        while not self._uvicorn.started:
            if self._task.done():
                self._task.result()  # re-raise startup failure
                raise RuntimeError("MCP host exited before starting")
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("MCP host did not start in time")
            await asyncio.sleep(0.02)
        return self.url

    async def stop(self) -> None:
        if self._uvicorn is not None:
            self._uvicorn.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        self._task = None
        self._uvicorn = None
