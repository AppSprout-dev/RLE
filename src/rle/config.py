"""RLE configuration via environment variables and defaults."""

from __future__ import annotations

import os

from felix_agent_sdk.core import HelixConfig
from felix_agent_sdk.providers import (
    AnthropicProvider,
    BaseProvider,
    LocalProvider,
    OpenAIProvider,
)
from pydantic_settings import BaseSettings

_HELIX_PRESETS: dict[str, HelixConfig] = {
    "default": HelixConfig.default(),
    "research_heavy": HelixConfig.research_heavy(),
    "fast_convergence": HelixConfig.fast_convergence(),
}

_PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "local": LocalProvider,
}


class RLEConfig(BaseSettings):
    """Top-level configuration for the RimWorld Learning Environment."""

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    rimapi_url: str = "http://localhost:8765"
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5"
    provider_base_url: str | None = None
    openrouter_api_key: str | None = None
    tick_interval: float = 1.0
    helix_preset: str = "default"
    max_agents: int = 7
    log_level: str = "INFO"

    def get_helix_config(self) -> HelixConfig:
        """Return the HelixConfig preset matching ``helix_preset``."""
        try:
            return _HELIX_PRESETS[self.helix_preset]
        except KeyError:
            raise ValueError(
                f"Unknown helix preset {self.helix_preset!r}. "
                f"Choose from: {list(_HELIX_PRESETS)}"
            ) from None

    def get_provider(self) -> BaseProvider:
        """Construct an LLM provider from the current config."""
        cls = _PROVIDER_CLASSES.get(self.provider)
        if cls is None:
            raise ValueError(
                f"Unknown provider {self.provider!r}. "
                f"Choose from: {list(_PROVIDER_CLASSES)}"
            )
        kwargs: dict[str, str] = {"model": self.model}
        if self.provider_base_url:
            kwargs["base_url"] = self.provider_base_url
        return cls(**kwargs)


def bridge_openrouter_key(config: RLEConfig) -> None:
    """If OPENROUTER_API_KEY is set but OPENAI_API_KEY isn't, bridge them."""
    if config.openrouter_api_key and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = config.openrouter_api_key
