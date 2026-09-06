"""Bind vs advertise settings for the in-process MCP HTTP host.

A Linux Docker container cannot reach ``127.0.0.1`` on the host. Container-
reachable mode binds ``0.0.0.0`` and advertises ``host.docker.internal`` so
an agent inside the container (stock grok-build on Docker Desktop, other
CLI harnesses) can call the host-side MCP server.

This is the opposite topology of ``--docker`` (headless RimWorld in a
container, RIMAPI published on localhost:8765). Enabling container-reachable
MCP does not change RIMAPI; the game stays on ``localhost:8765``.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ConfigDict

MCP_PATH = "/mcp"

LOCAL_BIND_HOST = "127.0.0.1"
LOCAL_ADVERTISE_HOST = "127.0.0.1"
LOCAL_PORT = 0  # ephemeral

CONTAINER_BIND_HOST = "0.0.0.0"
CONTAINER_ADVERTISE_HOST = "host.docker.internal"
CONTAINER_PORT = 8766

_WILDCARD_BIND_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})

_T = TypeVar("_T")


class McpListenSettings(BaseModel):
    """Where the MCP HTTP server listens vs what agents are told to call."""

    model_config = ConfigDict(frozen=True)

    bind_host: str
    advertise_host: str
    port: int
    """0 means pick an ephemeral port at bind time."""

    def url(self) -> str:
        return advertised_mcp_url(self.advertise_host, self.port)

    def with_port(self, port: int) -> McpListenSettings:
        return McpListenSettings(
            bind_host=self.bind_host, advertise_host=self.advertise_host, port=port,
        )


def advertised_mcp_url(host: str, port: int) -> str:
    """Build the streamable-HTTP MCP URL agents should be given."""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}{MCP_PATH}"


def first_not_none(*values: _T | None) -> _T | None:
    for value in values:
        if value is not None:
            return value
    return None


def first_host(*values: str | None) -> str | None:
    for value in values:
        if value is not None and value.strip():
            return value.strip()
    return None


def resolve_mcp_listen(
    *,
    container_reachable: bool = False,
    bind_host: str | None = None,
    advertise_host: str | None = None,
    port: int | None = None,
) -> McpListenSettings:
    """Resolve bind / advertise / port from an optional container-reachable mode.

    Explicit values always win. Unset fields take mode defaults:

    * local (default): bind and advertise ``127.0.0.1``, ephemeral port
    * container-reachable: bind ``0.0.0.0``, advertise
      ``host.docker.internal``, port ``8766`` (not 8765 — that is RIMAPI)
    """
    resolved_bind = first_host(bind_host) or (
        CONTAINER_BIND_HOST if container_reachable else LOCAL_BIND_HOST
    )
    if advertise_host is not None and advertise_host.strip():
        resolved_advertise = advertise_host.strip()
    elif container_reachable:
        resolved_advertise = CONTAINER_ADVERTISE_HOST
    elif resolved_bind in _WILDCARD_BIND_HOSTS:
        resolved_advertise = LOCAL_ADVERTISE_HOST
    else:
        resolved_advertise = resolved_bind
    if port is not None:
        resolved_port = port
    else:
        resolved_port = CONTAINER_PORT if container_reachable else LOCAL_PORT
    return McpListenSettings(
        bind_host=resolved_bind,
        advertise_host=resolved_advertise,
        port=resolved_port,
    )
