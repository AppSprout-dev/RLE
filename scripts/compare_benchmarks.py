"""CLI: compare benchmark runs from history JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    runs = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            runs.append(json.loads(line))
    return runs


def _model_short(model: str) -> str:
    return model.split("/")[-1][:25] if model else "unknown"


def print_history(runs: list[dict], model_filter: str | None = None) -> None:
    if model_filter:
        runs = [r for r in runs if model_filter.lower() in r.get("model", "").lower()]

    if not runs:
        print("No benchmark runs found.")
        return

    print(f"\nRLE Benchmark History ({len(runs)} runs)")
    print("=" * 90)
    header = (
        f"{'Date':<12} {'Commit':<8} {'Model':<25} "
        f"{'Score':>6} {'Parse%':>7} {'s/tick':>7} {'Ticks':>5} {'Time':>7}"
    )
    print(header)
    print("-" * 90)

    for r in runs:
        ts = r.get("timestamp", "")[:10]
        commit = r.get("git_commit", "?")[:7]
        model = _model_short(r.get("model", ""))
        scenarios = r.get("scenarios", [])
        scores = [s.get("score", 0) for s in scenarios]
        avg_score = sum(scores) / len(scores) if scores else 0
        total_parse = sum(s.get("parse_successes", 0) for s in scenarios)
        total_fail = sum(s.get("parse_failures", 0) for s in scenarios)
        total_calls = total_parse + total_fail
        parse_rate = total_parse / total_calls if total_calls else 0
        total_time = sum(s.get("elapsed_s", 0) for s in scenarios)
        total_ticks = sum(s.get("ticks", 0) for s in scenarios)
        avg_spt = total_time / total_ticks if total_ticks else 0

        print(
            f"{ts:<12} {commit:<8} {model:<25} "
            f"{avg_score:>6.3f} {parse_rate:>6.1%} {avg_spt:>7.1f} "
            f"{total_ticks:>5} {total_time:>6.0f}s"
        )

    print("=" * 90)


def print_scenario_detail(runs: list[dict], scenario_filter: str) -> None:
    print(f"\nScenario: {scenario_filter}")
    print("=" * 80)
    header = f"{'Date':<12} {'Model':<25} {'Score':>6} {'Parse%':>7} {'s/tick':>7} {'Outcome':<9}"
    print(header)
    print("-" * 80)

    for r in runs:
        ts = r.get("timestamp", "")[:10]
        model = _model_short(r.get("model", ""))
        for s in r.get("scenarios", []):
            if scenario_filter.lower() in s.get("name", "").lower():
                print(
                    f"{ts:<12} {model:<25} {s['score']:>6.3f} "
                    f"{s.get('parse_rate', 0):>6.1%} "
                    f"{s.get('sec_per_tick', 0):>7.1f} {s.get('outcome', '?'):<9}"
                )

    print("=" * 80)


def print_baselines(baselines_dir: Path) -> None:
    if not baselines_dir.exists():
        print("No baselines found.")
        return

    files = sorted(baselines_dir.glob("*.json"))
    if not files:
        print("No baselines found.")
        return

    print("\nRLE Baselines (Leaderboard)")
    print("=" * 70)
    print(f"{'Model':<35} {'Score':>6} {'Commit':<8} {'Date':<12}")
    print("-" * 70)

    for f in files:
        b = json.loads(f.read_text())
        model = _model_short(b.get("model", f.stem))
        print(
            f"{model:<35} {b.get('avg_score', 0):>6.3f} "
            f"{b.get('git_commit', '?'):<8} {b.get('timestamp', '')[:10]:<12}"
        )

    print("=" * 70)


def plot_history(runs: list[dict]) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed. Run: pip install matplotlib")
        return

    if not runs:
        print("No runs to plot.")
        return

    labels = []
    scores = []
    for r in runs:
        scenarios = r.get("scenarios", [])
        if not scenarios:
            continue
        avg = sum(s.get("score", 0) for s in scenarios) / len(scenarios)
        model = _model_short(r.get("model", "?"))
        ts = r.get("timestamp", "")[:10]
        labels.append(f"{ts}\n{model}")
        scores.append(avg)

    fig, ax = plt.subplots(figsize=(max(8, len(scores) * 1.2), 5))
    bars = ax.bar(range(len(scores)), scores, color="#00bcd4")
    ax.set_ylabel("Avg Composite Score")
    ax.set_title("RLE Benchmark History")
    ax.set_xticks(range(len(scores)))
    ax.set_xticklabels(labels, fontsize=8, rotation=45, ha="right")
    ax.set_ylim(0, 1)
    for bar, score in zip(bars, scores):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                f"{score:.3f}", ha="center", fontsize=8)
    plt.tight_layout()
    plt.savefig("results/benchmark_history.png", dpi=150)
    print("Plot saved to results/benchmark_history.png")
    plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare RLE benchmark runs")
    parser.add_argument("--model", help="Filter by model name")
    parser.add_argument("--scenario", help="Show per-scenario detail")
    parser.add_argument("--baselines", action="store_true", help="Show baseline leaderboard")
    parser.add_argument("--plot", action="store_true", help="Plot score history")
    parser.add_argument(
        "--history", default="results/benchmark_history.jsonl",
        help="Path to history JSONL",
    )
    args = parser.parse_args()

    history_path = Path(args.history)
    runs = load_history(history_path)

    if args.baselines:
        print_baselines(Path("results/baselines"))
    elif args.scenario:
        print_scenario_detail(runs, args.scenario)
    elif args.plot:
        plot_history(runs)
    else:
        print_history(runs, model_filter=args.model)
