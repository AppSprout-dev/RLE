"""Time-series recording of score snapshots with CSV export."""

from __future__ import annotations

import csv
from pathlib import Path

from rle.scoring.composite import ScoreSnapshot
from rle.scoring.metrics import ALL_METRICS


class TimeSeriesRecorder:
    """Records ScoreSnapshots and exports to CSV."""

    def __init__(self) -> None:
        self._snapshots: list[ScoreSnapshot] = []

    def record(self, snapshot: ScoreSnapshot) -> None:
        self._snapshots.append(snapshot)

    def to_csv(self, path: str | Path) -> None:
        """Export snapshots as CSV."""
        metric_names = sorted(ALL_METRICS.keys())
        fieldnames = ["tick", "day"] + metric_names + ["composite"]

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for snap in self._snapshots:
                row: dict[str, object] = {"tick": snap.tick, "day": snap.day}
                for name in metric_names:
                    row[name] = round(snap.metrics.get(name, 0.0), 4)
                row["composite"] = round(snap.composite, 4)
                writer.writerow(row)

    def to_dicts(self) -> list[dict]:
        """Return list of dicts for programmatic access."""
        return [
            {"tick": s.tick, "day": s.day, **s.metrics, "composite": s.composite}
            for s in self._snapshots
        ]

    @property
    def snapshots(self) -> list[ScoreSnapshot]:
        return list(self._snapshots)
