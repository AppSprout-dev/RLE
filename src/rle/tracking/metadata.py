"""Collect run metadata — git, platform, versions, replay-grade hashes."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

# Versioning of the composite scoring function. Bump when DEFAULT_WEIGHTS,
# metric implementations, or composite math change in a way that makes scores
# from older runs not directly comparable. The leaderboard re-scores artifacts
# at the current version on render; mismatches are surfaced, not silently
# elided.
# 1.1 (issue #25): threat_response now tracks actual draft responses
# (first_draft_tick wired, was permanently 0.0 once any threat registered)
# and null incident placeholders (enemy_count=0, threat_level=0.0) no longer
# count as threats.
# 1.2 (issue #51, "Phase C"): coordination + communication_efficiency removed
# (both were ~1.0 by construction and Felix-specific); plan_coherence added
# (contradictory executed writes per tick, harness-agnostic); efficiency and
# plan_coherence return a neutral 0.5 for ticks with no writes so an unmanaged
# baseline no longer banks free process points; weights redistributed.
SCORING_VERSION = "1.2"

# Conventional install path for the RIMAPI Workshop mod we deploy our fork DLL
# over. Best-effort — if Steam lives elsewhere set the RIMAPI_DLL_PATH env var.
_RIMAPI_DLL_DEFAULT_PATH = Path(
    "C:/Steam/steamapps/workshop/content/294100/3593423732/1.6/Assemblies/RIMAPI.dll",
)


def collect_metadata(random_seed: int | None = None) -> dict[str, object]:
    """Gather reproducibility metadata for a benchmark run.

    The random_seed argument is the seed the caller passed to ``random.seed``
    (or None if no seed was set). It controls only RLE-side stochasticity
    (json_repair fallbacks, resolver tiebreaks); RimWorld's own RNG is
    unaffected — that lives inside the game and is not reproducible from here.
    """
    dll_path = _rimapi_dll_path()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scoring_version": SCORING_VERSION,
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "git_dirty": _git("status", "--porcelain") != "",
        "rle_version": _version("rimworld-learning-environment"),
        "felix_sdk_version": _version("felix-agent-sdk"),
        "platform": sys.platform,
        "python_version": platform.python_version(),
        "docker_mode": False,
        "random_seed": random_seed,
        "rimapi_dll_path": str(dll_path) if dll_path else None,
        "rimapi_dll_sha256": file_sha256(dll_path) if dll_path else None,
        "rimapi_fork_commit": _rimapi_fork_commit(),
    }


def file_sha256(path: Path | None) -> str | None:
    """Hex SHA-256 of a file's contents, or None if missing/unreadable."""
    if path is None or not path.is_file():
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _rimapi_dll_path() -> Path | None:
    """Resolve the deployed RIMAPI DLL path (env override → Workshop default)."""
    override = os.environ.get("RIMAPI_DLL_PATH")
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    return (
        _RIMAPI_DLL_DEFAULT_PATH if _RIMAPI_DLL_DEFAULT_PATH.is_file() else None
    )


def _rimapi_fork_commit() -> str:
    """HEAD short SHA of the local RIMAPI fork checkout, if findable.

    Honors $RIMAPI_FORK_PATH; otherwise checks the conventional sibling repo
    location (../RIMAPI relative to this RLE checkout). Empty string when the
    fork isn't reachable from the runtime environment.
    """
    override = os.environ.get("RIMAPI_FORK_PATH")
    candidates = [Path(override)] if override else []
    candidates.append(Path(__file__).resolve().parents[3] / "RIMAPI")
    for fork_path in candidates:
        if (fork_path / ".git").exists():
            try:
                return subprocess.check_output(
                    ["git", "-C", str(fork_path), "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL, text=True,
                ).strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                return ""
    return ""


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
