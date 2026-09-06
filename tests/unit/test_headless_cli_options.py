"""HeadlessCliOptions merge of MCP listen settings onto RLEConfig."""

from __future__ import annotations

import pytest

from rle.config import RLEConfig

cli_base = pytest.importorskip("rle.harness.cli_base")


class TestOptionsMergeOntoConfig:
    def test_default_options_follow_config(self) -> None:
        opts = cli_base.HeadlessCliOptions()
        config = RLEConfig(mcp_container_reachable=True, mcp_port=9002)
        listen = opts.mcp_listen(config)
        assert listen.bind_host == "0.0.0.0"
        assert listen.advertise_host == "host.docker.internal"
        assert listen.port == 9002

    def test_harness_opt_overrides_config(self) -> None:
        opts = cli_base.HeadlessCliOptions(
            mcp_container_reachable=False,
            mcp_advertise_host="agent.example",
            mcp_port=0,
        )
        config = RLEConfig(mcp_container_reachable=True, mcp_advertise_host="from-config")
        listen = opts.mcp_listen(config)
        assert listen.bind_host == "127.0.0.1"
        assert listen.advertise_host == "agent.example"
        assert listen.port == 0

    def test_false_harness_opt_disables_config_flag(self) -> None:
        opts = cli_base.HeadlessCliOptions(mcp_container_reachable=False)
        config = RLEConfig(mcp_container_reachable=True)
        listen = opts.mcp_listen(config)
        assert listen.bind_host == "127.0.0.1"
        assert listen.port == 0

    def test_advertise_url_is_an_option(self) -> None:
        opts = cli_base.HeadlessCliOptions(
            mcp_advertise_url="http://host.docker.internal:8766/mcp",
            mcp_container_reachable=True,
        )
        assert opts.mcp_advertise_url == "http://host.docker.internal:8766/mcp"
        listen = opts.mcp_listen(RLEConfig())
        assert listen.bind_host == "0.0.0.0"
        assert listen.advertise_host == "host.docker.internal"
