"""Push an existing spread run to the HuggingFace dataset repo.

Standalone half of the HF integration (issue #45): pushes a completed
run dir without re-running the benchmark, regenerating the dataset card
(the public leaderboard) from that run's leaderboard.json.

Usage:
    python scripts/push_hf.py --spread-dir results/spread --date 2026-06-11
    python scripts/push_hf.py --spread-dir results/spread --date 2026-06-11 --dry-run

Auth: HF_TOKEN in .env (RLEConfig). Repo: HF_DATASET_REPO or the default.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path

from rle.config import RLEConfig
from rle.tracking.hf_logger import (
    SPREAD_ALLOW_PATTERNS,
    HFLogger,
    build_dataset_card,
)


def _matching_files(folder: Path) -> list[Path]:
    """Files in folder that the push would include (mirror of allow_patterns)."""
    return sorted(
        f for f in folder.rglob("*")
        if f.is_file()
        and any(fnmatch.fnmatch(f.as_posix(), p) for p in SPREAD_ALLOW_PATTERNS)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spread-dir", type=Path, required=True,
                        help="run dir containing leaderboard.json (e.g. results/spread)")
    parser.add_argument("--date", required=True, help="run date, YYYY-MM-DD")
    parser.add_argument("--repo", default=None,
                        help="dataset repo id (default: RLEConfig.hf_dataset_repo)")
    parser.add_argument("--history", type=Path,
                        default=Path("results/benchmark_history.jsonl"))
    parser.add_argument("--baseline-dir", type=Path, default=Path("results/baseline"))
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be pushed, push nothing")
    args = parser.parse_args()

    board_path = args.spread_dir / "leaderboard.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    card = build_dataset_card(board, args.date)

    config = RLEConfig()
    repo_id = args.repo or config.hf_dataset_repo

    if args.dry_run:
        print(f"Would push to dataset: {repo_id}\n")
        print("README.md (dataset card):")
        print("  " + "\n  ".join(card.splitlines()[:6]) + "\n  ...")
        if args.history.exists():
            print(f"benchmark_history.jsonl  <- {args.history}")
        for label, folder, prefix in (
            ("baseline", args.baseline_dir, "baseline/"),
            ("spread", args.spread_dir, f"runs/spread-{args.date}/"),
        ):
            if folder.exists():
                files = _matching_files(folder)
                total_kb = sum(f.stat().st_size for f in files) / 1024
                print(f"{prefix}  <- {folder} ({len(files)} files, {total_kb:.0f} KB)")
            else:
                print(f"SKIP {label}: {folder} missing")
        return

    if not config.hf_token:
        raise SystemExit("HF_TOKEN not set in .env — cannot push.")

    hf = HFLogger(repo_id=repo_id, token=config.hf_token)
    if not hf.enabled:
        raise SystemExit("HuggingFace auth failed — check HF_TOKEN.")

    hf.push_card(card)
    hf.push_results(
        history_path=args.history if args.history.exists() else None,
        baselines_dir=args.baseline_dir if args.baseline_dir.exists() else None,
    )
    hf.push_spread(args.spread_dir, args.date)
    print(f"Pushed to https://huggingface.co/datasets/{repo_id}")


if __name__ == "__main__":
    main()
