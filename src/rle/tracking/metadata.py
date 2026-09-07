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

# Last-resort OSS fallback only. AppSprout source of truth is the compiled
# checkout (AppSprout-dev/RIMAPI, branch rle-testing), not Steam Workshop.
# Prefer $RIMAPI_DLL_PATH / $RIMAPI_FORK_PATH, then a sibling ../RIMAPI build.
_RIMAPI_DLL_WORKSHOP_FALLBACK = Path(
    "C:/Steam/steamapps/workshop/content/294100/3593423732/1.6/Assemblies/RIMAPI.dll",
)
_RIMAPI_ASSEMBLY_RELATIVE = (
    Path("1.6") / "Assemblies" / "RIMAPI.dll",
    Path("1.5") / "Assemblies" / "RIMAPI.dll",
)


def collect_metadata(
    random_seed: int | None = None,
    harness_describe: dict[str, str] | None = None,
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


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def _git_show_toplevel(start: Path) -> Path | None:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return Path(out) if out else None


def _rle_git_toplevel() -> Path | None:
    """RLE checkout root via git, not ``Path(__file__).parents[3]``.

    ``__file__`` is under site-packages when RLE is installed into a venv, so
    walking parents of this module does not find the repo. Prefer cwd, then
    this file's directory (source checkouts), and ask git for the toplevel.
    """
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        toplevel = _git_show_toplevel(start)
        if toplevel is not None:
            return toplevel
    return None


def _rimapi_sibling_checkout() -> Path | None:
    """``../RIMAPI`` next to the RLE git toplevel, when that directory exists."""
    toplevel = _rle_git_toplevel()
    if toplevel is None:
        return None
    sibling = toplevel.parent / "RIMAPI"
    return sibling if sibling.is_dir() else None


def _dlls_under_fork(fork_root: Path) -> tuple[Path, ...]:
    return tuple(fork_root / relative for relative in _RIMAPI_ASSEMBLY_RELATIVE)


def _first_existing_file(*candidates: Path) -> Path | None:
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def _rimapi_dll_path() -> Path | None:
    """Resolve the RIMAPI DLL to hash for run metadata.

    Probe order (first existing file wins):

    1. ``$RIMAPI_DLL_PATH`` — explicit pin; if set but missing, return None
       (do not silently fall through to Workshop)
    2. ``$RIMAPI_FORK_PATH/{1.6,1.5}/Assemblies/RIMAPI.dll``
    3. Sibling checkout ``{RLE git toplevel}/../RIMAPI/{1.6,1.5}/Assemblies/RIMAPI.dll``
    4. Steam Workshop path — last-resort OSS fallback, not AppSprout SoT
    """
    override = _env_path("RIMAPI_DLL_PATH")
    if override is not None:
        return override.resolve() if override.is_file() else None

    candidates: list[Path] = []
    fork_override = _env_path("RIMAPI_FORK_PATH")
    if fork_override is not None:
        candidates.extend(_dlls_under_fork(fork_override))

    sibling = _rimapi_sibling_checkout()
    if sibling is not None:
        candidates.extend(_dlls_under_fork(sibling))

    candidates.append(_RIMAPI_DLL_WORKSHOP_FALLBACK)
    return _first_existing_file(*candidates)


def _rimapi_fork_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = _env_path("RIMAPI_FORK_PATH")
    if override is not None:
        candidates.append(override)
    sibling = _rimapi_sibling_checkout()
    if sibling is not None and sibling not in candidates:
        candidates.append(sibling)
    return candidates


def _rimapi_fork_commit() -> str:
    """HEAD short SHA of the local RIMAPI fork checkout, if findable.

    Honors ``$RIMAPI_FORK_PATH``. Otherwise resolves a sibling ``../RIMAPI``
    from the RLE git toplevel (``git rev-parse --show-toplevel``), not from
    ``Path(__file__).parents[3]``. Empty string when the fork isn't reachable.
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
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
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
