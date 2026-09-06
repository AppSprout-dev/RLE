"""Bind vs advertise URL construction for the MCP HTTP host (no live Docker)."""

from __future__ import annotations

from rle.mcp.listen import (
    CONTAINER_ADVERTISE_HOST,
    CONTAINER_BIND_HOST,
    CONTAINER_PORT,
    LOCAL_ADVERTISE_HOST,
    LOCAL_BIND_HOST,
    LOCAL_PORT,
    McpListenSettings,
    advertised_mcp_url,
    resolve_mcp_listen,
)


class TestAdvertisedUrl:
    def test_ipv4_and_hostname(self) -> None:
        assert advertised_mcp_url("127.0.0.1", 3456) == "http://127.0.0.1:3456/mcp"
        assert (
            advertised_mcp_url(CONTAINER_ADVERTISE_HOST, CONTAINER_PORT)
            == "http://host.docker.internal:8766/mcp"
        )

    def test_ipv6_is_bracketed(self) -> None:
        assert advertised_mcp_url("::1", 8766) == "http://[::1]:8766/mcp"
        assert advertised_mcp_url("[::1]", 8766) == "http://[::1]:8766/mcp"

    def test_settings_url(self) -> None:
        settings = McpListenSettings(
            bind_host=CONTAINER_BIND_HOST,
            advertise_host=CONTAINER_ADVERTISE_HOST,
            port=CONTAINER_PORT,
        )
        assert settings.url() == "http://host.docker.internal:8766/mcp"
        assert settings.with_port(9001).port == 9001


class TestResolveMcpListen:
    def test_local_defaults_unchanged(self) -> None:
        settings = resolve_mcp_listen()
        assert settings.bind_host == LOCAL_BIND_HOST
        assert settings.advertise_host == LOCAL_ADVERTISE_HOST
        assert settings.port == LOCAL_PORT
        assert settings.bind_host == "127.0.0.1"
        assert settings.advertise_host == "127.0.0.1"
        assert settings.port == 0

    def test_container_reachable_defaults(self) -> None:
        settings = resolve_mcp_listen(container_reachable=True)
        assert settings.bind_host == CONTAINER_BIND_HOST
        assert settings.advertise_host == CONTAINER_ADVERTISE_HOST
        assert settings.port == CONTAINER_PORT
        assert settings.url() == "http://host.docker.internal:8766/mcp"

    def test_explicit_values_win_over_container_defaults(self) -> None:
        settings = resolve_mcp_listen(
            container_reachable=True,
            bind_host="192.168.1.10",
            advertise_host="mcp.lan",
            port=9001,
        )
        assert (settings.bind_host, settings.advertise_host, settings.port) == (
            "192.168.1.10", "mcp.lan", 9001,
        )

    def test_explicit_port_zero_stays_ephemeral_in_container_mode(self) -> None:
        settings = resolve_mcp_listen(container_reachable=True, port=0)
        assert settings.port == 0
        assert settings.bind_host == "0.0.0.0"

    def test_wildcard_bind_does_not_advertise_zero(self) -> None:
        settings = resolve_mcp_listen(bind_host="0.0.0.0")
        assert settings.bind_host == "0.0.0.0"
        assert settings.advertise_host == "127.0.0.1"

    def test_custom_bind_is_advertised_when_not_wildcard(self) -> None:
        settings = resolve_mcp_listen(bind_host="192.168.1.5")
        assert settings.advertise_host == "192.168.1.5"

    def test_blank_host_treated_as_unset(self) -> None:
        settings = resolve_mcp_listen(container_reachable=True, bind_host="  ", advertise_host="")
        assert settings.bind_host == "0.0.0.0"
        assert settings.advertise_host == "host.docker.internal"
