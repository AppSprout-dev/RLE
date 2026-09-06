"""RLE configuration via environment variables and defaults."""

from __future__ import annotations

import os
from typing import Any

from pydantic_settings import BaseSettings


class RLEConfig(BaseSettings):
    """Top-level configuration for the RimWorld Learning Environment.

    Deliberately framework-free: provider/model/harness are strings, and the
    harness that gets built from them (see ``rle.harness``) decides what they
    mean. Felix-only knobs (helix preset, no-think, parallelism) live in
    ``FelixOptions`` and arrive via ``harness_options``.
    """

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    rimapi_url: str = "http://localhost:8765"
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5"
    provider_base_url: str | None = None
    openrouter_api_key: str | None = None
    anthropic_api_key: str | None = None
    tick_interval: float = 1.0
    harness: str = "felix"
    """Which harness decides the colony's actions. Resolved through the
    ``rle.harnesses`` entry-point registry (``--harness list``)."""
    harness_options: dict[str, Any] = {}
    """Harness-specific options validated against the plugin's schema
    (``RLE_HARNESS_OPTIONS`` as JSON, or ``--harness-opt key=value``)."""
    tick_timeout_s: float | None = None
    """Loop-level cap on a whole harness step. ``None`` = no cap (the Felix
    harness applies its own per-agent ``role_timeout_s``)."""
    role_timeout_s: float = 60.0
    """Max wall-clock seconds for a single Felix agent's deliberation. Hung LLM
    calls beyond this fire a deliberation_timeout ERROR event and the agent
    contributes no actions for the tick. Kept on RLEConfig for the legacy
    ``RLEGameLoop(agents=...)`` path; ``--harness-opt role_timeout_s=`` is the
    modern spelling."""
    max_agents: int = 7
    log_level: str = "INFO"
    docker_image: str = "rle-headless:latest"
    docker_port: int = 8765
    """Published RIMAPI port for ``--docker`` (headless RimWorld in a container).
    Unrelated to the MCP HTTP server; do not reuse 8765 for MCP."""
    mcp_container_reachable: bool = False
    """Bind MCP on ``0.0.0.0`` and advertise ``http://host.docker.internal:<port>/mcp``
    so a Docker coding-agent container can reach a host-side RLE process.
    Does **not** change ``--docker`` / RIMAPI (8765).
    Env: ``MCP_CONTAINER_REACHABLE``. CLI harnesses also accept
    ``--harness-opt mcp_container_reachable=true``."""
    mcp_bind_host: str | None = None
    """Interface the MCP HTTP server listens on. Unset: ``127.0.0.1`` locally,
    ``0.0.0.0`` when ``mcp_container_reachable``. Env: ``MCP_BIND_HOST``."""
    mcp_advertise_host: str | None = None
    """Hostname put in the MCP URL handed to the agent. Unset: ``127.0.0.1``
    locally, ``host.docker.internal`` when container-reachable.
    Env: ``MCP_ADVERTISE_HOST``."""
    mcp_port: int | None = None
    """MCP HTTP port. Unset: ephemeral locally, ``8766`` when container-reachable
    (never 8765). ``0`` forces ephemeral. Env: ``MCP_PORT``."""
    hf_token: str | None = None
    """Fine-grained HuggingFace write token (HF_TOKEN in .env) for dataset pushes."""
    hf_dataset_repo: str = "AppSprout/rle-benchmarks"
    """Target HF dataset repo (HF_DATASET_REPO in .env to override)."""

def bridge_openrouter_key(config: RLEConfig) -> None:
    """If OPENROUTER_API_KEY is set but OPENAI_API_KEY isn't, bridge them."""
    if config.openrouter_api_key and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = config.openrouter_api_key


def bridge_anthropic_key(config: RLEConfig) -> None:
    """Export ANTHROPIC_API_KEY from .env so the felix provider can read it.

    pydantic-settings loads .env into the config object but not into
    os.environ, which is where AnthropicProvider looks for the key.
    """
    if config.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = config.anthropic_api_key
