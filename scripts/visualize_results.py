"""Plot score timeseries from RLE benchmark CSV files.

Requires: uv sync --extra viz
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def _load_csv(path: Path) -> dict[str, list[float]]:
    """Load a CSV into column-name → list-of-values mapping."""
    with open(path) as f:
        reader = csv.DictReader(f)
        columns: dict[str, list[float]] = {}
        for row in reader:
            for key, value in row.items():
                columns.setdefault(key, []).append(float(value))
    return columns


def plot_scenario(csv_path: Path, output_path: Path | None = None) -> None:
    """Plot all metrics + composite for a single scenario CSV."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is required: uv sync --extra viz")
        sys.exit(1)

    data = _load_csv(csv_path)
    ticks = data.get("tick", [])
    if not ticks:
        print(f"No data in {csv_path}")
        return

    metric_names = [k for k in data if k not in ("tick", "day", "composite")]

    fig, (ax_metrics, ax_composite) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle(csv_path.stem.replace("_", " ").title(), fontsize=14)

    for name in metric_names:
        ax_metrics.plot(ticks, data[name], label=name, alpha=0.8)
    ax_metrics.set_ylabel("Metric Score (0-1)")
    ax_metrics.legend(loc="upper left", fontsize=8, ncol=4)
    ax_metrics.set_ylim(-0.05, 1.05)
    ax_metrics.grid(True, alpha=0.3)

    ax_composite.plot(ticks, data["composite"], color="black", linewidth=2, label="Composite")
    ax_composite.set_xlabel("Tick")
    ax_composite.set_ylabel("Composite Score")
    ax_composite.set_ylim(-0.05, 1.05)
    ax_composite.legend()
    ax_composite.grid(True, alpha=0.3)

    plt.tight_layout()

    if output_path:
        plt.savefig(output_path, dpi=150)
        print(f"Saved plot to {output_path}")
    else:
        save_to = csv_path.with_suffix(".png")
        plt.savefig(save_to, dpi=150)
        print(f"Saved plot to {save_to}")
    plt.close()


def plot_comparison(csv_dir: Path, output_path: Path | None = None) -> None:
    """Plot composite score comparison across all scenarios in a directory."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is required: uv sync --extra viz")
        sys.exit(1)

    csv_files = sorted(csv_dir.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {csv_dir}")
        return

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.suptitle("RLE Benchmark — Composite Score Comparison", fontsize=14)

    for csv_path in csv_files:
        data = _load_csv(csv_path)
        ticks = data.get("tick", [])
        composite = data.get("composite", [])
        if ticks and composite:
            label = csv_path.stem.replace("_", " ").title()
            ax.plot(ticks, composite, label=label, linewidth=1.5)

    ax.set_xlabel("Tick")
    ax.set_ylabel("Composite Score")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    save_to = output_path or csv_dir / "benchmark_comparison.png"
    plt.savefig(save_to, dpi=150)
    print(f"Saved comparison plot to {save_to}")
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize RLE benchmark results")
    parser.add_argument("path", help="CSV file or directory of CSVs")
    parser.add_argument("--all", action="store_true", help="Compare all CSVs in directory")
    parser.add_argument("--output", help="Output image path")
    args = parser.parse_args()

    path = Path(args.path)
    output = Path(args.output) if args.output else None

    if args.all or path.is_dir():
        directory = path if path.is_dir() else path.parent
        plot_comparison(directory, output)
    elif path.is_file():
        plot_scenario(path, output)
    else:
        print(f"Path not found: {path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
