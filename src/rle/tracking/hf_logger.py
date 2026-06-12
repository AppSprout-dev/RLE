"""HuggingFace Hub integration for sharing benchmark results.

The dataset card (README.md) doubles as a public leaderboard: it is
regenerated from leaderboard.json on every push, so the Hub page always
shows the latest spread. Auth comes from RLEConfig.hf_token (HF_TOKEN in
.env) — pydantic-settings loads .env into the config object, not
os.environ, so the token must be passed explicitly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_REPO_ID = "AppSprout/rle-benchmarks"

# Spread run dirs mix text artifacts with capture leftovers; only the
# analysis-grade text formats belong on the Hub.
SPREAD_ALLOW_PATTERNS = ["**/*.json", "**/*.jsonl", "**/*.csv", "**/*.md", "**/*.ts"]

_CARD_HEADER = """---
license: mit
pretty_name: RLE — RimWorld Learning Environment Benchmarks
tags:
- benchmark
- multi-agent
- agents
- llm
- rimworld
- game
---

# RLE — RimWorld Learning Environment Benchmarks

Can 7 role-specialized LLM agents keep a RimWorld colony alive? RLE is a
multi-agent coordination benchmark: MapAnalyst + 6 domain agents
(resources, defense, research, social, construction, medical) manage a
live colony through a REST API, scored on a 10-metric weighted composite
against a no-agent baseline (RimWorld's built-in pawn AI, static
4-seed reference).

