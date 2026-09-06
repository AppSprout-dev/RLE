"""PATH / version probes for the stock grok executable (no MCP imports)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def resolve_binary(binary: str) -> str | None:
    candidate = Path(binary).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    return shutil.which(binary)


def binary_version(binary: str) -> str:
    path = resolve_binary(binary)
    if path is None:
        return "not installed"
    try:
        out = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if text else "unknown"
