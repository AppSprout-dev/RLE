"""Tests for the cinematic CameraDirector (issue #34)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from rle.orchestration.camera_director import CameraDirector
from rle.rimapi.schemas import ColonistData, GameState
from rle.rimapi.sse_client import RimAPIEvent


def _event(event_type: str, **data: object) -> RimAPIEvent:
    return RimAPIEvent(event_type, dict(data), 1700000000.0)


def _colonist(
    cid: str, mood: float, pos: tuple[int, int], injuries: list[str] | None = None,
) -> ColonistData:
    return ColonistData(
        colonist_id=cid, name=cid, health=1.0, mood=mood, skills={},
        traits=[], current_job=None, is_drafted=False, needs={},
        injuries=injuries or [], position=pos,
    )


def _state(sample_game_state: GameState, **overrides: object) -> GameState:
    return sample_game_state.model_copy(update=overrides)


class TestTargetExtraction:
    def test_extract_pawn_id_variants(self) -> None:
        assert CameraDirector._extract_pawn_id({"pawn_id": 184}) == "184"
        assert CameraDirector._extract_pawn_id({"colonist_id": "col_2"}) == "col_2"
        assert CameraDirector._extract_pawn_id({"pawn_id": 0}) is None
        assert CameraDirector._extract_pawn_id({}) is None

    def test_extract_cell_variants(self) -> None:
        assert CameraDirector._extract_cell({"position": {"x": 10, "z": 20}}) == (10, 20)
        assert CameraDirector._extract_cell({"position": {"x": 10, "y": 20}}) == (10, 20)
        assert CameraDirector._extract_cell({"position": [5, 6]}) == (5, 6)
        assert CameraDirector._extract_cell({"x": 7, "z": 8}) == (7, 8)
        assert CameraDirector._extract_cell({"foo": "bar"}) is None


class TestDecisions:
    async def test_event_with_pawn_id_jumps_to_pawn(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        director = CameraDirector(client)
        cue = await director.direct(
            1, sample_game_state, [_event("pawn_downed", pawn_id=184)], 1.0,
        )
        assert cue is not None
        assert cue.target_type == "pawn"
        assert cue.pawn_id == "184"
        assert cue.reason == "pawn_downed"
        client.jump_camera_to_pawn.assert_awaited_once_with("184")

    async def test_event_with_cell_moves_camera(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        director = CameraDirector(client)
        cue = await director.direct(
            1, sample_game_state, [_event("pawn_killed", position={"x": 30, "z": 40})], 1.0,
        )
        assert cue is not None
        assert cue.target_type == "cell"
        assert (cue.x, cue.z) == (30, 40)
        client.move_camera.assert_awaited_once_with(30, 40)

    async def test_highest_priority_event_wins(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        director = CameraDirector(client)
        events = [
            _event("colonist_mental_break", pawn_id=5),
            _event("pawn_killed", pawn_id=9),
        ]
        cue = await director.direct(1, sample_game_state, events, 1.0)
        assert cue is not None
        assert cue.reason == "pawn_killed"
        assert cue.pawn_id == "9"

    async def test_threat_with_no_event_frames_colony(self, sample_game_state: GameState) -> None:
        # sample_game_state already carries a threat.
        client = AsyncMock()
        director = CameraDirector(client)
        cue = await director.direct(1, sample_game_state, [], 1.0)
        assert cue is not None
        assert cue.target_type == "colony"
        assert cue.reason == "threat_active"
        client.move_camera.assert_awaited_once()

    async def test_idle_drift_on_interval(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        director = CameraDirector(client, drift_interval=4)
        state = _state(sample_game_state, threats=[])
        cue = await director.direct(4, state, [], 1.0)  # tick % 4 == 0
        assert cue is not None
        assert cue.reason == "idle_drift"
        assert cue.target_type == "colony"

    async def test_idle_spotlights_most_distressed(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        director = CameraDirector(client, drift_interval=4)
        roster = [
            _colonist("happy", 0.9, (10, 10)),
            _colonist("sad", 0.1, (20, 20)),
        ]
        state = _state(sample_game_state, threats=[], colonists=roster)
        cue = await director.direct(1, state, [], 1.0)  # tick % 4 != 0
        assert cue is not None
        assert cue.reason == "idle_spotlight"
        assert cue.pawn_id == "sad"


class TestCueLog:
    async def test_cue_log_written(self, sample_game_state: GameState, tmp_path: Path) -> None:
        client = AsyncMock()
        director = CameraDirector(client, output_dir=tmp_path)
        await director.direct(1, sample_game_state, [_event("pawn_killed", pawn_id=3)], 99.5)
        log = tmp_path / "camera_cues.jsonl"
        assert log.exists()
        record = json.loads(log.read_text(encoding="utf-8").strip())
        assert record["pawn_id"] == "3"
        assert record["timestamp"] == 99.5
        assert len(director.cues) == 1

    async def test_camera_failure_is_swallowed(self, sample_game_state: GameState) -> None:
        client = AsyncMock()
        client.jump_camera_to_pawn.side_effect = RuntimeError("no endpoint")
        director = CameraDirector(client)
        cue = await director.direct(1, sample_game_state, [_event("pawn_downed", pawn_id=3)], 1.0)
        assert cue is None
        assert director.cues == []
