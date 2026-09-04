"""Tests for replay-grade run metadata collection."""

from __future__ import annotations

import hashlib
from pathlib import Path

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
