"""Resolve OpenRouter credentials without importing the MCP extra."""

from __future__ import annotations

import os

from rle.config import RLEConfig

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_REFERER = "https://github.com/AppSprout-dev/RLE"
DEFAULT_TITLE = "RLE raw-openrouter"


def resolve_api_key(
    explicit: str | None = None,
    config_key: str | None = None,
) -> str | None:
    """Prefer an explicit key, then config, then ``OPENROUTER_API_KEY``.

    ``OPENAI_API_KEY`` is a last-resort fallback (Felix / README often store
    the OpenRouter key there). Empty strings are ignored.
    """
    for candidate in (
        explicit,
        config_key,
        os.environ.get("OPENROUTER_API_KEY"),
        os.environ.get("OPENAI_API_KEY"),
    ):
        if candidate and candidate.strip():
            return candidate.strip()
    return None


def resolve_base_url(
    explicit: str | None = None,
    config_url: str | None = None,
) -> str:
    """OpenRouter URL unless the caller overrode it.

    ``config.provider_base_url`` is used only when it already points at
    OpenRouter — a typical ``.env`` LM Studio URL must not steal this harness.
    """
    if explicit and explicit.strip():
        return explicit.strip().rstrip("/")
    cfg = (config_url or "").strip().rstrip("/")
    if cfg and "openrouter.ai" in cfg:
        return cfg
    return DEFAULT_BASE_URL


def config_openrouter_key() -> str | None:
    """Best-effort ``RLEConfig.openrouter_api_key`` (loads ``.env``)."""
    try:
        return RLEConfig().openrouter_api_key
    except Exception:
        return None
