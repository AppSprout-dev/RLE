"""Tests for replay-grade run metadata collection."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from rle.tracking import metadata as metadata_mod
from rle.tracking.metadata import (
    SCORING_VERSION,
    collect_metadata,
    file_sha256,
)


def test_scoring_version_pins_a_string() -> None:
    """SCORING_VERSION is a non-empty string. Bumping it is a deliberate act
    that requires this test (and the dataset card) to be updated."""
    assert isinstance(SCORING_VERSION, str)
    assert SCORING_VERSION
    assert SCORING_VERSION == "1.2"


def test_file_sha256_returns_none_for_missing_path() -> None:
    assert file_sha256(None) is None
    assert file_sha256(Path("c:/does/not/exist/file.bin")) is None


def test_file_sha256_matches_hashlib(tmp_path: Path) -> None:
    payload = b"the quick brown fox jumps over the lazy dog\n" * 100
    target = tmp_path / "blob.bin"
    target.write_bytes(payload)

    expected = hashlib.sha256(payload).hexdigest()
    assert file_sha256(target) == expected


def test_collect_metadata_includes_scoring_version_and_seed() -> None:
    md = collect_metadata(random_seed=42)
    assert md["scoring_version"] == SCORING_VERSION
    assert md["random_seed"] == 42
    # Keys that callers consume — verify presence (values may be empty / None
    # if the environment lacks git / the Workshop install / a RIMAPI fork).
    for key in (
        "timestamp",
        "git_commit",
        "git_branch",
        "git_dirty",
        "rle_version",
        "harness_versions",
        "platform",
        "python_version",
        "rimapi_dll_path",
        "rimapi_dll_sha256",
        "rimapi_fork_commit",
    ):
        assert key in md, f"missing metadata field: {key}"


def test_collect_metadata_records_harness_describe() -> None:
    md = collect_metadata(harness_describe={"harness": "x", "tool": "1.2"})
    assert md["harness_versions"] == {"harness": "x", "tool": "1.2"}
    assert collect_metadata()["harness_versions"] == {}


def test_collect_metadata_default_seed_is_none() -> None:
    md = collect_metadata()
    assert md["random_seed"] is None


def test_collect_metadata_dll_path_and_hash_pair_consistently() -> None:
    """If the DLL path is recorded, the hash must be a 64-char hex digest.
    If the path is None, the hash must also be None (no half-states)."""
    md = collect_metadata()
    path = md["rimapi_dll_path"]
    digest = md["rimapi_dll_sha256"]
    if path is None:
        assert digest is None
    else:
        assert isinstance(digest, str)
        assert len(digest) == 64
        int(digest, 16)  # raises if not hex


def _write_dll(path: Path, payload: bytes = b"compiled-rimapi") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _init_git_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "RLE Test"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    (path / "README").write_text("fork\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=path,
        text=True,
    ).strip()


@pytest.fixture
def isolated_pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Clear pin env and disable real-checkout / Workshop probes."""
    monkeypatch.delenv("RIMAPI_DLL_PATH", raising=False)
    monkeypatch.delenv("RIMAPI_FORK_PATH", raising=False)
    monkeypatch.setattr(metadata_mod, "_rle_git_toplevel", lambda: None)
    monkeypatch.setattr(
        metadata_mod,
        "_RIMAPI_DLL_WORKSHOP_FALLBACK",
        tmp_path / "workshop-missing" / "RIMAPI.dll",
    )
    return tmp_path


def test_dll_path_honors_explicit_env_over_compiled_and_workshop(
    isolated_pin: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pinned = _write_dll(isolated_pin / "pinned" / "RIMAPI.dll", b"explicit")
    fork = isolated_pin / "fork"
    _write_dll(fork / "1.6" / "Assemblies" / "RIMAPI.dll", b"fork-build")
    workshop = _write_dll(isolated_pin / "workshop" / "RIMAPI.dll", b"workshop")
    monkeypatch.setenv("RIMAPI_DLL_PATH", str(pinned))
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(fork))
    monkeypatch.setattr(metadata_mod, "_RIMAPI_DLL_WORKSHOP_FALLBACK", workshop)

    found = metadata_mod._rimapi_dll_path()
    assert found == pinned.resolve()


