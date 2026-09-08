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

# Compiled fork layout relative to a RIMAPI checkout root.
_RIMAPI_DLL_RELATIVE = Path("1.6") / "Assemblies" / "RIMAPI.dll"

# Steam Workshop install we sometimes overlay. Last-resort fallback only —
# Workshop is not source of truth (Flash can drift the Workshop DLL).
_RIMAPI_DLL_WORKSHOP_FALLBACK = Path(
    "C:/Steam/steamapps/workshop/content/294100/3593423732/1.6/Assemblies/RIMAPI.dll",
)


def collect_metadata(
    random_seed: int | None = None,
    harness_describe: dict[str, str] | None = None,
    live_save_sha256: str | None = None,
    live_save_copied: bool | None = None,
) -> dict[str, object]:
    """Gather reproducibility metadata for a benchmark run.

    The random_seed argument is the seed the caller passed to ``random.seed``
    (or None if no seed was set). It controls only RLE-side stochasticity
    (json_repair fallbacks, resolver tiebreaks); RimWorld's own RNG is
    unaffected — that lives inside the game and is not reproducible from here.

    ``harness_describe`` is whatever the harness reports about itself
    (``BaseHarness.describe()``): SDK versions, agent roster, external tool
    versions. Recorded as ``harness_versions`` so a leaderboard row can be
    traced to the exact harness build, whichever framework it used.

    ``live_save_sha256`` / ``live_save_copied`` record whether the native
    AppData save was already at the scenario pin or had to be copied from
    ``docker/saves/`` before ``POST /game/load``.
    """
    dll_path = _rimapi_dll_path()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scoring_version": SCORING_VERSION,
        "git_commit": _git("rev-parse", "--short", "HEAD"),
        "git_branch": _git("branch", "--show-current"),
        "git_dirty": _git("status", "--porcelain") != "",
        "rle_version": _version("rimworld-learning-environment"),
        "harness_versions": dict(harness_describe or {}),
        "platform": sys.platform,
        "python_version": platform.python_version(),
        "docker_mode": False,
        "random_seed": random_seed,
        "rimapi_dll_path": str(dll_path) if dll_path else None,
        "rimapi_dll_sha256": file_sha256(dll_path) if dll_path else None,
        "rimapi_fork_commit": _rimapi_fork_commit(),
        "live_save_sha256": live_save_sha256,
        "live_save_copied": live_save_copied,
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


def _is_packaged_install(path: Path) -> bool:
    """True when *path* lives in a venv/site-packages install, not a checkout."""
    return "site-packages" in path.parts or ".venv" in path.parts


def _checkout_root_from_source_file(file_path: Path) -> Path | None:
    """RLE checkout root inferred from ``src/rle/tracking/metadata.py``.

    Returns None for packaged installs (site-packages / .venv): ``parents[3]``
    is not the RLE repo in those layouts.
    """
    if _is_packaged_install(file_path):
        return None
    try:
        candidate = file_path.resolve().parents[3]
    except IndexError:
        return None
    if (candidate / ".git").exists() or (candidate / "src" / "rle").is_dir():
        return candidate
    return None


def _rle_checkout_root() -> Path | None:
    """Git toplevel of the RLE checkout, if findable.

    Prefers ``git rev-parse --show-toplevel`` from the process cwd (works when
    RLE is imported from site-packages/.venv but launched from the checkout).
    Falls back to ``__file__`` only when that path still looks like a source
    tree — not a packaged install.
    """
    raw = _git("rev-parse", "--show-toplevel")
    if raw:
        return Path(raw)
    return _checkout_root_from_source_file(Path(__file__))


def _sibling_rimapi_root() -> Path | None:
    """``../RIMAPI`` next to the RLE checkout, or None if the checkout is unknown."""
    checkout = _rle_checkout_root()
    if checkout is None:
        return None
    return checkout.parent / "RIMAPI"


def _first_existing_file(candidates: list[Path]) -> Path | None:
    seen: set[str] = set()
    for candidate in candidates:
        key = os.fspath(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
    return None


def _rimapi_dll_candidates() -> list[Path]:
    """Deterministic DLL probe order. First existing file wins.

    1. ``$RIMAPI_DLL_PATH``
    2. ``$RIMAPI_FORK_PATH/1.6/Assemblies/RIMAPI.dll``
    3. sibling checkout ``../RIMAPI/1.6/Assemblies/RIMAPI.dll``
    4. Workshop path (optional last fallback; not source of truth)
    """
    candidates: list[Path] = []
    dll_override = os.environ.get("RIMAPI_DLL_PATH")
    if dll_override:
        candidates.append(Path(dll_override))
    fork_override = os.environ.get("RIMAPI_FORK_PATH")
    if fork_override:
        candidates.append(Path(fork_override) / _RIMAPI_DLL_RELATIVE)
    sibling = _sibling_rimapi_root()
    if sibling is not None:
        candidates.append(sibling / _RIMAPI_DLL_RELATIVE)
    candidates.append(_RIMAPI_DLL_WORKSHOP_FALLBACK)
    return candidates


def _rimapi_dll_path() -> Path | None:
    """Resolve the RIMAPI DLL, preferring a compiled fork over Workshop."""
    return _first_existing_file(_rimapi_dll_candidates())


def _rimapi_fork_candidates() -> list[Path]:
    """Fork checkout probe order. First path with a ``.git`` dir wins.

    1. ``$RIMAPI_FORK_PATH``
    2. sibling of the RLE git toplevel (``../RIMAPI``), not only ``__file__``
    """
    candidates: list[Path] = []
    override = os.environ.get("RIMAPI_FORK_PATH")
    if override:
        candidates.append(Path(override))
    sibling = _sibling_rimapi_root()
    if sibling is not None:
        candidates.append(sibling)
    return candidates


def _rimapi_fork_commit() -> str:
    """HEAD short SHA of the local RIMAPI fork checkout, if findable.

    Honors ``$RIMAPI_FORK_PATH`` and the sibling of the RLE git toplevel.
    Empty string when the fork isn't reachable from the runtime environment.
    """
    for fork_path in _rimapi_fork_candidates():
        if not (fork_path / ".git").exists():
            continue
        try:
            return subprocess.check_output(
                ["git", "-C", str(fork_path), "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
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
