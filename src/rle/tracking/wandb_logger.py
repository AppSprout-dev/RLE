"""W&B integration for RLE benchmarks. Gracefully degrades if wandb not installed."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WandBLogger:
    """Logs benchmark metrics and agent traces to Weights & Biases.

    All methods are no-ops if wandb is not installed or init fails.
    """

    def __init__(
        self,
        project: str = "rle",
        entity: str = "appsprout",
        enabled: bool = True,
        run_name: str | None = None,
    ) -> None:
        self._run = None
        self._wandb = None
        self._step = 0
        if not enabled:
            return
        try:
            import wandb

            self._wandb = wandb
            self._run = wandb.init(
                project=project,
                entity=entity,
                name=run_name,
                reinit=True,
            )
        except ImportError:
            logger.info("wandb not installed — tracking disabled")
        except Exception:
            logger.warning("wandb init failed — tracking disabled", exc_info=True)

    @property
    def enabled(self) -> bool:
        return self._run is not None

    def log_config(self, config: dict[str, Any]) -> None:
        """Log run configuration (model, provider, git commit, etc.)."""
        if not self._run:
            return
        self._run.config.update(config)

    def log_tick(
        self,
        tick: int,
        metrics: dict[str, float],
        composite: float,
        execution: dict[str, int] | None = None,
    ) -> None:
        """Log per-tick metrics as step data."""
        if not self._run:
            return
        data: dict[str, Any] = {"tick": tick, "metrics/composite": composite}
        for name, value in metrics.items():
            data[f"metrics/{name}"] = value
        if execution:
            for name, value in execution.items():
                data[f"execution/{name}"] = value
        self._run.log(data, step=self._step)
        self._step += 1

    def log_deliberation(
        self, tick: int, agent: str, data: dict[str, Any],
    ) -> None:
        """Log a single agent deliberation."""
        if not self._run:
            return
        self._run.log(
            {
                f"agents/{agent}/confidence": data.get("confidence", 0),
                f"agents/{agent}/num_actions": data.get("num_actions", 0),
                f"agents/{agent}/status": data.get("status", "unknown"),
            },
            step=self._step - 1,  # Same step as the tick
        )

    def log_scenario_result(self, result: dict[str, Any]) -> None:
        """Log a completed scenario's summary."""
        if not self._run:
            return
        name = result.get("name", "unknown").replace(" ", "_").lower()
        self._run.summary[f"scenario/{name}/score"] = result.get("score", 0)
        self._run.summary[f"scenario/{name}/outcome"] = result.get("outcome", "")
        self._run.summary[f"scenario/{name}/parse_rate"] = result.get("parse_rate", 0)
        self._run.summary[f"scenario/{name}/sec_per_tick"] = result.get("sec_per_tick", 0)

    def log_final_summary(self, avg_score: float, parse_rate: float, total_time: float) -> None:
        """Log aggregate benchmark summary."""
        if not self._run:
            return
        self._run.summary["avg_score"] = avg_score
        self._run.summary["parse_rate"] = parse_rate
        self._run.summary["total_time_s"] = total_time

    def finish(self) -> None:
        """Finalize the W&B run."""
        if self._run:
            self._run.finish()
            self._run = None