def test_dll_path_explicit_env_missing_does_not_fall_through(
    isolated_pin: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fork = isolated_pin / "fork"
    _write_dll(fork / "1.6" / "Assemblies" / "RIMAPI.dll", b"fork-build")
    workshop = _write_dll(isolated_pin / "workshop" / "RIMAPI.dll", b"workshop")
    monkeypatch.setenv("RIMAPI_DLL_PATH", str(isolated_pin / "absent.dll"))
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(fork))
    monkeypatch.setattr(metadata_mod, "_RIMAPI_DLL_WORKSHOP_FALLBACK", workshop)

    assert metadata_mod._rimapi_dll_path() is None


def test_dll_path_prefers_fork_env_assemblies_over_sibling_and_workshop(
    isolated_pin: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fork = isolated_pin / "compiled-fork"
    fork_dll = _write_dll(fork / "1.6" / "Assemblies" / "RIMAPI.dll", b"fork16")
    sibling = isolated_pin / "RIMAPI"
    _write_dll(sibling / "1.6" / "Assemblies" / "RIMAPI.dll", b"sibling")
    workshop = _write_dll(isolated_pin / "workshop" / "RIMAPI.dll", b"workshop")
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(fork))
    monkeypatch.setattr(metadata_mod, "_rle_git_toplevel", lambda: isolated_pin / "RLE")
    monkeypatch.setattr(metadata_mod, "_RIMAPI_DLL_WORKSHOP_FALLBACK", workshop)
    (isolated_pin / "RLE").mkdir()

    assert metadata_mod._rimapi_dll_path() == fork_dll.resolve()


def test_dll_path_fork_env_falls_back_to_1_5_assemblies(
    isolated_pin: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fork = isolated_pin / "compiled-fork"
    dll = _write_dll(fork / "1.5" / "Assemblies" / "RIMAPI.dll", b"fork15")
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(fork))

    assert metadata_mod._rimapi_dll_path() == dll.resolve()


def test_dll_path_prefers_sibling_compiled_over_workshop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rle = tmp_path / "RLE"
    fork = tmp_path / "RIMAPI"
    sibling_dll = _write_dll(fork / "1.6" / "Assemblies" / "RIMAPI.dll", b"sibling")
    workshop = _write_dll(tmp_path / "workshop" / "RIMAPI.dll", b"workshop")
    _init_git_repo(rle)
    monkeypatch.delenv("RIMAPI_DLL_PATH", raising=False)
    monkeypatch.delenv("RIMAPI_FORK_PATH", raising=False)
    monkeypatch.chdir(rle)
    monkeypatch.setattr(metadata_mod, "_RIMAPI_DLL_WORKSHOP_FALLBACK", workshop)

    assert metadata_mod._rimapi_dll_path() == sibling_dll.resolve()


def test_dll_path_workshop_is_last_resort_only(
    isolated_pin: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workshop = _write_dll(isolated_pin / "workshop" / "RIMAPI.dll", b"workshop")
    monkeypatch.setattr(metadata_mod, "_RIMAPI_DLL_WORKSHOP_FALLBACK", workshop)

    assert metadata_mod._rimapi_dll_path() == workshop.resolve()


def test_dll_path_returns_none_when_nothing_findable(isolated_pin: Path) -> None:
    assert metadata_mod._rimapi_dll_path() is None


def test_fork_commit_honors_rimapi_fork_path(
    isolated_pin: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fork = isolated_pin / "compiled-fork"
    sha = _init_git_repo(fork)
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(fork))

    assert metadata_mod._rimapi_fork_commit() == sha


def test_fork_commit_resolves_sibling_via_rle_git_toplevel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rle = tmp_path / "RLE"
    fork = tmp_path / "RIMAPI"
    _init_git_repo(rle)
    sha = _init_git_repo(fork)
    monkeypatch.delenv("RIMAPI_DLL_PATH", raising=False)
    monkeypatch.delenv("RIMAPI_FORK_PATH", raising=False)
    monkeypatch.chdir(rle)

    assert metadata_mod._rimapi_fork_commit() == sha


def test_fork_commit_empty_when_fork_unreachable(isolated_pin: Path) -> None:
    assert metadata_mod._rimapi_fork_commit() == ""


def test_collect_metadata_records_compiled_dll_pin(
    isolated_pin: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"appsprout-compiled"
    dll = _write_dll(isolated_pin / "1.6" / "Assemblies" / "RIMAPI.dll", payload)
    fork_sha = _init_git_repo(isolated_pin)
    monkeypatch.setenv("RIMAPI_DLL_PATH", str(dll))
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(isolated_pin))

    md = collect_metadata()
    assert md["rimapi_dll_path"] == str(dll.resolve())
    assert md["rimapi_dll_sha256"] == hashlib.sha256(payload).hexdigest()
    assert md["rimapi_fork_commit"] == fork_sha
