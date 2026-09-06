"""Host the RLE MCP server in-process over streamable HTTP.

Harnesses that drive an external coding agent start one of these so the
agent's MCP client and the environment share a single ledger in memory.

Bind address and advertised URL are separate: local runs bind and advertise
``127.0.0.1``; container-reachable mode binds ``0.0.0.0`` and advertises
``host.docker.internal`` so a Docker agent can reach a host-side server.
"""

from __future__ import annotations

import asyncio
import socket

import uvicorn
from mcp.server.mcpserver import MCPServer

from rle.mcp.listen import (
    MCP_PATH,
    McpListenSettings,
    advertised_mcp_url,
    resolve_mcp_listen,
)

__all__ = ["MCP_PATH", "McpHost", "free_port"]


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


class McpHost:
    def __init__(
        self,
        server: MCPServer,
        settings: McpListenSettings | None = None,
        *,
        bind_host: str | None = None,
        advertise_host: str | None = None,
        port: int | None = None,
    ) -> None:
        if settings is not None and (
            bind_host is not None or advertise_host is not None or port is not None
        ):
            raise TypeError("pass settings or keyword fields, not both")
        listen = settings or resolve_mcp_listen(
            bind_host=bind_host, advertise_host=advertise_host, port=port,
        )
        self._bind_host = listen.bind_host
        self._advertise_host = listen.advertise_host
        self._port = listen.port or free_port(listen.bind_host)
        self._server = server
        self._uvicorn: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def bind_host(self) -> str:
        return self._bind_host

    @property
    def advertise_host(self) -> str:
        return self._advertise_host

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        """URL handed to the agent — always the advertised host, not the bind address."""
        return advertised_mcp_url(self._advertise_host, self._port)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, *, timeout_s: float = 10.0) -> str:
        if self.running:
            return self.url
        # ``host`` here is the Host-header identity the MCP SDK uses to decide
        # whether to lock DNS-rebinding protection to loopback. Pass the
        # advertised host so container clients sending Host:
        # host.docker.internal are not rejected. uvicorn still binds bind_host.
        app = self._server.streamable_http_app(
            streamable_http_path=MCP_PATH, host=self._advertise_host, stateless_http=True,
        )
        config = uvicorn.Config(app, host=self._bind_host, port=self._port, log_level="warning")
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
