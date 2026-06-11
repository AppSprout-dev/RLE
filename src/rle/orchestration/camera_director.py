"""Cinematic camera director — drives the RimWorld camera to the action.

Issue #34: during a run the OBS/timelapse camera sat wherever it was left
(zoomed-out map center), so the events agents narrate — a raid, a colonist
bleeding out, a mental break — happened as a few pixels at the edge of frame.

The director watches the same SSE event stream the agents see and eases the
camera to whatever is most story-worthy this tick: a downed/killed pawn, a
mental break, an incoming raid. Between events it drifts over the colony and
periodically zooms in on a colonist. Every decision is appended to a
camera-cue log (timestamp -> target) so the footage index can map video cuts
to camera moves.

This is opt-in (capture runs only) and never raises into the game loop — a
missing camera endpoint or a malformed event degrades to a logged miss.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from rle.rimapi.client import RimAPIClient
    from rle.rimapi.schemas import GameState
    from rle.rimapi.sse_client import RimAPIEvent

logger = logging.getLogger(__name__)

# Zoom levels (RimWorld CameraDriver: smaller = closer).
_ZOOM_CLOSEUP = 13
_ZOOM_COLONY = 40

# SSE event types worth cutting to, highest priority first. A raid has no
# dedicated SSE type (it arrives as a letter / shows up in state.threats), so
# threats are handled separately from this table.
_EVENT_PRIORITY: tuple[str, ...] = (
    "pawn_killed",
    "colonist_died",
    "pawn_downed",
    "colonist_mental_break",
    "pawn_entered_map",
)

# Candidate keys SSE payloads use for a pawn id / a map cell. RIMAPI's event
# shapes vary by Harmony hook, so we probe several rather than assume one.
_PAWN_ID_KEYS: tuple[str, ...] = ("pawn_id", "colonist_id", "thing_id", "victim_id")
_POS_KEYS: tuple[str, ...] = ("position", "pos", "location", "cell")


class CameraCue(BaseModel):
    """One camera decision, logged for the footage index."""

    model_config = ConfigDict(frozen=True)

    timestamp: float
    tick: int
    target_type: str  # "pawn" | "cell" | "colony"
    reason: str
    pawn_id: str | None = None
    x: int | None = None
    z: int | None = None
    zoom: int | None = None


class CameraDirector:
    """Decides where the camera should look each tick and moves it there."""

    def __init__(
        self,
        client: RimAPIClient,
        *,
        output_dir: Path | None = None,
        drift_interval: int = 4,
    ) -> None:
        self._client = client
        self._cue_log_path = (
            output_dir / "camera_cues.jsonl" if output_dir is not None else None
        )
        self._drift_interval = max(1, drift_interval)
        self.cues: list[CameraCue] = []

    # -- target selection (pure, testable) ----------------------------------

    @staticmethod
    def _extract_pawn_id(data: dict[str, Any]) -> str | None:
        for key in _PAWN_ID_KEYS:
            value = data.get(key)
            if value is not None and str(value) not in ("", "0"):
                return str(value)
        return None

    @staticmethod
    def _extract_cell(data: dict[str, Any]) -> tuple[int, int] | None:
        # Nested {"position": {"x": .., "z"/"y": ..}} or {"position": [x, z]}.
        for key in _POS_KEYS:
            pos = data.get(key)
            if isinstance(pos, dict):
                x = pos.get("x")
                z = pos.get("z", pos.get("y"))
                if isinstance(x, int) and isinstance(z, int):
                    return (x, z)
            elif isinstance(pos, (list, tuple)) and len(pos) >= 2:
                try:
                    return (int(pos[0]), int(pos[1]))
                except (TypeError, ValueError):
                    continue
        # Flat x/z on the event itself.
        x_flat = data.get("x")
        z_flat = data.get("z", data.get("y"))
        if isinstance(x_flat, int) and isinstance(z_flat, int):
            return (x_flat, z_flat)
        return None

    def _select_event(
        self, events: list[RimAPIEvent]
    ) -> tuple[RimAPIEvent, int] | None:
        """Pick the highest-priority event we can actually point the camera at."""
        best: tuple[RimAPIEvent, int] | None = None
        for event in events:
            if event.event_type not in _EVENT_PRIORITY:
                continue
            rank = _EVENT_PRIORITY.index(event.event_type)
            if self._extract_pawn_id(event.data) is None and (
                self._extract_cell(event.data) is None
            ):
                continue
            if best is None or rank < best[1]:
                best = (event, rank)
        return best

    # -- main entry point ---------------------------------------------------

    async def direct(
        self,
        tick: int,
        state: GameState,
        events: list[RimAPIEvent],
        now: float,
    ) -> CameraCue | None:
        """Move the camera to this tick's focus and record the cue.

        ``now`` is passed in (rather than read here) so the caller controls the
        clock and the cue log stays deterministic in tests.
        """
        cue = self._decide(tick, state, events, now)
        if cue is None:
            return None
        try:
            await self._apply(cue)
        except Exception:  # never break the tick on a camera hiccup
            logger.debug("Camera move failed for cue %s", cue.reason, exc_info=True)
            return None
        self._record(cue)
        return cue

    def _decide(
        self,
        tick: int,
        state: GameState,
        events: list[RimAPIEvent],
        now: float,
    ) -> CameraCue | None:
        # 1. Story event takes the cut.
        selected = self._select_event(events)
        if selected is not None:
            event, _ = selected
            pawn_id = self._extract_pawn_id(event.data)
            if pawn_id is not None:
                return CameraCue(
                    timestamp=now, tick=tick, target_type="pawn",
                    reason=event.event_type, pawn_id=pawn_id, zoom=_ZOOM_CLOSEUP,
                )
            cell = self._extract_cell(event.data)
            if cell is not None:
                return CameraCue(
                    timestamp=now, tick=tick, target_type="cell",
                    reason=event.event_type, x=cell[0], z=cell[1], zoom=_ZOOM_CLOSEUP,
                )

        # 2. Active raid with no SSE coords — frame the colony so the approach
        #    is in shot.
        if state.threats:
            cx, cz = self._colony_center(state)
            return CameraCue(
                timestamp=now, tick=tick, target_type="colony",
                reason="threat_active", x=cx, z=cz, zoom=_ZOOM_COLONY,
            )

        # 3. Idle: periodically pull back to the colony, otherwise zoom a pawn.
        if tick % self._drift_interval == 0 or not state.colonists:
            cx, cz = self._colony_center(state)
            return CameraCue(
                timestamp=now, tick=tick, target_type="colony",
                reason="idle_drift", x=cx, z=cz, zoom=_ZOOM_COLONY,
            )
        colonist = self._spotlight_colonist(state, tick)
        return CameraCue(
            timestamp=now, tick=tick, target_type="pawn",
            reason="idle_spotlight", pawn_id=colonist.colonist_id, zoom=_ZOOM_CLOSEUP,
        )

    @staticmethod
    def _colony_center(state: GameState) -> tuple[int, int]:
        terrain = state.map.terrain
        if terrain is not None:
            return terrain.colony_center
        if state.colonists:
            xs = [c.position[0] for c in state.colonists]
            zs = [c.position[1] for c in state.colonists]
            return (sum(xs) // len(xs), sum(zs) // len(zs))
        w, h = state.map.size
        return (w // 2, h // 2)

    @staticmethod
    def _spotlight_colonist(state: GameState, tick: int) -> Any:
        """Pick a story-worthy colonist: the most distressed (lowest mood),
        else cycle through the roster so the camera doesn't fixate."""
        distressed = [c for c in state.colonists if c.mood < 0.35 or c.injuries]
        if distressed:
            return min(distressed, key=lambda c: c.mood)
        return state.colonists[tick % len(state.colonists)]

    async def _apply(self, cue: CameraCue) -> None:
        if cue.zoom is not None:
            await self._client.set_camera_zoom(cue.zoom)
        if cue.target_type == "pawn" and cue.pawn_id is not None:
            await self._client.jump_camera_to_pawn(cue.pawn_id)
        elif cue.x is not None and cue.z is not None:
            await self._client.move_camera(cue.x, cue.z)

    def _record(self, cue: CameraCue) -> None:
        self.cues.append(cue)
        if self._cue_log_path is None:
            return
        try:
            self._cue_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._cue_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(cue.model_dump()) + "\n")
        except OSError:
            logger.debug("Could not append camera cue to %s", self._cue_log_path)
