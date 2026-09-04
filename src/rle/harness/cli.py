"""argparse glue shared by ``run_scenario.py`` and ``run_benchmark.py``.

Keeps harness selection identical across CLIs:

    --harness <name>            registry name (default: RLEConfig.harness)
    --harness list              print discovered plugins and exit
    --harness-opt key=value     validated against the plugin's option schema
    --no-agent                  permanent alias for --harness baseline

Legacy Felix flags (``--no-think``, ``--sequential``, ``--visualize``) are
still accepted and folded into ``FelixOptions`` when the selected harness is
``felix``; for any other harness they are ignored with a warning.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from rle.config import RLEConfig
from rle.harness.registry import list_harnesses, parse_option_pairs

logger = logging.getLogger(__name__)

LIST_SENTINEL = "list"

_LEGACY_FELIX_FLAGS: dict[str, tuple[str, Any]] = {
    # argparse attribute -> (FelixOptions field, value when the flag is set)
    "no_think": ("no_think", True),
    "sequential": ("parallel", False),
    "visualize": ("visualize", True),
}


def add_harness_args(parser: argparse.ArgumentParser, *, repeatable: bool = False) -> None:
    kwargs: dict[str, Any] = {"action": "append"} if repeatable else {}
    parser.add_argument(
        "--harness", dest="harness", default=None,
        help=(
            "Harness that decides the colony's actions (default: RLE_HARNESS / felix). "
            "Use `--harness list` to see installed plugins."
            + (" Repeat to run a harness matrix." if repeatable else "")
        ),
        **kwargs,
    )
    parser.add_argument(
        "--harness-opt", dest="harness_opts", action="append", default=[],
        metavar="KEY=VALUE",
        help="Harness-specific option (repeatable); validated by the plugin's schema.",
    )
    parser.add_argument(
        "--no-agent", action="store_true",
        help="Baseline mode: alias for --harness baseline (colony runs unmanaged).",
    )
    parser.add_argument(
        "--no-think", action="store_true",
        help="[felix] Inject </think> prefill so thinking models skip reasoning.",
    )
    parser.add_argument(
        "--sequential", action="store_true",
        help="[felix] Deliberate role agents one at a time (default: parallel).",
    )
    parser.add_argument(
        "--visualize", action="store_true",
        help="[felix] Show the live helix visualisation.",
    )


def format_harness_table() -> str:
    rows = list_harnesses()
    if not rows:
        return "No harness plugins installed (entry-point group 'rle.harnesses')."
    name_w = max(len(r.name) for r in rows)
    pkg_w = max(len(f"{r.package} {r.version}") for r in rows)
    lines = [f"{'HARNESS':<{name_w}}  {'PACKAGE':<{pkg_w}}  STATUS       DESCRIPTION"]
    for r in rows:
        status = "available" if r.availability.ok else "unavailable"
        pkg = f"{r.package} {r.version}"
        desc = r.description
        if not r.availability.ok:
            desc = f"{desc} ({r.availability.reason})"
        lines.append(f"{r.name:<{name_w}}  {pkg:<{pkg_w}}  {status:<11}  {desc}")
    return "\n".join(lines)


def maybe_handle_harness_list(args: argparse.Namespace) -> bool:
    """Print the plugin table and return True when ``--harness list`` was given."""
    raw = getattr(args, "harness", None)
    names = raw if isinstance(raw, list) else [raw]
    if any(n == LIST_SENTINEL for n in names if n):
        print(format_harness_table())
        return True
    return False


def selected_harnesses(args: argparse.Namespace, config: RLEConfig) -> list[str]:
    """Resolve the harness name(s) from CLI flags + config."""
    if getattr(args, "no_agent", False):
        return ["baseline"]
    raw = getattr(args, "harness", None)
    if raw is None:
        return [config.harness]
    names = raw if isinstance(raw, list) else [raw]
    return [n for n in names if n and n != LIST_SENTINEL] or [config.harness]


def harness_options_for(
    name: str, args: argparse.Namespace, config: RLEConfig,
) -> dict[str, Any]:
    """Merge config options, legacy Felix flags, and ``--harness-opt`` pairs."""
    options: dict[str, Any] = dict(config.harness_options)
    legacy_set = {
        field: value
        for attr, (field, value) in _LEGACY_FELIX_FLAGS.items()
        if getattr(args, attr, False)
    }
    if legacy_set:
        if name == "felix":
            options.update(legacy_set)
        else:
            logger.warning(
                "Ignoring Felix-only flags %s for harness %r",
                sorted(legacy_set), name,
            )
    options.update(parse_option_pairs(getattr(args, "harness_opts", None)))
    return options


def exit_with_harness_error(exc: Exception) -> None:
    print(f"error: {exc}", file=sys.stderr)
    print(format_harness_table(), file=sys.stderr)
    raise SystemExit(2)
