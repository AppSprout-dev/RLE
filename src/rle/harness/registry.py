"""Harness discovery via the ``rle.harnesses`` entry-point group.

Built-in harnesses (``baseline``, ``felix``) and third-party packages
(``rle-harness-<tool>``) register the same way, so adding a harness is
``pip install <package>`` — never a change to RLE core.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from rle.harness.protocol import Availability, BaseHarness, HarnessContext, HarnessPlugin

ENTRY_POINT_GROUP = "rle.harnesses"


class HarnessNotFoundError(LookupError):
    """No plugin registered under the requested name."""


class HarnessUnavailableError(RuntimeError):
    """The plugin exists but cannot run here (missing extra, binary, ...)."""


class HarnessOptionsError(ValueError):
    """Harness options failed validation against the plugin's schema."""


@dataclass(frozen=True)
class HarnessInfo:
    name: str
    description: str
    availability: Availability
    package: str
    version: str


def _entry_points() -> dict[str, EntryPoint]:
    found: dict[str, EntryPoint] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if ep.name in found:
            other = found[ep.name]
            raise RuntimeError(
                f"Two packages register harness {ep.name!r}: "
                f"{_dist_name(other)} and {_dist_name(ep)}. Uninstall one.",
            )
        found[ep.name] = ep
    return found


def _dist_name(ep: EntryPoint) -> str:
    dist = ep.dist
    return dist.metadata["Name"] if dist is not None else "?"


def _dist_version(ep: EntryPoint) -> str:
    dist = ep.dist
    return dist.version if dist is not None else "?"


def harness_names() -> list[str]:
    return sorted(_entry_points())


def get_plugin(name: str) -> HarnessPlugin:
    eps = _entry_points()
    ep = eps.get(name)
    if ep is None:
        raise HarnessNotFoundError(
            f"Unknown harness {name!r}. Installed: {', '.join(sorted(eps)) or '(none)'}. "
            "Install a harness package (rle-harness-<tool>) or check the name.",
        )
    return cast(HarnessPlugin, ep.load())


def list_harnesses() -> list[HarnessInfo]:
    infos: list[HarnessInfo] = []
    for name, ep in sorted(_entry_points().items()):
        try:
            plugin = cast(HarnessPlugin, ep.load())
            availability = plugin.available()
            description = plugin.description
        except Exception as exc:  # a broken plugin must not break the CLI
            availability = Availability.missing(f"plugin failed to load: {exc}")
            description = ""
        infos.append(HarnessInfo(
            name=name,
            description=description,
            availability=availability,
            package=_dist_name(ep),
            version=_dist_version(ep),
        ))
    return infos


def parse_option_pairs(pairs: list[str] | None) -> dict[str, Any]:
    """Turn ``["key=value", ...]`` into a dict, decoding JSON-looking values.

    ``true``/``false``/numbers/quoted strings/objects parse as JSON; anything
    else is kept as the raw string.
    """
    out: dict[str, Any] = {}
    for pair in pairs or []:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise HarnessOptionsError(f"--harness-opt expects key=value, got {pair!r}")
        try:
            out[key.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            out[key.strip()] = raw
    return out


def validate_options(plugin: HarnessPlugin, raw: dict[str, Any] | BaseModel | None) -> BaseModel:
    schema = plugin.option_schema()
    if isinstance(raw, BaseModel):
        if isinstance(raw, schema):
            return raw
        raw = raw.model_dump()
    try:
        return schema.model_validate(raw or {})
    except ValidationError as exc:
        raise HarnessOptionsError(
            f"Invalid options for harness {plugin.name!r}:\n{exc}",
        ) from exc


def create_harness(
    name: str,
    ctx: HarnessContext,
    options: dict[str, Any] | BaseModel | None = None,
    *,
    smoke: bool = False,
) -> BaseHarness:
    """Resolve ``name`` through the registry and build a ready-to-setup harness."""
    plugin = get_plugin(name)
    availability = plugin.available()
    if not availability.ok:
        raise HarnessUnavailableError(
            f"Harness {name!r} is installed but unavailable: {availability.reason}",
        )
    opts = validate_options(plugin, options)
    if smoke or ctx.smoke:
        return plugin.smoke(ctx, opts)
    return plugin.create(ctx, opts)
