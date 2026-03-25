"""Collect run metadata — git, platform, versions."""

from __future__ import annotations

import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version


def collect_metadata() -> dict[str, object]:
    """Gather reproducibility metadata for a benchmark run."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "git_dirty": _git("status", "--porcelain") != "",
        "rle_version": _version("rimworld-learning-environment"),
        "felix_sdk_version": _version("felix-agent-sdk"),
        "platform": sys.platform,
        "python_version": platform.python_version(),
    }


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _version(package: str) -> str:
    try:
        return version(package)
    except Exception:
        return "unknown"
