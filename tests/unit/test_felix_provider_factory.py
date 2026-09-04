"""Felix provider/helix construction (moved off RLEConfig)."""

from __future__ import annotations

import pytest

from rle.harness.felix.provider_factory import build_helix, build_provider
from rle.harness.felix.providers.claude_code import ClaudeCodeProvider


class TestProviderRegistry:
    def test_claude_code_provider_registered(self) -> None:
        provider = build_provider("claude-code", "claude-fable-5")
        assert isinstance(provider, ClaudeCodeProvider)
        assert provider.model == "claude-fable-5"

    def test_unknown_provider_lists_choices(self) -> None:
        with pytest.raises(ValueError, match="anthropic"):
            build_provider("nope", "x")


class TestHelixPresets:
    def test_default(self) -> None:
        assert build_helix("default") is not None

    def test_unknown_preset(self) -> None:
        with pytest.raises(ValueError, match="research_heavy"):
            build_helix("spiral")
