"""raw-openrouter model-baseline plugin, options, auth, and OpenAI-compat parsing."""

from __future__ import annotations

import json
from importlib.util import find_spec
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from rle.config import RLEConfig
from rle.harness.brief import ScenarioBrief
from rle.harness.protocol import HarnessStepError
from rle.harness.raw_openrouter.auth import (
    DEFAULT_BASE_URL,
    config_openrouter_key,
    resolve_api_key,
    resolve_base_url,
)
from rle.harness.raw_openrouter.openai_compat import (
    assistant_message,
    complete_chat,
    extract_cost_usd,
    extract_generation_id,
    extract_usage,
    mcp_tool_to_openai,
    openai_tools_from_mcp,
    parse_tool_call,
)
from rle.harness.raw_openrouter.plugin import PLUGIN, RAW_OPENROUTER_DESCRIPTION
from rle.harness.registry import create_harness, get_plugin, harness_names, validate_options
from tests.unit.test_harness_registry import _ctx

mcp_available = find_spec("mcp") is not None
requires_mcp = pytest.mark.skipif(not mcp_available, reason="mcp extra not installed")


class TestRawOpenRouterPlugin:
    def test_registers(self) -> None:
        assert "raw-openrouter" in harness_names()
        plugin = get_plugin("raw-openrouter")
        assert plugin.name == "raw-openrouter"
        assert plugin is PLUGIN
        assert "MODEL BASELINE" in plugin.description
        assert "OpenRouter" in plugin.description
        assert "not XAI" in plugin.description.lower() or "Not XAI" in plugin.description
        assert "not a product or agent harness" in plugin.description.lower()
        assert "MODEL BASELINE" in RAW_OPENROUTER_DESCRIPTION
        assert "XAI" not in plugin.name

    def test_describe_is_model_baseline_not_xai(self) -> None:
        info = PLUGIN.describe()
        assert info["harness"] == "raw-openrouter"
        assert info["kind"] == "model-baseline"
        assert info["provider"] == "openrouter"
        assert "grok" not in info.values()
        assert "xai" not in {v.lower() for v in info.values()}

    @requires_mcp
    def test_options_schema_defaults(self) -> None:
        plugin = get_plugin("raw-openrouter")
        opts = validate_options(plugin, {})
        assert opts.api_key is None  # type: ignore[attr-defined]
        assert opts.base_url is None  # type: ignore[attr-defined]
        assert opts.max_rounds == 16  # type: ignore[attr-defined]
        assert opts.turn_timeout_s == 180.0  # type: ignore[attr-defined]
        assert opts.extra_instructions == ""  # type: ignore[attr-defined]
        assert opts.model is None  # type: ignore[attr-defined]

    @requires_mcp
    def test_options_accept_model_base_url_and_rounds(self) -> None:
        plugin = get_plugin("raw-openrouter")
        opts = validate_options(plugin, {
            "model": "google/gemini-3.8-flash",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-test",
            "max_rounds": 8,
            "turn_timeout_s": 300,
        })
        assert opts.model == "google/gemini-3.8-flash"  # type: ignore[attr-defined]
        assert opts.base_url == "https://openrouter.ai/api/v1"  # type: ignore[attr-defined]
        assert opts.api_key == "sk-or-test"  # type: ignore[attr-defined]
        assert opts.max_rounds == 8  # type: ignore[attr-defined]
        assert opts.turn_timeout_s == 300.0  # type: ignore[attr-defined]

    @requires_mcp
    def test_prompt_is_turn_rules_only(self) -> None:
        from rle.harness.cli_base import TURN_RULES
        from rle.harness.raw_openrouter.harness import RawOpenRouterHarness
        from rle.harness.raw_openrouter.options import RawOpenRouterOptions

        harness = RawOpenRouterHarness(RawOpenRouterOptions())
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
        assert "rle__get_brief" not in prompt
        assert "namespaced" not in prompt.lower()

    @requires_mcp
    def test_smoke_builds_scripted_standin(self) -> None:
        harness = create_harness("raw-openrouter", _ctx(), smoke=True)
        assert harness.name == "raw-openrouter"

    def test_available_missing_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch(
            "rle.harness.raw_openrouter.plugin.config_openrouter_key",
            return_value=None,
        ):
            avail = PLUGIN.available()
        if find_spec("mcp") is None:
            assert not avail.ok
            assert "mcp extra" in avail.reason
        else:
            assert not avail.ok
            assert "OPENROUTER_API_KEY" in avail.reason

    def test_available_ok_with_openrouter_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        if find_spec("mcp") is None:
            pytest.skip("mcp extra not installed")
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert PLUGIN.available().ok


