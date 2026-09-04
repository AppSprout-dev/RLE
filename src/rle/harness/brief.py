"""Harness-neutral scenario brief.

Every harness receives the same facts: what the scenario asks for, the
current colony state, the deterministic MAP_SUMMARY (verified build / farm /
stockpile sites, water to avoid), and the action catalog it may use. Anything
beyond that — role splits, bootstrap playbooks, phase-dependent temperature,
tool-call framing — is the harness's own prompt engineering and is part of
what the benchmark measures.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from rle.rimapi.api_catalog import WRITE_CATALOG
from rle.rimapi.schemas import GameState
from rle.rimapi.sse_client import RimAPIEvent
from rle.scenarios.schema import ScenarioConfig

# Colonist fields worth a harness's attention (full dumps blow context budgets).
_COLONIST_FIELDS = (
    "colonist_id", "name", "health", "mood", "current_job", "is_drafted", "position",
)
_MAX_EVENTS = 12


def build_map_summary(state: GameState) -> str | None:
    """Compact (~500 token) spatial summary from terrain + zone + room data.

    Coordinates here are verified against the terrain grid; harnesses are told
    to use them verbatim rather than invent positions.
    """
    terrain = state.map.terrain
    if terrain is None:
        return None

    lines: list[str] = []
    cx, cz = terrain.colony_center
    lines.append(f"Colony center: ({cx}, {cz}).")

    if terrain.recommended_shelter:
        s = terrain.recommended_shelter
        lines.append(
            f"SHELTER SITE (verified solid ground): "
            f"place walls/doors/beds at ({s.x1},{s.z1})-({s.x2},{s.z2}). "
            f"ALL blueprint actions MUST use x,z within this rectangle."
        )
    if terrain.recommended_farm:
        f = terrain.recommended_farm
        lines.append(
            f"FARM SITE (verified fertile soil): "
            f"place growing_zone at x1={f.x1},z1={f.z1},x2={f.x2},z2={f.z2}. "
            f"ALL growing_zone actions MUST use these exact coordinates."
        )
    if terrain.recommended_stockpile:
        sp = terrain.recommended_stockpile
        lines.append(
            f"STOCKPILE SITE (verified solid ground): "
            f"place stockpile_zone at x1={sp.x1},z1={sp.z1},"
            f"x2={sp.x2},z2={sp.z2}."
        )

    if terrain.water_areas:
        water_strs = [f"({w.x1},{w.z1})-({w.x2},{w.z2})" for w in terrain.water_areas]
        lines.append(f"WATER (do NOT build here): {', '.join(water_strs)}.")

    if state.map.zones:
        zone_strs = [
            f"{z.label} ({z.zone_type}, {z.cell_count} cells)"
            for z in state.map.zones[:8]
        ]
        lines.append(f"Zones: {'; '.join(zone_strs)}.")
    else:
        lines.append("Zones: NONE — create stockpile and growing zone NOW.")

    real_rooms = [r for r in state.map.rooms if r.size > 1]
    if real_rooms:
        room_strs = [f"{r.role} ({r.size} cells, {r.bed_count} beds)" for r in real_rooms[:6]]
        lines.append(f"Rooms: {'; '.join(room_strs)}.")
    else:
        lines.append(
            "Rooms: NONE — colonists sleeping outside. "
            "Build shelter IMMEDIATELY."
        )

    if state.map.ore_deposits:
        ore_strs = [
            f"{o.def_name} ({o.count} cells"
            + (f", near ({o.positions[0][0]},{o.positions[0][1]})" if o.positions else "")
            + ")"
            for o in state.map.ore_deposits[:5]
        ]
        lines.append(f"Ore: {'; '.join(ore_strs)}.")

    fs = state.map.farm_summary
    if fs and fs.total_growing_zones > 0:
        lines.append(
            f"Farms: {fs.total_growing_zones} zones, "
            f"{fs.planted_cells} planted, "
            f"{fs.harvestable_cells} harvestable."
        )

    return "\n".join(lines)


def action_catalog() -> list[dict[str, Any]]:
    """Every write a harness may issue, with its parameter shape."""
    out: list[dict[str, Any]] = [
        {"action_type": "no_action", "description": "Do nothing this tick.", "params": {}},
    ]
    for name, raw in sorted(WRITE_CATALOG.items()):
        entry = cast(dict[str, Any], raw)
        out.append({
            "action_type": name,
            "description": entry.get("description", ""),
            "params": entry.get("params", {}),
        })
    return out


def scenario_goals(scenario: ScenarioConfig | None) -> dict[str, Any]:
    if scenario is None:
        return {}
    return {
        "name": scenario.name,
        "description": scenario.description,
        "difficulty": scenario.difficulty,
        "expected_duration_days": scenario.expected_duration_days,
        "victory": [f"{c.metric} {c.operator} {c.value}" for c in scenario.victory_conditions],
        "failure": [f"{c.metric} {c.operator} {c.value}" for c in scenario.failure_conditions],
        "scoring_weights": dict(scenario.scoring_weights),
    }


def state_snapshot(state: GameState) -> dict[str, Any]:
    """The colony as any harness should see it — no role filtering."""
    return {
        "colony": state.colony.model_dump(),
        "colonists": [
            {k: getattr(c, k) for k in _COLONIST_FIELDS} for c in state.colonists
        ],
        "resources": state.resources.model_dump(),
        "research": state.research.model_dump(),
        "threats": [t.model_dump() for t in state.threats],
        "weather": state.weather.model_dump(),
        "map": {
            "size": state.map.size,
            "biome": state.map.biome,
            "season": state.map.season,
            "temperature": state.map.temperature,
            "structures": len(state.map.structures),
            "zones": len(state.map.zones),
            "rooms": len([r for r in state.map.rooms if r.size > 1]),
        },
    }


class ScenarioBrief(BaseModel):
    """What the environment tells a harness at the start of a tick."""

    model_config = ConfigDict(frozen=True)

    tick: int
    day: int
    macro_time: float
    goals: dict[str, Any]
    state: dict[str, Any]
    map_summary: str | None
    recent_events: list[dict[str, Any]]
    actions: list[dict[str, Any]]

    def to_text(self) -> str:
        """Plain-text rendering for prompt-based harnesses."""
        parts = [
            f"# RimWorld colony — tick {self.tick}, day {self.day} "
            f"(run progress {self.macro_time:.0%})",
        ]
        if self.goals:
            g = self.goals
            parts.append(
                f"## Scenario: {g.get('name')} ({g.get('difficulty')})\n{g.get('description')}\n"
                f"Victory: {'; '.join(g.get('victory', []))}\n"
                f"Failure: {'; '.join(g.get('failure', []))}",
            )
        if self.map_summary:
            parts.append(f"## MAP_SUMMARY\n{self.map_summary}")
        parts.append("## State\n" + _render(self.state))
        if self.recent_events:
            parts.append(
                "## Recent events\n"
                + "\n".join(f"- {e['event_type']}: {e['data']}" for e in self.recent_events),
            )
        parts.append(
            "## Actions available\n"
            + "\n".join(
                f"- {a['action_type']}: {a['description']} params={a['params']}"
                for a in self.actions
            ),
        )
        return "\n\n".join(parts)


def _render(data: dict[str, Any], indent: int = 0) -> str:
    lines: list[str] = []
    pad = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_render(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{pad}{key}: {value}")
        else:
            lines.append(f"{pad}{key}: {value}")
    return "\n".join(lines)


def build_brief(
    state: GameState,
    *,
    tick: int,
    macro_time: float,
    scenario: ScenarioConfig | None = None,
    events: list[RimAPIEvent] | None = None,
) -> ScenarioBrief:
    return ScenarioBrief(
        tick=tick,
        day=state.colony.day,
        macro_time=macro_time,
        goals=scenario_goals(scenario),
        state=state_snapshot(state),
        map_summary=build_map_summary(state),
        recent_events=[
            {"event_type": e.event_type, "data": str(e.data)[:200]}
            for e in (events or [])[:_MAX_EVENTS]
        ],
        actions=action_catalog(),
    )
