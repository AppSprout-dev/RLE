"""HuggingFace Hub integration for sharing benchmark results."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class HFLogger:
    """Pushes benchmark results to a HuggingFace dataset repo.

    All methods are no-ops if huggingface-hub is not installed or auth fails.
    """

    def __init__(
        self,
        repo_id: str = "appsprout/rle-benchmarks",
        enabled: bool = True,
    ) -> None:
        self._api = None
        self._repo_id = repo_id
        if not enabled:
            return
        try:
            from huggingface_hub import HfApi

            self._api = HfApi()
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
            # Ensure repo exists
            self._api.create_repo(
                self._repo_id, repo_type="dataset", exist_ok=True,
            )

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

            # Push baselines
            if baselines_dir and baselines_dir.exists():
                for f in baselines_dir.glob("*.json"):
                    self._api.upload_file(
                        path_or_fileobj=str(f),
                        path_in_repo=f"baselines/{f.name}",
                        repo_id=self._repo_id,
                        repo_type="dataset",
                        commit_message=f"Update baseline: {f.stem}",
                    )
                logger.info("Pushed baselines to %s", self._repo_id)

            # Push latest run artifacts
            if run_dir and run_dir.exists():
                self._api.upload_folder(
                    folder_path=str(run_dir),
                    path_in_repo=f"runs/{run_dir.name}",
                    repo_id=self._repo_id,
                    repo_type="dataset",
                    commit_message=f"Add run: {run_dir.name}",
                )
                logger.info("Pushed run %s to %s", run_dir.name, self._repo_id)

        except Exception:
            logger.warning("HuggingFace push failed", exc_info=True)
