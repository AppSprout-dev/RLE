"""Local JSONL history + baselines for benchmark tracking."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

RESULTS_DIR = Path("results")
HISTORY_PATH = RESULTS_DIR / "benchmark_history.jsonl"
BASELINES_DIR = RESULTS_DIR / "baselines"


def get_run_dir(model: str | None = None) -> Path:
    """Generate a timestamped run directory path."""
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M")
    model_short = re.sub(r"[^\w\-]", "", (model or "default").split("/")[-1])[:20]
    run_dir = RESULTS_DIR / "runs" / f"{ts}_{model_short}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def append_history(summary: dict[str, object]) -> Path:
    """Append a benchmark summary as one JSONL line. Returns the history path."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a") as f:
        f.write(json.dumps(summary, default=str) + "\n")
    return HISTORY_PATH


def load_history() -> list[dict[str, object]]:
    """Load all historical benchmark runs from JSONL."""
    if not HISTORY_PATH.exists():
        return []
    runs = []
    for line in HISTORY_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            runs.append(json.loads(line))
    return runs


def update_baseline(summary: dict[str, Any]) -> tuple[bool, float | None]:
    """Update baseline if this run's avg score is a new best for the model.

    Returns (is_new_best, previous_score_or_None).
    """
    BASELINES_DIR.mkdir(parents=True, exist_ok=True)
    model = summary.get("model", "unknown")
    slug = re.sub(r"[^\w\-]", "_", model)
    baseline_path = BASELINES_DIR / f"{slug}.json"

    scenarios = summary.get("scenarios", [])
    if not scenarios:
        return False, None
    avg_score = sum(s.get("score", 0) for s in scenarios) / len(scenarios)

    prev_score = None
    if baseline_path.exists():
        prev = json.loads(baseline_path.read_text())
        prev_score = prev.get("avg_score", 0.0)
        if avg_score <= prev_score:
            return False, prev_score

    baseline = {
        "model": model,
        "avg_score": round(avg_score, 4),
        "timestamp": summary.get("timestamp", ""),
        "git_commit": summary.get("git_commit", ""),
        "scenarios": scenarios,
    }
    baseline_path.write_text(json.dumps(baseline, indent=2, default=str))
    return True, prev_score
