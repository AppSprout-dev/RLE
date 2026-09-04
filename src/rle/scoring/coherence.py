"""Contradiction detection over a tick's executed writes (``plan_coherence``).

A harness's job is to hand the game a coherent set of writes each tick.
Whether that coherence comes from a conflict resolver (multi-agent), a single
model's judgement, or a coding agent calling tools one at a time is the
harness's business — this module only looks at what actually reached RIMAPI,
so every harness is scored on the same footing (issue #51).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from rle.agents.actions import ActionOutcome, resolve_endpoint

Rect = tuple[int, int, int, int]

_ZONE_ENDPOINTS = frozenset({"growing_zone", "stockpile_zone"})


def _int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _rect(params: dict[str, Any]) -> Rect | None:
    """Mirror the executor's rectangle defaults (x2/z2 default to +5)."""
    x1 = _int(params.get("x1", params.get("x")))
    z1 = _int(params.get("z1", params.get("z")))
    if x1 is None or z1 is None:
        return None
    x2 = _int(params.get("x2", x1 + 5))
    z2 = _int(params.get("z2", z1 + 5))
    if x2 is None or z2 is None:
        return None
    return (min(x1, x2), min(z1, z2), max(x1, x2), max(z1, z2))


def _rects_overlap(a: Rect, b: Rect) -> bool:
    ax1, az1, ax2, az2 = a
    bx1, bz1, bx2, bz2 = b
    return not (ax2 < bx1 or ax1 > bx2 or az2 < bz1 or az1 > bz2)


def _all_conflicting(groups: Iterable[Sequence[int]], flagged: set[int]) -> None:
    for group in groups:
        if len(group) > 1:
            flagged.update(group)


def count_contradictions(outcomes: Sequence[ActionOutcome]) -> tuple[int, int]:
    """Return ``(contradictory, executed)`` for one tick's outcomes.

    Only successful writes count — a failed write never reached the game, so
    it cannot contradict anything (it is already penalised by ``efficiency``).
    A write is contradictory when, within the same tick, another executed
    write targets the same thing with an incompatible intent:

    * ``draft`` on the same pawn with different ``is_drafted`` values
    * ``move`` and ``job_assign`` on the same pawn
    * ``work_priority`` on the same pawn setting the same work type to
      different priorities
    * ``growing_zone`` / ``stockpile_zone`` rectangles that overlap
    * ``blueprint`` twice on the same cell
    * more than one distinct ``research_target`` project
    """
    executed = [(i, o) for i, o in enumerate(outcomes) if o.success]
    if not executed:
        return 0, 0

    flagged: set[int] = set()

    draft_by_pawn: dict[str, dict[bool, list[int]]] = {}
    move_or_job_by_pawn: dict[str, dict[str, list[int]]] = {}
    work_by_pawn_type: dict[tuple[str, str], dict[int, list[int]]] = {}
    zones: list[tuple[int, Rect]] = []
    blueprint_by_cell: dict[tuple[int, int], list[int]] = {}
    research_by_project: dict[str, list[int]] = {}

    for idx, o in executed:
        endpoint = resolve_endpoint(o.action_type)
        pawn = o.target_colonist_id or ""
        params = o.parameters
        if endpoint == "draft":
            state = bool(params.get("is_drafted", True))
            draft_by_pawn.setdefault(pawn, {}).setdefault(state, []).append(idx)
        elif endpoint in ("move", "job_assign"):
            move_or_job_by_pawn.setdefault(pawn, {}).setdefault(endpoint, []).append(idx)
        elif endpoint == "work_priority":
            for work, pri in _work_priorities(params).items():
                work_by_pawn_type.setdefault((pawn, work), {}).setdefault(pri, []).append(idx)
        elif endpoint in _ZONE_ENDPOINTS:
            rect = _rect(params)
            if rect is not None:
                zones.append((idx, rect))
        elif endpoint == "blueprint":
            try:
                cell = (int(params["x"]), int(params["z"]))
            except (KeyError, TypeError, ValueError):
                continue
            blueprint_by_cell.setdefault(cell, []).append(idx)
        elif endpoint == "research_target":
            project = str(params.get("project", params.get("name", "")))
            research_by_project.setdefault(project, []).append(idx)

    for by_state in draft_by_pawn.values():
        if len(by_state) > 1:
            for idxs in by_state.values():
                flagged.update(idxs)
    for by_kind in move_or_job_by_pawn.values():
        if len(by_kind) > 1:
            for idxs in by_kind.values():
                flagged.update(idxs)
    for by_pri in work_by_pawn_type.values():
        if len(by_pri) > 1:
            for idxs in by_pri.values():
                flagged.update(idxs)
    for i, (idx_a, rect_a) in enumerate(zones):
        for idx_b, rect_b in zones[i + 1:]:
            if _rects_overlap(rect_a, rect_b):
                flagged.add(idx_a)
                flagged.add(idx_b)
    _all_conflicting(blueprint_by_cell.values(), flagged)
    if len(research_by_project) > 1:
        for idxs in research_by_project.values():
            flagged.update(idxs)

    return len(flagged), len(executed)


def _work_priorities(params: dict[str, Any]) -> dict[str, int]:
    """Mirror of the executor's accepted shapes, tolerant of garbage."""
    nested = params.get("work_priorities")
    if isinstance(nested, dict):
        return {str(w): int(p) for w, p in nested.items() if isinstance(p, int)}
    if "work_type" in params:
        pri = params.get("priority", 1)
        return {str(params["work_type"]): int(pri)} if isinstance(pri, int) else {}
    return {
        str(w): p for w, p in params.items()
        if isinstance(p, int) and not isinstance(p, bool)
    }
