"""Options for the OpenRouter model-only baseline."""

from __future__ import annotations

from pydantic import Field

from rle.harness.cli_base import HeadlessCliOptions
from rle.harness.raw_openrouter.auth import DEFAULT_REFERER, DEFAULT_TITLE


class RawOpenRouterOptions(HeadlessCliOptions):
    """OpenRouter OpenAI-compat + inherited MCP / turn knobs.

    ``turn_timeout_s`` defaults to 180 (``HeadlessCliOptions``). Comparisons
    against slower coding-agent harnesses should pass ``turn_timeout_s=300``.
    ``base_url`` defaults to OpenRouter; set it only for a proxy.
    """

    api_key: str | None = Field(
        default=None,
        description=(
            "OpenRouter API key. Defaults to OPENROUTER_API_KEY / "
            "RLEConfig.openrouter_api_key (OPENAI_API_KEY last)."
        ),
    )
    base_url: str | None = Field(
        default=None,
        description=(
            "OpenAI-compat base URL. Default https://openrouter.ai/api/v1. "
            "RLE --base-url is honored only when it already points at OpenRouter."
        ),
    )
    max_rounds: int = Field(
        default=16,
        ge=1,
        le=64,
        description="Max model↔tool rounds in one tick (safety cap).",
    )
    http_referer: str = Field(
        default=DEFAULT_REFERER,
        description="OpenRouter HTTP-Referer attribution header.",
    )
    x_title: str = Field(
        default=DEFAULT_TITLE,
        description="OpenRouter X-Title attribution header.",
    )
