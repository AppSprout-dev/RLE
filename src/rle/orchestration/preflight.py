"""Harness-agnostic preflight gates at action dispatch.

Keeper Crashlanded failures that are RLE-side contract bugs must not be
counted as model noise. These checks sit in ``ActionExecutor`` so every
harness benefits:

* growing-zone cells already covered → success-by-state
* work_priority payloads aligned with WorkTypeDef / ``/api/v1/work-list``
* research_target only when the project is available (prereqs / bench)
* tend requires a living doctor + patient pair
* stockpile_delete is quarantined when the endpoint is missing
"""

from __future__ import annotations

from typing import Any

from rle.rimapi.api_catalog import QUARANTINED_WRITES
from rle.rimapi.schemas import ColonistData, GameState, ResearchData

__all__ = [
    "ALREADY_COVERED_MARKERS",
    "VANILLA_WORK_TYPES",
    "WORK_PRIORITY_RESERVED_KEYS",
    "extract_work_priorities",
    "growing_zone_already_covers",
    "is_already_covered_error",
    "is_quarantined_write",
    "living_colonists",
    "normalize_work_priorities",
    "research_target_status",
    "resolve_tend_pair",
]

# Vanilla WorkTypeDef.defName values. Live ``GET /api/v1/work-list`` wins
# when the client can fetch it; this is the offline / mock fallback.
VANILLA_WORK_TYPES: frozenset[str] = frozenset({
    "Firefighter",
    "Patient",
    "Doctor",
    "PatientBedRest",
    "BasicWorker",
    "Warden",
    "Handling",
    "Cooking",
    "Hunting",
    "Construction",
    "Growing",
    "Mining",
    "PlantCutting",
    "Smithing",
    "Tailoring",
    "Art",
    "Crafting",
    "Hauling",
    "Cleaning",
    "Research",
    "Childcare",
})

# Field names models copy from the old catalog / RIMAPI DTO. Never treat
# these as WorkTypeDef names when flattening a work_priority payload.
WORK_PRIORITY_RESERVED_KEYS: frozenset[str] = frozenset({
    "id",
    "priority",
    "pawn_id",
    "colonist_id",
    "target_colonist_id",
    "work",
    "work_type",
    "skill",
    "work_priorities",
    "reason",
    "map_id",
})

# Engine / RIMAPI phrasing for "these cells already belong to a zone".
ALREADY_COVERED_MARKERS: tuple[str, ...] = (
    "already cover",
    "already owned",
    "cells already",
    "owned by a zone",
    "zone already",
    "overlapping zone",
    "already assigned to a zone",
)


def is_quarantined_write(endpoint: str) -> bool:
    """True when the write must not be advertised or dispatched."""
    return endpoint in QUARANTINED_WRITES


def extract_work_priorities(params: dict[str, Any]) -> dict[str, int]:
    """Shape-normalize work_priority parameters. Does not validate names.

    Accepts the documented flat ``{"<WorkType>": <0-4>}`` map, the nested
    ``work_priorities`` object, and the single-type ``work`` /
    ``work_type`` + ``priority`` shape. Reserved DTO keys (``id``,
    ``priority``, …) are never treated as work types.
    """
    nested = params.get("work_priorities")
    if isinstance(nested, dict):
        out: dict[str, int] = {}
        for work, pri in nested.items():
            try:
                out[str(work)] = int(pri)
            except (TypeError, ValueError):
                continue
        return out

    work_name = params.get("work_type", params.get("work", params.get("skill")))
    named = work_name is not None and str(work_name)
    if named and str(work_name) not in WORK_PRIORITY_RESERVED_KEYS:
        raw_pri = params.get("priority", 1)
        try:
            return {str(work_name): int(raw_pri)}
        except (TypeError, ValueError):
            return {}

    flat: dict[str, int] = {}
    for work, pri in params.items():
        if work in WORK_PRIORITY_RESERVED_KEYS:
            continue
        if isinstance(pri, bool) or not isinstance(pri, int):
            continue
        flat[str(work)] = pri
    return flat