- Site + featured runs: https://rle.appsprout.dev
- Harness: https://github.com/AppSprout-dev/RLE
"""


def build_dataset_card(board: dict[str, Any], date: str) -> str:
    """Render the dataset card README from a spread's leaderboard.json.

    Pure function — testable without the Hub. Costs prefer the billed
    OpenRouter ground truth (``real_cost_usd``); estimates are marked
    with ``~`` (subscription-billed models have no metered ground truth).
    """
    baseline = board.get("baseline", {})
    rows: list[dict[str, Any]] = board.get("rows", [])

    lines = [
        _CARD_HEADER,
        f"## Latest spread — {date} (N=1, seed 42, Crashlanded)",
        "",
        "Ranked by mean composite over the run. N=1 is content-first, not",
        "statistically valid — no confidence intervals. Winners advance to N=4.",
        f"Baseline: no-agent, {baseline.get('n_runs', '?')} seeds, mean "
        f"time-to-end {baseline.get('mean_time_to_end_days', '?')} days.",
        "",
        "| # | model | mean | final | vs baseline | ticks > base | action ok | cost |",
        "|---|-------|------|-------|-------------|--------------|-----------|------|",
    ]
    for i, r in enumerate(rows, 1):
        real = r.get("real_cost_usd")
        cost = f"${real:.2f}" if real is not None else f"~${r.get('est_cost_usd', 0):.2f}"
        lines.append(
            f"| {i} | {r['model']} | {r['mean_composite']:.3f} "
            f"| {r['final_composite']:.3f} | {r['vs_baseline_mean_delta']:+.3f} "
            f"| {r['ticks_above_baseline']} | {r['raw_action_success']:.0%} | {cost} |"
        )

    above = [r for r in rows if r.get("vs_baseline_mean_delta", 0) > 0]
    lines += [
        "",
        f"**{len(above)} of {len(rows)} models beat the no-agent baseline.**"
        + (
            " (" + ", ".join(r["model"] for r in above) + ")"
            if above else ""
        ),
        "",
        "## Layout",
        "",
        "- `benchmark_history.jsonl` — every tracked run (one JSON object per line)",
        "- `baseline/` — the static no-agent reference runs (per-seed CSV + summary)",
        "- `runs/spread-<date>/` — per-model artifacts: summary JSON, per-tick CSV,",
        "  structured event log, full deliberation transcripts, `leaderboard.json`,",
        "  `site/site_data.json` (website payload)",
        "",
        "Costs marked `~` are token-count estimates (subscription-billed models);",
        "unmarked costs are OpenRouter billed ground truth.",
        "",
    ]
    return "\n".join(lines)


class HFLogger:
    """Pushes benchmark results to a HuggingFace dataset repo.

    All methods are no-ops if huggingface-hub is not installed or auth fails.
    """

    def __init__(
        self,
        repo_id: str = DEFAULT_REPO_ID,
        enabled: bool = True,
        token: str | None = None,
    ) -> None:
        self._api = None
        self._repo_id = repo_id
        self._token = token
        if not enabled:
            return
        try:
            from huggingface_hub import HfApi

            self._api = HfApi(token=token)
            # Verify auth
            self._api.whoami()
        except ImportError:
            logger.info("huggingface-hub not installed — HF push disabled")
        except Exception:
            logger.warning("HuggingFace auth failed — HF push disabled", exc_info=True)
            self._api = None

    @property
    def enabled(self) -> bool:
        return self._api is not None

    def _ensure_repo(self) -> None:
        assert self._api is not None
        self._api.create_repo(self._repo_id, repo_type="dataset", exist_ok=True)

    def push_card(self, content: str) -> None:
        """Upload the dataset card (README.md) — the public leaderboard."""
        if not self._api:
            return
        try:
            self._ensure_repo()
            self._api.upload_file(
                path_or_fileobj=content.encode("utf-8"),
                path_in_repo="README.md",
                repo_id=self._repo_id,
                repo_type="dataset",
                commit_message="Update dataset card / leaderboard",
            )
            logger.info("Pushed dataset card to %s", self._repo_id)
        except Exception:
            logger.warning("HuggingFace card push failed", exc_info=True)

    def push_spread(self, spread_dir: Path, date: str) -> None:
        """Upload a spread run dir to runs/spread-<date>/ (text artifacts only)."""
        if not self._api:
            return
        try:
            self._ensure_repo()
            self._api.upload_folder(
                folder_path=str(spread_dir),
                path_in_repo=f"runs/spread-{date}",
                repo_id=self._repo_id,
                repo_type="dataset",
                allow_patterns=SPREAD_ALLOW_PATTERNS,
                commit_message=f"Add spread run: {date}",
            )
            logger.info("Pushed spread %s to %s", date, self._repo_id)
        except Exception:
            logger.warning("HuggingFace spread push failed", exc_info=True)

    def push_results(
        self,
        history_path: Path | None = None,
        baselines_dir: Path | None = None,
        run_dir: Path | None = None,
    ) -> None:
        """Push benchmark artifacts to the HuggingFace dataset repo."""
        if not self._api:
            return

        try:
            self._ensure_repo()

            # Push history JSONL
            if history_path and history_path.exists():
                self._api.upload_file(
                    path_or_fileobj=str(history_path),
                    path_in_repo="benchmark_history.jsonl",
                    repo_id=self._repo_id,
                    repo_type="dataset",
                    commit_message="Update benchmark history",
                )
                logger.info("Pushed benchmark_history.jsonl to %s", self._repo_id)

            # Push baselines (static no-agent reference)
            if baselines_dir and baselines_dir.exists():
                self._api.upload_folder(
                    folder_path=str(baselines_dir),
                    path_in_repo="baseline",
                    repo_id=self._repo_id,
                    repo_type="dataset",
                    allow_patterns=SPREAD_ALLOW_PATTERNS,
                    commit_message="Update no-agent baseline",
                )
                logger.info("Pushed baseline to %s", self._repo_id)

            # Push latest run artifacts
            if run_dir and run_dir.exists():
                self._api.upload_folder(
                    folder_path=str(run_dir),
                    path_in_repo=f"runs/{run_dir.name}",
                    repo_id=self._repo_id,
                    repo_type="dataset",
                    allow_patterns=SPREAD_ALLOW_PATTERNS,
                    commit_message=f"Add run: {run_dir.name}",
                )
                logger.info("Pushed run %s to %s", run_dir.name, self._repo_id)

        except Exception:
            logger.warning("HuggingFace push failed", exc_info=True)
