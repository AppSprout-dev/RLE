"""Export a spread's leaderboard.json into website-ready artifacts.

Bridges the run-analysis pipeline to rle.appsprout.dev: reads
results/<run>/leaderboard.json (written by analyze_spread.py) and emits

  <out>/data.fragment.ts   META + MODELS blocks matching the ModelRow
                           interface in AppSprout-Site client/src/rle/data.ts
  <out>/site_data.json     the same payload as JSON (HF dataset / API ingestion)

Editorial blocks (HERO_LOG, STORY, AGENTS, OG_*) stay hand-curated — this
covers the mechanical half of a fold-in so leaderboard numbers are never
hand-transcribed again.

Usage:
    python scripts/export_site_data.py --spread-dir results/spread --date 2026-06-11
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from rle.tracking.cost_tracker import is_pareto_cost_source

# Display name / family / family swatch per model slug, mirroring the palette
# in AppSprout-Site client/src/rle/data.ts. Unknown slugs fall back to a
# derived family + neutral color with a warning, so a new model never blocks
# an export.
MODEL_REGISTRY: dict[str, tuple[str, str, str]] = {
    "x-ai/grok-4.3": ("Grok 4.3", "xAI", "#C77DB8"),
    "mistralai/mistral-medium-3-5": ("Mistral Medium 3.5", "Mistral", "#FF7000"),
    "google/gemini-3.5-flash": ("Gemini 3.5 Flash", "Google", "#6B9BF0"),
    "qwen/qwen3.7-max": ("Qwen3.7 Max", "Alibaba", "#A36BFF"),
    "claude-fable-5": ("Claude Fable 5", "Anthropic", "#E8A06A"),
    "nvidia/nemotron-3-super-120b-a12b": ("Nemotron 3 Super 120B", "NVIDIA", "#76B900"),
    "claude-opus-4-8": ("Claude Opus 4.8", "Anthropic", "#D97757"),
    "z-ai/glm-5.1": ("GLM-5.1", "Zhipu", "#00D4D4"),
    "openai/gpt-5.5": ("GPT-5.5", "OpenAI", "#56B79A"),
    "deepseek/deepseek-v4-pro": ("DeepSeek-V4 Pro", "DeepSeek", "#8A7CF0"),
    "moonshotai/kimi-k2.6": ("Kimi K2.6", "Moonshot", "#9AA0A6"),
    "nvidia/nemotron-3-nano-30b-a3b": ("Nemotron 3 Nano 30B", "NVIDIA", "#76B900"),
    "unsloth/nvidia-nemotron-3-nano-4b": ("Nemotron 3 Nano 4B", "NVIDIA", "#76B900"),
}
FALLBACK_COLOR = "#B7AC8B"

# Optional published-pack backfill (Site may apply later). Not live-metered
# here and not fetched from any API — values from the n1-final pack review:
# CLI coding-agent harness estimated $1.594858 from 796917 tokens; Felix keep
# billed $0.857296; ACP console ~$7; raw = unknown / omit from cost Pareto.
PACK_COST_BACKFILL: dict[str, dict[str, object]] = {
    "cli-agent": {
        "cost_usd": 1.594858,
        "cost_source": "estimated",
        "note": "796917 tokens; pricing slug was openrouter/x-ai/grok-4.6",
    },
    "felix": {
        "cost_usd": 0.857296,
        "cost_source": "billed",
    },
    "acp": {
        "cost_usd": 7.0,
        "cost_source": "console",
        "note": "n1-final console ~$7",
    },
    "raw-grok": {
        "cost_usd": None,
        "cost_source": "unknown",
        "note": "omit from cost Pareto",
    },
}

GITHUB_URL = "https://github.com/AppSprout-dev/RLE"
GITHUB_REPO = "AppSprout-dev/RLE"
DISCORD_URL = "https://discord.gg/vKuyjqNEea"


def rnd(value: float, places: int) -> float:
    """Round half away from zero (matches hand-rounded site data, unlike
    Python's banker's rounding)."""
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def fmt(value: float, places: int) -> str:
    """Fixed-decimal literal for the TS output (keeps trailing zeros: 0.710, 4.00)."""
    return f"{rnd(value, places):.{places}f}"


def registry_entry(slug: str) -> tuple[str, str, str]:
    if slug in MODEL_REGISTRY:
        return MODEL_REGISTRY[slug]
    family = slug.split("/")[0] if "/" in slug else slug.split("-")[0]
    print(f"WARNING: {slug} not in MODEL_REGISTRY — using derived family "
          f"{family!r} + fallback color. Add it to the registry.", file=sys.stderr)
    return slug, family, FALLBACK_COLOR


def _row_cost_source(row: dict) -> str:
    raw = row.get("cost_source")
    return str(raw) if raw else "unknown"


def build_model(row: dict) -> dict:
    slug = row["model"]
    display, family, color = registry_entry(slug)
    source = _row_cost_source(row)
    eligible = bool(row.get("pareto_eligible", is_pareto_cost_source(source)))
    # Prefer the analyze-spread authoritative figure; never fall back to
    # unknown $0 (that used to land CLI/ACP/raw rows on the Site Pareto).
    display_cost = row.get("display_cost_usd")
    if display_cost is None and eligible:
        real = row.get("real_cost_usd")
        console = row.get("console_cost_usd")
        if source == "billed" and real is not None:
            display_cost = real
        elif source == "console" and console is not None:
            display_cost = console
        elif source == "estimated":
            display_cost = row.get("est_cost_usd")
    if not eligible:
        display_cost = None
    return {
        "slug": slug,
        "key": row["name"],
        "model": display,
        "family": family,
        "color": color,
        "meanComposite": rnd(row["mean_composite"], 3),
        "finalComposite": rnd(row["final_composite"], 3),
        "vsBaselineDelta": rnd(row["vs_baseline_mean_delta"], 3),
        "ticksAboveBaseline": row["ticks_above_baseline"],
        "endDay": int(row["end_day"]),
        "rawActionSuccess": rnd(row["raw_action_success"], 2),
        "exArtifactSuccess": rnd(row["ex_artifact_success"], 2),
        "avgLatencyS": rnd(row["avg_latency_s"], 1),
        "wallMin": rnd(row["wall_min"], 1),
        "costUsd": rnd(display_cost, 2) if display_cost is not None else None,
        "costEstimated": source == "estimated",
        "costSource": source,
        "paretoEligible": eligible and display_cost is not None,
    }


def build_meta(board: dict, rows: list[dict], args: argparse.Namespace) -> dict:
    metered: list[float] = []
    for r in board["rows"]:
        source = _row_cost_source(r)
        if source not in ("billed", "console"):
            continue
        amount = r.get("real_cost_usd") if source == "billed" else r.get("console_cost_usd")
        if amount is None:
            amount = r.get("display_cost_usd")
        if amount is not None:
            metered.append(float(amount))
    ticks = max((len(r.get("trajectory", [])) for r in board["rows"]), default=0)
    return {
        "scenario": args.scenario,
        "seed": args.seed,
        "ticks": args.ticks if args.ticks is not None else ticks,
        "nRuns": args.n_runs,
        "date": args.date,
        "totalSpendUsd": rnd(sum(metered), 2),
        "baselineMeanTteDays": int(board["baseline"]["mean_time_to_end_days"]),
        "githubUrl": GITHUB_URL,
        "githubRepo": GITHUB_REPO,
        "discordUrl": DISCORD_URL,
    }


def emit_ts(meta: dict, models: list[dict], spread_dir: Path) -> str:
    lines = [
        "// =====================================================================",
        "// GENERATED by scripts/export_site_data.py from",
        f"// {spread_dir.as_posix()}/leaderboard.json",
        "// Paste over the META + MODELS blocks in AppSprout-Site",
        "// client/src/rle/data.ts. Editorial blocks (HERO_LOG, STORY, AGENTS,",
        "// OG_*) stay hand-curated — update those from stories.md separately.",
        "// =====================================================================",
        "",
        "export const META = {",
        f'  scenario: "{meta["scenario"]}",',
        f"  seed: {meta['seed']},",
        f"  ticks: {meta['ticks']},",
        f"  nRuns: {meta['nRuns']},",
        f'  date: "{meta["date"]}",',
        "  // Billed + console spend; estimated/unknown rows are not included.",
        "  // Plot Pareto only when costSource is billed|estimated|console.",
        f"  totalSpendUsd: {fmt(meta['totalSpendUsd'], 2)},",
        f"  baselineMeanTteDays: {meta['baselineMeanTteDays']},",
        f'  githubUrl: "{meta["githubUrl"]}",',
        f'  githubRepo: "{meta["githubRepo"]}",',
        f'  discordUrl: "{meta["discordUrl"]}",',
        "} as const;",
        "",
        "// Ranked by mean composite over the run (analyze_spread.py ordering).",
        "export const MODELS: ModelRow[] = [",
    ]
    for m in models:
        lines += [
            "  {",
            f'    slug: "{m["slug"]}", key: "{m["key"]}", model: "{m["model"]}",'
            f' family: "{m["family"]}", color: "{m["color"]}",',
            f"    meanComposite: {fmt(m['meanComposite'], 3)},"
            f" finalComposite: {fmt(m['finalComposite'], 3)},"
            f" vsBaselineDelta: {fmt(m['vsBaselineDelta'], 3)},"
            f' ticksAboveBaseline: "{m["ticksAboveBaseline"]}",',
            f"    endDay: {m['endDay']}, rawActionSuccess: {fmt(m['rawActionSuccess'], 2)},"
            f" exArtifactSuccess: {fmt(m['exArtifactSuccess'], 2)},"
            f" avgLatencyS: {fmt(m['avgLatencyS'], 1)}, wallMin: {fmt(m['wallMin'], 1)},",
            f"    costUsd: {fmt(m['costUsd'], 2) if m['costUsd'] is not None else 'null'},"
            f" costEstimated: {'true' if m['costEstimated'] else 'false'},"
            f" costSource: \"{m['costSource']}\","
            f" paretoEligible: {'true' if m['paretoEligible'] else 'false'},",
            "  },",
        ]
    lines += ["];", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spread-dir", type=Path, required=True,
                        help="run dir containing leaderboard.json (e.g. results/spread)")
    parser.add_argument("--date", required=True, help="run date, YYYY-MM-DD")
    parser.add_argument("--out", type=Path, default=None,
                        help="output dir (default: <spread-dir>/site)")
    parser.add_argument("--scenario", default="Crashlanded")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ticks", type=int, default=None,
                        help="override tick count (default: longest trajectory)")
    parser.add_argument("--n-runs", type=int, default=1)
    args = parser.parse_args()

    board = json.loads((args.spread_dir / "leaderboard.json").read_text(encoding="utf-8"))
    models = [build_model(r) for r in board["rows"]]
    meta = build_meta(board, models, args)

    out = args.out or (args.spread_dir / "site")
    out.mkdir(parents=True, exist_ok=True)

    ts_path = out / "data.fragment.ts"
    ts_path.write_text(emit_ts(meta, models, args.spread_dir), encoding="utf-8")

    json_path = out / "site_data.json"
    json_path.write_text(
        json.dumps(
            {"meta": meta, "models": models, "costBackfill": PACK_COST_BACKFILL},
            indent=2,
        ) + "\n",
        encoding="utf-8")

    print(f"Wrote {ts_path}")
    print(f"Wrote {json_path}")
    print(f"{len(models)} models | total metered spend ${meta['totalSpendUsd']:.2f} "
          f"| date {meta['date']}")


if __name__ == "__main__":
    main()
