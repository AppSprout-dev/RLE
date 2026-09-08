"""Native AppData save staging against the scenario pin."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from rle.orchestration import save_loader as save_loader_mod
from rle.orchestration.save_loader import load_save_and_settle
from rle.scenarios import loader as loader_mod
from rle.scenarios.loader import (
    LiveSavePinError,
    LiveSaveStatus,
    default_rimworld_saves_dir,
    ensure_live_save,
    live_save_path,
)
from rle.tracking.metadata import file_sha256


def _write_save(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_ensure_live_save_copies_on_mismatch(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical" / "rle_crashlanded_v1.rws"
    pin = _write_save(canonical, b"canonical-bench-and-smithing")
    live_dir = tmp_path / "AppData" / "Saves"
    live = live_dir / "rle_crashlanded_v1.rws"
    _write_save(live, b"april-stale-appdata")

    status = ensure_live_save(
        "rle_crashlanded_v1",
        pin,
        live_dir=live_dir,
        canonical_path=canonical,
    )

    assert status.copied is True
    assert status.live_save_sha256 == pin
    assert status.pinned_sha256 == pin
    assert live.read_bytes() == canonical.read_bytes()
    assert file_sha256(live) == pin


def test_ensure_live_save_noop_when_live_already_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"already-pinned"
    pin = hashlib.sha256(payload).hexdigest()
    canonical = tmp_path / "canonical" / "rle_crashlanded_v1.rws"
    _write_save(canonical, payload)
    live_dir = tmp_path / "Saves"
    live = live_dir / "rle_crashlanded_v1.rws"
    _write_save(live, payload)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("matching live save must not copy")

    monkeypatch.setattr(loader_mod.shutil, "copy2", _boom)

    status = ensure_live_save(
        "rle_crashlanded_v1",
        pin,
        live_dir=live_dir,
        canonical_path=canonical,
    )
    assert status.copied is False
    assert status.live_save_sha256 == pin
    assert live.read_bytes() == payload


def test_ensure_live_save_copies_when_live_missing(tmp_path: Path) -> None:
    canonical = tmp_path / "docker" / "saves" / "rle_crashlanded_v1.rws"
    pin = _write_save(canonical, b"new-seed")
    live_dir = tmp_path / "Saves"

    status = ensure_live_save(
        "rle_crashlanded_v1",
        pin,
        live_dir=live_dir,
        canonical_path=canonical,
    )
    assert status.copied is True
    assert (live_dir / "rle_crashlanded_v1.rws").read_bytes() == b"new-seed"
    assert status.live_save_sha256 == pin


def test_ensure_live_save_fails_closed_when_canonical_missing(tmp_path: Path) -> None:
    live_dir = tmp_path / "Saves"
    missing = tmp_path / "docker" / "saves" / "rle_crashlanded_v1.rws"
    with pytest.raises(LiveSavePinError, match="missing"):
        ensure_live_save(
            "rle_crashlanded_v1",
            "a" * 64,
            live_dir=live_dir,
            canonical_path=missing,
        )
    assert not (live_dir / "rle_crashlanded_v1.rws").exists()


def test_ensure_live_save_fails_closed_when_canonical_hash_wrong(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical.rws"
    _write_save(canonical, b"not-the-pin")
    live_dir = tmp_path / "Saves"
    with pytest.raises(LiveSavePinError, match="hashes to"):
        ensure_live_save(
            "rle_crashlanded_v1",
            "b" * 64,
            live_dir=live_dir,
            canonical_path=canonical,
        )


def test_ensure_live_save_fails_closed_when_post_copy_hash_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical.rws"
    pin = _write_save(canonical, b"good-canonical")
    live_dir = tmp_path / "Saves"

    def _corrupt_copy(src: object, dst: object) -> None:
        Path(str(dst)).write_bytes(b"corrupted-copy")

    monkeypatch.setattr(loader_mod.shutil, "copy2", _corrupt_copy)

    with pytest.raises(LiveSavePinError, match="Copied"):
        ensure_live_save(
            "rle_crashlanded_v1",
            pin,
            live_dir=live_dir,
            canonical_path=canonical,
        )


def test_ensure_live_save_fails_closed_when_copy_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical.rws"
    pin = _write_save(canonical, b"good-canonical")
    live_dir = tmp_path / "Saves"

    def _io_error(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(loader_mod.shutil, "copy2", _io_error)

    with pytest.raises(LiveSavePinError, match="Failed to copy"):
        ensure_live_save(
            "rle_crashlanded_v1",
            pin,
            live_dir=live_dir,
            canonical_path=canonical,
        )


def test_live_save_path_uses_live_dir(tmp_path: Path) -> None:
    dest = live_save_path("rle_first_winter_v1", live_dir=tmp_path)
    assert dest == tmp_path / "rle_first_winter_v1.rws"


def test_default_rimworld_saves_dir_honors_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RLE_RIMWORLD_SAVES", str(tmp_path / "custom"))
    assert default_rimworld_saves_dir() == tmp_path / "custom"


def test_default_rimworld_saves_dir_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RLE_RIMWORLD_SAVES", raising=False)
    monkeypatch.setattr(loader_mod.sys, "platform", "win32")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\keeper")
    assert default_rimworld_saves_dir() == (
        Path(r"C:\Users\keeper") / "AppData" / "LocalLow" / "Ludeon Studios"
        / "RimWorld by Ludeon Studios" / "Saves"
    )


class _FakeColonyClient:
    def __init__(self, order: list[str] | None = None) -> None:
        self.loads: list[str] = []
        self.order = order if order is not None else []

    async def load_game(self, save_name: str) -> None:
        self.order.append(f"load:{save_name}")
        self.loads.append(save_name)

    async def get_colony(self) -> SimpleNamespace:
        return SimpleNamespace(population=3)

    async def unforbid_all_items(self) -> int:
        return 4


async def test_load_save_and_settle_stages_before_game_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    pin = "c" * 64
    status = LiveSaveStatus(
        save_name="rle_crashlanded_v1",
        live_path=Path("/tmp/rle_crashlanded_v1.rws"),
        live_save_sha256=pin,
        copied=True,
        pinned_sha256=pin,
    )

    def fake_ensure(save_name: str, expected: str, **_kwargs: object) -> LiveSaveStatus:
        order.append(f"stage:{save_name}:{expected}")
        return status

    async def fake_wait(_url: str, timeout: float = 30.0) -> None:
        order.append("wait")

    monkeypatch.setattr(save_loader_mod, "ensure_live_save", fake_ensure)
    monkeypatch.setattr(save_loader_mod, "wait_for_rimapi", fake_wait)
    monkeypatch.setattr(save_loader_mod, "STABLE_POLLS_REQUIRED", 1)
    monkeypatch.setattr(save_loader_mod, "POLL_INTERVAL_S", 0.0)

    client = _FakeColonyClient(order)
    result = await load_save_and_settle(
        client,  # type: ignore[arg-type]
        "http://localhost:8765",
        "rle_crashlanded_v1",
        save_sha256=pin,
        stage_live=True,
    )
    assert order[0] == f"stage:rle_crashlanded_v1:{pin}"
    assert order[1] == "load:rle_crashlanded_v1"
    assert result.unforbid_count == 4
    assert result.live_save == status
    assert result.live_save.copied is True


async def test_load_save_and_settle_skips_staging_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> LiveSaveStatus:
        raise AssertionError("docker/smoke path must not stage AppData")

    async def fake_wait(_url: str, timeout: float = 30.0) -> None:
        return None

    monkeypatch.setattr(save_loader_mod, "ensure_live_save", _boom)
    monkeypatch.setattr(save_loader_mod, "wait_for_rimapi", fake_wait)
    monkeypatch.setattr(save_loader_mod, "STABLE_POLLS_REQUIRED", 1)
    monkeypatch.setattr(save_loader_mod, "POLL_INTERVAL_S", 0.0)

    client = _FakeColonyClient()
    result = await load_save_and_settle(
        client,  # type: ignore[arg-type]
        "http://localhost:8765",
        "rle_crashlanded_v1",
        save_sha256="d" * 64,
        stage_live=False,
        unforbid_items=False,
    )
    assert client.loads == ["rle_crashlanded_v1"]
    assert result.live_save is None
    assert result.unforbid_count == 0


async def test_load_save_and_settle_pin_error_before_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_ensure(*_args: object, **_kwargs: object) -> LiveSaveStatus:
        raise LiveSavePinError("canonical missing")

    client = _FakeColonyClient()
    monkeypatch.setattr(save_loader_mod, "ensure_live_save", fake_ensure)

    with pytest.raises(LiveSavePinError, match="canonical missing"):
        await load_save_and_settle(
            client,  # type: ignore[arg-type]
            "http://localhost:8765",
            "rle_crashlanded_v1",
            save_sha256="e" * 64,
            stage_live=True,
        )
    assert client.loads == []
