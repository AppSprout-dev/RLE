"""Tests for replay-grade run metadata collection."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from rle.tracking import metadata as metadata_mod
from rle.tracking.metadata import (
    _RIMAPI_DLL_RELATIVE,
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


def _write_compiled_dll(fork_root: Path, payload: bytes) -> Path:
    dll = fork_root / _RIMAPI_DLL_RELATIVE
    dll.parent.mkdir(parents=True, exist_ok=True)
    dll.write_bytes(payload)
    return dll


def _init_git_repo(path: Path, marker: str = "ok") -> str:
    path.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "rle-test",
        "GIT_AUTHOR_EMAIL": "rle-test@example.com",
        "GIT_COMMITTER_NAME": "rle-test",
        "GIT_COMMITTER_EMAIL": "rle-test@example.com",
    }
    git_ident = [
        "-c",
        "user.name=rle-test",
        "-c",
        "user.email=rle-test@example.com",
        "-c",
        "commit.gpgsign=false",
    ]
    subprocess.run(
        ["git", *git_ident, "init", "-b", "main"],
        cwd=path,
        check=True,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    marker_file = path / "marker.txt"
    marker_file.write_text(f"{marker}\n", encoding="utf-8")
    subprocess.run(
        ["git", *git_ident, "add", "marker.txt"],
        cwd=path,
        check=True,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", *git_ident, "commit", "-m", "init"],
        cwd=path,
        check=True,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
        text=True,
    ).strip()


@pytest.fixture
def isolated_rimapi_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No inherited pin env; workshop fallback and checkout root are temp-local."""
    monkeypatch.delenv("RIMAPI_DLL_PATH", raising=False)
    monkeypatch.delenv("RIMAPI_FORK_PATH", raising=False)
    workshop = tmp_path / "workshop" / "RIMAPI.dll"
    monkeypatch.setattr(metadata_mod, "_RIMAPI_DLL_WORKSHOP_FALLBACK", workshop)
    monkeypatch.setattr(metadata_mod, "_rle_checkout_root", lambda: tmp_path / "Projects" / "RLE")
    return tmp_path


def test_dll_probe_order_env_then_fork_then_sibling_then_workshop(
    isolated_rimapi_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = isolated_rimapi_env
    env_dll = tmp_path / "explicit" / "RIMAPI.dll"
    env_dll.parent.mkdir(parents=True)
    env_dll.write_bytes(b"env-dll")
    fork_root = tmp_path / "fork-env"
    fork_dll = _write_compiled_dll(fork_root, b"fork-dll")
    sibling_root = tmp_path / "Projects" / "RIMAPI"
    sibling_dll = _write_compiled_dll(sibling_root, b"sibling-dll")
    workshop = tmp_path / "workshop" / "RIMAPI.dll"
    workshop.parent.mkdir(parents=True)
    workshop.write_bytes(b"workshop-dll")

    monkeypatch.setenv("RIMAPI_DLL_PATH", str(env_dll))
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(fork_root))
    assert metadata_mod._rimapi_dll_path() == env_dll

    monkeypatch.delenv("RIMAPI_DLL_PATH")
    assert metadata_mod._rimapi_dll_path() == fork_dll

    monkeypatch.delenv("RIMAPI_FORK_PATH")
    assert metadata_mod._rimapi_dll_path() == sibling_dll

    sibling_dll.unlink()
    assert metadata_mod._rimapi_dll_path() == workshop


def test_dll_probe_prefers_compiled_sibling_over_workshop(
    isolated_rimapi_env: Path,
) -> None:
    tmp_path = isolated_rimapi_env
    sibling_dll = _write_compiled_dll(tmp_path / "Projects" / "RIMAPI", b"compiled")
    workshop = tmp_path / "workshop" / "RIMAPI.dll"
    workshop.parent.mkdir(parents=True)
    workshop.write_bytes(b"flash-drift")

    assert metadata_mod._rimapi_dll_path() == sibling_dll


def test_dll_probe_falls_through_when_env_path_missing(
    isolated_rimapi_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = isolated_rimapi_env
    fork_dll = _write_compiled_dll(tmp_path / "fork-env", b"fork")
    monkeypatch.setenv("RIMAPI_DLL_PATH", str(tmp_path / "missing.dll"))
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(tmp_path / "fork-env"))
    assert metadata_mod._rimapi_dll_path() == fork_dll


def test_collect_metadata_records_compiled_dll_path_and_hash(
    isolated_rimapi_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = isolated_rimapi_env
    dll = _write_compiled_dll(tmp_path / "compiled", b"compiled-bytes")
    monkeypatch.setenv("RIMAPI_DLL_PATH", str(dll))
    md = collect_metadata()
    assert md["rimapi_dll_path"] == str(dll)
    assert md["rimapi_dll_sha256"] == file_sha256(dll)


def test_collect_metadata_records_fork_commit_from_env(
    isolated_rimapi_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = isolated_rimapi_env
    fork = tmp_path / "compiled"
    commit = _init_git_repo(fork)
    dll = _write_compiled_dll(fork, b"compiled-bytes")
    monkeypatch.setenv("RIMAPI_DLL_PATH", str(dll))
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(fork))
    md = collect_metadata()
    assert md["rimapi_dll_path"] == str(dll)
    assert md["rimapi_dll_sha256"] == file_sha256(dll)
    assert md["rimapi_fork_commit"] == commit


def test_fork_commit_honors_env_over_sibling(
    isolated_rimapi_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = isolated_rimapi_env
    env_commit = _init_git_repo(tmp_path / "fork-env", marker="env-fork")
    sibling_commit = _init_git_repo(tmp_path / "Projects" / "RIMAPI", marker="sibling-fork")
    assert env_commit != sibling_commit
    monkeypatch.setenv("RIMAPI_FORK_PATH", str(tmp_path / "fork-env"))
    assert metadata_mod._rimapi_fork_commit() == env_commit


def test_fork_commit_falls_back_to_git_toplevel_sibling(
    isolated_rimapi_env: Path,
) -> None:
    tmp_path = isolated_rimapi_env
    sibling_commit = _init_git_repo(tmp_path / "Projects" / "RIMAPI")
    assert metadata_mod._rimapi_fork_commit() == sibling_commit


def test_fork_commit_empty_when_missing(isolated_rimapi_env: Path) -> None:
    assert metadata_mod._rimapi_fork_commit() == ""


def test_checkout_root_from_source_file_skips_site_packages(tmp_path: Path) -> None:
    packaged = (
        tmp_path
        / ".venv"
        / "lib"
        / "python3.14"
        / "site-packages"
        / "rle"
        / "tracking"
        / "metadata.py"
    )
    assert metadata_mod._checkout_root_from_source_file(packaged) is None


def test_checkout_root_from_source_file_uses_editable_tree(tmp_path: Path) -> None:
    tracking = tmp_path / "RLE" / "src" / "rle" / "tracking"
    tracking.mkdir(parents=True)
    source = tracking / "metadata.py"
    source.write_text("# test\n", encoding="utf-8")
    assert metadata_mod._checkout_root_from_source_file(source) == tmp_path / "RLE"