class TestAuthResolution:
    def test_prefers_explicit_then_config_then_openrouter_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "from-or")
        monkeypatch.setenv("OPENAI_API_KEY", "from-openai")
        assert resolve_api_key("explicit", "from-config") == "explicit"
        assert resolve_api_key(None, "from-config") == "from-config"
        assert resolve_api_key(None, None) == "from-or"

    def test_falls_back_to_openai_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-or-via-openai")
        assert resolve_api_key() == "sk-or-via-openai"

    def test_empty_strings_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert resolve_api_key("  ", "") is None

    def test_base_url_defaults_to_openrouter(self) -> None:
        assert resolve_base_url() == DEFAULT_BASE_URL
        assert resolve_base_url(None, "http://localhost:1234/v1") == DEFAULT_BASE_URL

    def test_base_url_honors_openrouter_config_and_explicit(self) -> None:
        assert resolve_base_url(None, "https://openrouter.ai/api/v1/") == (
            "https://openrouter.ai/api/v1"
        )
        assert resolve_base_url("https://proxy.example/v1") == "https://proxy.example/v1"

    def test_config_openrouter_key_reads_settings(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "from-settings")
        assert config_openrouter_key() == "from-settings"


class TestOpenAICompatParsing:
    def test_extract_generation_id_and_reasoning_tokens(self) -> None:
        payload = {
            "id": "gen-abc123",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "completion_tokens_details": {"reasoning_tokens": 7},
                "cost": 0.0015,
            },
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }
        assert extract_generation_id(payload) == "gen-abc123"
        assert extract_usage(payload) == (10, 4, 7)
        assert extract_cost_usd(payload) == pytest.approx(0.0015)
        assert assistant_message(payload)["content"] == "ok"

    def test_extract_usage_missing_is_zero(self) -> None:
        assert extract_generation_id({}) is None
        assert extract_usage({}) == (0, 0, 0)
        assert extract_cost_usd({}) is None

    def test_mcp_tool_to_openai(self) -> None:
        tool = SimpleNamespace(
            name="get_brief",
            description="Scenario brief",
            inputSchema={"type": "object", "properties": {}},
        )
        converted = mcp_tool_to_openai(tool)
        assert converted["type"] == "function"
        assert converted["function"]["name"] == "get_brief"
        assert converted["function"]["parameters"]["type"] == "object"
        listed = openai_tools_from_mcp(SimpleNamespace(tools=[tool]))
        assert len(listed) == 1

    def test_parse_tool_call_json_arguments(self) -> None:
        name, args, tc_id = parse_tool_call({
            "id": "call-1",
            "function": {
                "name": "end_turn",
                "arguments": '{"summary": "done"}',
            },
        })
        assert name == "end_turn"
        assert args == {"summary": "done"}
        assert tc_id == "call-1"

    async def test_complete_chat_posts_usage_include(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = request.content
            return httpx.Response(
                200,
                json={
                    "id": "gen-1",
                    "choices": [{"message": {"role": "assistant", "content": "hi"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0},
                },
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://openrouter.ai/api/v1",
        ) as client:
            data = await complete_chat(
                client,
                model="google/gemini-3.8-flash",
                messages=[{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "get_brief"}}],
            )
        assert data["id"] == "gen-1"
        sent = json.loads(captured["body"])
        assert sent["model"] == "google/gemini-3.8-flash"
        assert sent["usage"] == {"include": True}
        assert sent["tool_choice"] == "auto"
        assert captured["url"].endswith("/chat/completions")

    async def test_complete_chat_http_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://openrouter.ai/api/v1",
        ) as client:
            with pytest.raises(HarnessStepError, match="401"):
                await complete_chat(
                    client, model="x", messages=[{"role": "user", "content": "hi"}],
                )


@requires_mcp
class TestSendTurnLoop:
    async def test_tool_round_then_end_turn_records_generation_ids(self) -> None:
        from rle.harness.raw_openrouter.harness import RawOpenRouterHarness
        from rle.harness.raw_openrouter.options import RawOpenRouterOptions

        payloads = [
            {
                "id": "gen-1",
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "cost": 0.01},
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "c1",
                            "function": {"name": "get_brief", "arguments": "{}"},
                        }],
                    },
                }],
            },
            {
                "id": "gen-2",
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 3,
                    "completion_tokens_details": {"reasoning_tokens": 4},
                    "cost": 0.02,
                },
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "c2",
                            "function": {
                                "name": "end_turn",
                                "arguments": '{"summary": "ok"}',
                            },
                        }],
                    },
                }],
            },
        ]

        async def fake_complete(*_a: Any, **_k: Any) -> dict[str, Any]:
            return payloads.pop(0)

        calls: list[tuple[str, dict[str, Any]]] = []

        class _FakeMcp:
            async def list_tools(self) -> list[Any]:
                return [{
                    "name": "get_brief",
                    "description": "brief",
                    "inputSchema": {"type": "object", "properties": {}},
                }]

            async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
                calls.append((name, args))
                return SimpleNamespace(content=[SimpleNamespace(text=f"{name}-ok")])

            async def __aenter__(self) -> _FakeMcp:
                return self

            async def __aexit__(self, *_exc: object) -> None:
                return None

        harness = RawOpenRouterHarness(RawOpenRouterOptions(model="google/gemini-3.8-flash"))
        harness._mcp_url = "http://127.0.0.1:9/mcp"
        harness._http = httpx.AsyncClient()
        try:
            with (
                patch(
                    "rle.harness.raw_openrouter.harness.Client",
                    lambda *_a, **_k: _FakeMcp(),
                ),
                patch(
                    "rle.harness.raw_openrouter.harness.complete_chat",
                    fake_complete,
                ),
            ):
                turn = await harness.send_turn("RLE turn")
        finally:
            await harness._http.aclose()

        assert calls == [("get_brief", {}), ("end_turn", {"summary": "ok"})]
        assert turn.prompt_tokens == 13
        assert turn.completion_tokens == 5
        assert turn.reasoning_tokens == 4
        assert turn.extras["generation_ids"] == ["gen-1", "gen-2"]
        assert turn.extras["cost_usd"] == pytest.approx(0.03)
        assert turn.extras["cost_source"] == "billed"
        assert turn.extras["provider"] == "openrouter"


@requires_mcp
class TestCreateRequiresKey:
    def test_create_without_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        ctx = _ctx()
        ctx.config = RLEConfig(tick_interval=0.0, openrouter_api_key=None)
        with (
            patch(
                "rle.harness.raw_openrouter.plugin.resolve_api_key",
                return_value=None,
            ),
            patch(
                "rle.harness.raw_openrouter.plugin.config_openrouter_key",
                return_value=None,
            ),
            pytest.raises(Exception, match="OPENROUTER_API_KEY"),
        ):
            create_harness("raw-openrouter", ctx)

    def test_create_with_key_builds_harness(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
        harness = create_harness(
            "raw-openrouter",
            _ctx(),
            {"api_key": "sk-or-test", "model": "google/gemini-3.8-flash"},
        )
        assert harness.name == "raw-openrouter"
