"""raw-grok model-baseline plugin, options, and prompt contract."""

from __future__ import annotations

from importlib.util import find_spec

import pytest

from rle.harness.brief import ScenarioBrief
from rle.harness.raw_grok.plugin import PLUGIN, RAW_GROK_DESCRIPTION
from rle.harness.registry import create_harness, get_plugin, harness_names, validate_options
from tests.unit.test_harness_registry import _ctx

mcp_available = find_spec("mcp") is not None
requires_mcp = pytest.mark.skipif(not mcp_available, reason="mcp extra not installed")


class TestRawGrokPlugin:
    def test_registers(self) -> None:
        assert "raw-grok" in harness_names()
        plugin = get_plugin("raw-grok")
        assert plugin.name == "raw-grok"
        assert plugin is PLUGIN
        assert "MODEL BASELINE" in plugin.description
        assert "MODEL BASELINE" in RAW_GROK_DESCRIPTION

    @requires_mcp
    def test_options_schema_defaults(self) -> None:
        plugin = get_plugin("raw-grok")
        opts = validate_options(plugin, {})
        assert opts.binary == "grok"  # type: ignore[attr-defined]
        assert opts.turn_timeout_s == 180.0  # type: ignore[attr-defined]
        assert opts.extra_instructions == ""  # type: ignore[attr-defined]
        assert opts.mcp_advertise_url is None  # type: ignore[attr-defined]
        assert opts.mcp_container_reachable is None  # type: ignore[attr-defined]

    @requires_mcp
    def test_options_accept_binary_timeout_and_advertise_url(self) -> None:
        plugin = get_plugin("raw-grok")
        opts = validate_options(plugin, {
            "binary": "/opt/grok",
            "turn_timeout_s": 300,
            "mcp_advertise_url": "http://host.docker.internal:8766/mcp",
            "mcp_container_reachable": True,
        })
        assert opts.binary == "/opt/grok"  # type: ignore[attr-defined]
        assert opts.turn_timeout_s == 300.0  # type: ignore[attr-defined]
        assert opts.mcp_advertise_url == "http://host.docker.internal:8766/mcp"  # type: ignore[attr-defined]
        assert opts.mcp_container_reachable is True  # type: ignore[attr-defined]

    @requires_mcp
    def test_prompt_is_turn_rules_only(self) -> None:
        from rle.harness.cli_base import TURN_RULES
        from rle.harness.raw_grok.harness import RawGrokHarness
        from rle.harness.raw_grok.options import RawGrokOptions

        harness = RawGrokHarness(RawGrokOptions())
        brief = ScenarioBrief(
            tick=1, day=0, macro_time=0.0,
            goals={}, state={"colony": {"tick": 1}},
            map_summary="SHELTER SITE (1,1)-(7,7)",
            recent_events=[], actions=[],
        )
        prompt = harness.render_prompt(brief)
        assert TURN_RULES in prompt
        assert "get_brief" in prompt
        assert "end_turn" in prompt
        assert harness.options.extra_instructions == ""
        # Model baseline: no namespaced-tool addendum, no extra instructions.
        assert "rle__get_brief" not in prompt
        assert "namespaced" not in prompt.lower()
        assert "the only mcp server" not in prompt.lower()

    @requires_mcp
    def test_smoke_builds_scripted_standin(self) -> None:
        harness = create_harness("raw-grok", _ctx(), smoke=True)
        assert harness.name == "raw-grok"

    @requires_mcp
    def test_mcp_toml_is_rle_stanza_only(self) -> None:
        from rle.harness.raw_grok.harness import project_mcp_toml

        text = project_mcp_toml("http://127.0.0.1:8766/mcp")
        assert "[mcp_servers.rle]" in text
        assert "http://127.0.0.1:8766/mcp" in text
        assert "compat" not in text