def normalize_work_priorities(
    params: dict[str, Any],
    allowed: frozenset[str] = VANILLA_WORK_TYPES,
) -> dict[str, int]:
    """Extract + validate WorkTypeDef names and RimWorld priority 0–4."""
    pairs = extract_work_priorities(params)
    if not pairs:
        raise ValueError(
            'work_priority requires {"<WorkType>": <0-4>} parameters '
            '(e.g. {"Growing": 1}). Do not send id/priority as the payload; '
            "target_colonist_id is the pawn. Work types come from "
            "GET /api/v1/work-list."
        )
    lookup = {name.lower(): name for name in allowed}
    validated: dict[str, int] = {}
    unknown: list[str] = []
    for work, pri in pairs.items():
        canonical = lookup.get(work.lower())
        if canonical is None:
            unknown.append(work)
            continue
        if pri < 0 or pri > 4:
            raise ValueError(
                f"work_priority {canonical}={pri} is out of range; "
                "RimWorld priorities are 0 (disabled) through 4 (lowest)"
            )
        validated[canonical] = pri
    if unknown:
        sample = ", ".join(sorted(allowed)[:8])
        raise ValueError(
            f"Unknown WorkTypeDef {unknown!r}. Use names from "
            f"/api/v1/work-list (e.g. {sample}, …)"
        )
    return validated


def growing_zone_already_covers(payload: Any) -> bool:
    """True when ``POST /builder/check-zone`` (or equivalent) says a zone owns cells.

    Handles both the develop ``issues.zones`` shape and the docs
    ``occupied_cells`` summary.
    """
    if not isinstance(payload, dict):
        return False
    issues = payload.get("issues", payload.get("Issues"))
    if isinstance(issues, dict):
        zones = issues.get("zones", issues.get("Zones"))
        if isinstance(zones, list) and zones:
            return True
    occupied = payload.get("occupied_cells", payload.get("OccupiedCells"))
    return isinstance(occupied, int) and occupied > 0


def is_already_covered_error(message: str) -> bool:
    """True when a RIMAPI/engine error means the zone already covers the cells."""
    text = message.lower()
    return any(marker in text for marker in ALREADY_COVERED_MARKERS)


def research_target_status(project: str, research: ResearchData) -> str:
    """Classify a research target against the current tree.

    Returns ``available``, ``current``, ``finished``, or ``locked``.
    Comparison is case-insensitive on defName.
    """
    name = project.strip()
    if not name:
        raise ValueError('research_target requires "project" (research defName)')
    key = name.lower()
    current = (research.current_project or "").strip()
    if current and current.lower() == key:
        return "current"
    if any(item.lower() == key for item in research.completed):
        return "finished"
    if any(item.lower() == key for item in research.available):
        return "available"
    return "locked"


def living_colonists(colonists: list[ColonistData]) -> dict[str, ColonistData]:
    """Colonists with health > 0, keyed by ``colonist_id``."""
    return {c.colonist_id: c for c in colonists if c.health > 0}


def resolve_tend_pair(
    patient_id: str,
    params: dict[str, Any],
    state: GameState | None,
) -> tuple[str, str]:
    """Return ``(doctor_id, patient_id)`` or raise if the pair is invalid.

    Patient comes from ``target_colonist_id`` / ``patient_pawn_id``.
    Doctor comes from ``doctor_pawn_id`` / ``doctor_id``. When ``state``
    is present both must be living colonists and must be distinct.
    """
    patient = str(params.get("patient_pawn_id") or params.get("patient_id") or patient_id or "")
    doctor_raw = params.get("doctor_pawn_id")
    if doctor_raw is None:
        doctor_raw = params.get("doctor_id")
    doctor = "" if doctor_raw is None else str(doctor_raw)

    if not patient or patient == "0":
        raise ValueError(
            "tend requires a living patient "
            "(target_colonist_id or patient_pawn_id)"
        )
    if not doctor or doctor == "0":
        raise ValueError(
            "tend requires a living doctor (doctor_pawn_id)"
        )
    if doctor == patient:
        raise ValueError("tend requires a distinct living doctor and patient")

    if state is None:
        return doctor, patient

    living = living_colonists(state.colonists)
    if patient not in living:
        raise ValueError(f"tend patient {patient} is missing or not alive")
    if doctor not in living:
        raise ValueError(f"tend doctor {doctor} is missing or not alive")
    return doctor, patient
