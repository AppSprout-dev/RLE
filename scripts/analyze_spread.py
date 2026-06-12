"""Cross-model analysis of the Stage S spread per the run-analysis playbook:
composite vs pinned baseline, action success BY TYPE (harness vs model failures),
parse health, trajectory shape. Writes leaderboard.json + analysis.md.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

# Failure substrings attributable to the harness / known RIMAPI quirks, not the model.
HARNESS_FAILURE_MARKERS = [
    "Invalid plant definition",          # Plant_Rice / Plant_Potato def-name quirk
    "invalid literal for int()",         # stockpile priority string crash (our executor)
    "Object reference not set",          # RIMAPI null-ref
]


def load_model(d: Path) -> dict:
    summary = json.loads((d / "01_crashlanded_survival_summary.json").read_text(encoding="utf-8"))
    ticks = []
    with (d / "01_crashlanded_survival.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ticks.append({
                k: (float(v) if v.replace(".", "", 1).replace("-", "", 1).isdigit() else v)
                for k, v in row.items()
            })
    by_type: dict[str, Counter] = defaultdict(Counter)
    failures = []
    delib = {"count": 0, "zero_action": 0, "latencies": [], "confidences": []}
    with (d / "events.jsonl").open(encoding="utf-8") as f:
        for ln in f:
            e = json.loads(ln)
            et, data = e.get("event_type"), e.get("data", {})
            if et == "action_exec":
                t = data.get("action_type", "?")
                ok = data.get("success")
                by_type[t]["ok" if ok else "fail"] += 1
                if not ok:
                    failures.append({"tick": e.get("tick"), "type": t,
                                     "error": (data.get("error") or "")[:160]})
            elif et == "deliberation":
                delib["count"] += 1
                delib["latencies"].append(data.get("latency_ms", 0))
                delib["confidences"].append(data.get("confidence", 0))
                if data.get("num_actions", 0) == 0:
                    delib["zero_action"] += 1

    harness_fails = sum(1 for fl in failures
                        if any(m in fl["error"] for m in HARNESS_FAILURE_MARKERS))
    total_ok = sum(c["ok"] for c in by_type.values())
    total_fail = sum(c["fail"] for c in by_type.values())
    total = total_ok + total_fail
    model_fails = total_fail - harness_fails
    return {
        "summary": summary,
        "ticks": ticks,
        "by_type": {t: dict(c) for t, c in sorted(by_type.items())},
        "failures": failures,
        "deliberation": {
            "count": delib["count"],
            "zero_action": delib["zero_action"],
            "avg_latency_ms": round(
                sum(delib["latencies"]) / max(len(delib["latencies"]), 1), 1),
            "avg_confidence": round(
                sum(delib["confidences"]) / max(len(delib["confidences"]), 1), 3),
        },
        "actions": {
            "total": total, "ok": total_ok, "fail": total_fail,
            "raw_success": round(total_ok / total, 4) if total else None,
            "harness_fails": harness_fails, "model_fails": model_fails,
            "ex_artifact_success": round(total_ok / (total - harness_fails), 4)
            if total - harness_fails else None,
        },
    }


def load_baseline_by_day(baseline_runs_dir: Path) -> dict[int, float]:
    """Day-indexed baseline composite: mean across seeds of per-day mean composite.

    The pinned sidecar trajectory is tick-indexed at ~30 ticks/day while agent runs
    tick ~2-3x/day, so tick-alignment compares different game days. Day-align instead.
    """
    per_day: dict[int, list[float]] = defaultdict(list)
    for csv_path in sorted(baseline_runs_dir.glob("seed*/01_crashlanded_survival.csv")):
        seed_days: dict[int, list[float]] = defaultdict(list)
        with csv_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                seed_days[int(float(row["day"]))].append(float(row["composite"]))
        for day, vals in seed_days.items():
            per_day[day].append(sum(vals) / len(vals))
    return {day: sum(v) / len(v) for day, v in sorted(per_day.items())}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spread-dir", default="results/spread")
    ap.add_argument("--baseline",
                    default="src/rle/scenarios/definitions/01_crashlanded_survival.baseline.json")
    ap.add_argument("--baseline-runs", default="results/baseline/01_crashlanded_survival")
    ap.add_argument("--out-json", default="results/spread/leaderboard.json")
    ap.add_argument("--out-md", default="results/spread/analysis.md")
    args = ap.parse_args()

    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_by_day = load_baseline_by_day(Path(args.baseline_runs))

    models = {}
    for d in sorted(Path(args.spread_dir).iterdir()):
        if d.is_dir() and (d / "01_crashlanded_survival_summary.json").exists():
            models[d.name] = load_model(d)

    rows = []
    for name, m in models.items():
        traj = [t["composite"] for t in m["ticks"]]
        days = [t["day"] for t in m["ticks"]]
        n = len(traj)
        max_base_day = max(base_by_day)
        base_slice = [base_by_day[min(int(d), max_base_day)] for d in days]
        delta = [round(a - b, 4) for a, b in zip(traj, base_slice)]
        ticks_above = sum(1 for x in delta if x > 0)
        c = m["summary"]["cost_snapshot"]
        # Billed ground truth (run_scenario reconciles via OpenRouter's
        # generation API) — same schema we hand-patched into the v0.3.0
        # leaderboard from the dashboard. Estimates stay for comparison.
        billed = m["summary"].get("billed_cost")
        rows.append({
            "model": m["summary"]["model"],
            "name": name,
            "final_composite": m["summary"]["final_score"],
            "mean_composite": round(sum(traj) / n, 4),
            "vs_baseline_mean_delta": round(sum(delta) / n, 4),
            "ticks_above_baseline": f"{ticks_above}/{n}",
            "end_day": days[-1] if days else None,
            "raw_action_success": m["actions"]["raw_success"],
            "ex_artifact_success": m["actions"]["ex_artifact_success"],
            "harness_fails": m["actions"]["harness_fails"],
            "model_fails": m["actions"]["model_fails"],
            "zero_action_delibs": m["deliberation"]["zero_action"],
            "delib_count": m["deliberation"]["count"],
            "avg_latency_s": round(m["deliberation"]["avg_latency_ms"] / 1000, 1),
            "avg_confidence": m["deliberation"]["avg_confidence"],
            "wall_min": round(c["wall_time_s"] / 60, 1),
            "est_cost_usd": round(c["estimated_cost_usd"], 2),
            "real_cost_usd": (
                round(billed["billed_cost_usd"], 3) if billed else None
            ),
            "cost_source": billed["source"] if billed else None,
            "trajectory": traj,
            "days": days,
            "baseline_slice": [round(x, 4) for x in base_slice],
        })
    rows.sort(key=lambda r: r["mean_composite"], reverse=True)

    Path(args.out_json).write_text(json.dumps(
        {"baseline": {"mean_time_to_end_days": baseline["time_to_end_days_mean"],
                      "n_runs": baseline["n_runs"]},
         "note": ("N=1 content-first spread; not statistically valid. "
                  "Ranked by mean composite over 10 ticks."),
         "rows": rows}, indent=2), encoding="utf-8")

    md = ["# Stage S Spread — N=1 Leaderboard (10 ticks, seed 42)\n",
          "Ranked by **mean composite over 10 ticks** (endpoint scores are single-event noisy).",
          f"Baseline: no-agent, N={baseline['n_runs']}, mean time-to-end "
          f"{baseline['time_to_end_days_mean']}d.\n",
          "| # | model | mean comp | final | vs base Δ | ticks>base | end day | act ok (raw) "
          "| act ok (ex-artifact) | harness/model fails | 0-act delibs | avg delib s "
          "| wall min | $ |",
          "|---|-------|-----------|-------|-----------|------------|---------|-------|-------|"
          "------|------|------|------|---|"]
    for i, r in enumerate(rows, 1):
        md.append(
            f"| {i} | {r['name']} | {r['mean_composite']:.3f} | {r['final_composite']:.3f} "
            f"| {r['vs_baseline_mean_delta']:+.3f} | {r['ticks_above_baseline']} "
            f"| {r['end_day']:.0f} "
            f"| {r['raw_action_success']:.0%} | {r['ex_artifact_success']:.0%} "
            f"| {r['harness_fails']}/{r['model_fails']} | {r['zero_action_delibs']} "
            f"| {r['avg_latency_s']} | {r['wall_min']} | {r['est_cost_usd']} |")
    md.append("\n## Per-model action success by type\n")
    for name, m in models.items():
        md.append(f"### {name}")
        for t, c in m["by_type"].items():
            ok, fail = c.get("ok", 0), c.get("fail", 0)
            flag = " ⚠ ALL FAILED" if ok == 0 and fail > 0 else ""
            md.append(f"- {t}: {ok}/{ok + fail}{flag}")
        if m["failures"]:
            md.append(f"- failures ({len(m['failures'])}):")
            for fl in m["failures"][:8]:
                md.append(f"  - tick {fl['tick']} {fl['type']}: {fl['error']}")
        md.append("")
    Path(args.out_md).write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {args.out_json} and {args.out_md}")
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['name']:<11} mean={r['mean_composite']:.3f} "
              f"final={r['final_composite']:.3f} "
              f"Δbase={r['vs_baseline_mean_delta']:+.3f} "
              f"ex-artifact-ok={r['ex_artifact_success']:.0%} "
              f"0act={r['zero_action_delibs']} ${r['est_cost_usd']}")


if __name__ == "__main__":
    main()
