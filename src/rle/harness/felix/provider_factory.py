"""Build Felix SDK providers and helix geometry from RLE's string config."""

from __future__ import annotations

from felix_agent_sdk.core import HelixConfig, HelixGeometry
from felix_agent_sdk.providers import (
    AnthropicProvider,
    BaseProvider,
    LocalProvider,
    OpenAIProvider,
)

from rle.providers.claude_code import ClaudeCodeProvider

HELIX_PRESETS: dict[str, HelixConfig] = {
    "default": HelixConfig.default(),
    "research_heavy": HelixConfig.research_heavy(),
    "fast_convergence": HelixConfig.fast_convergence(),
}

PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "local": LocalProvider,
    "claude-code": ClaudeCodeProvider,
}


def build_provider(provider: str, model: str, base_url: str | None = None) -> BaseProvider:
    """Construct a Felix provider from provider name + model (+ optional base URL)."""
    cls = PROVIDER_CLASSES.get(provider)
    if cls is None:
        raise ValueError(
            f"Unknown provider {provider!r}. Choose from: {list(PROVIDER_CLASSES)}"
        )
    kwargs: dict[str, str] = {"model": model}
    if base_url:
        kwargs["base_url"] = base_url
    return cls(**kwargs)  # type: ignore[arg-type]  # subclasses accept kwargs


def build_helix(preset: str = "default") -> HelixGeometry:
    try:
        return HELIX_PRESETS[preset].to_geometry()
    except KeyError:
        raise ValueError(
            f"Unknown helix preset {preset!r}. Choose from: {list(HELIX_PRESETS)}"
        ) from None
