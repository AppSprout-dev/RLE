"""Tests for RLEConfig API-key bridging."""

from __future__ import annotations

import os

import pytest

from rle.config import RLEConfig, bridge_anthropic_key, bridge_openrouter_key


class TestBridgeAnthropicKey:
    def test_exports_key_to_process_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sentinel")
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        config = RLEConfig(anthropic_api_key="sk-ant-test")
        bridge_anthropic_key(config)
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test"

    def test_does_not_override_existing_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        config = RLEConfig(anthropic_api_key="from-dotenv")
        bridge_anthropic_key(config)
        assert os.environ["ANTHROPIC_API_KEY"] == "from-env"

    def test_noop_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sentinel")
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        config = RLEConfig(anthropic_api_key=None)
        bridge_anthropic_key(config)
        assert "ANTHROPIC_API_KEY" not in os.environ


class TestProviderRegistry:
    def test_claude_code_provider_registered(self) -> None:
        from rle.providers.claude_code import ClaudeCodeProvider

        config = RLEConfig(provider="claude-code", model="claude-fable-5")
        provider = config.get_provider()
        assert isinstance(provider, ClaudeCodeProvider)
        assert provider.model == "claude-fable-5"


class TestBridgeOpenRouterKey:
    def test_exports_key_to_process_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sentinel")
        monkeypatch.delenv("OPENAI_API_KEY")
        config = RLEConfig(openrouter_api_key="sk-or-test")
        bridge_openrouter_key(config)
        assert os.environ["OPENAI_API_KEY"] == "sk-or-test"

    def test_does_not_override_existing_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "from-env")
        config = RLEConfig(openrouter_api_key="from-dotenv")
        bridge_openrouter_key(config)
        assert os.environ["OPENAI_API_KEY"] == "from-env"
