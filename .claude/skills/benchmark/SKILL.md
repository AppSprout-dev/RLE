---
name: benchmark
description: Run the full RLE benchmark suite (6 scenarios)
allowed-tools: Bash, Read
argument-hint: "--ticks N --smoke-test --docker --runs N --sequential"
---

Run the RLE benchmark using provider/model from `.env`. Read `.env` first to determine the configuration.

```bash
# .env has PROVIDER, MODEL, PROVIDER_BASE_URL, OPENAI_API_KEY
source .env 2>/dev/null
python scripts/run_benchmark.py \
  --no-think --visualize \
  --output results/benchmark-latest/ \
  $ARGUMENTS
```

If `.env` isn't configured or user specifies a provider, override with CLI flags:
```bash
python scripts/run_benchmark.py \
  --provider openai \
  --model <model> \
  --base-url <url> \
  --no-think --visualize \
  --output results/benchmark-latest/ \
  $ARGUMENTS
```

Key flags:
- `--smoke-test` — Mock RIMAPI (no game needed)
- `--docker` — Use headless RimWorld container
- `--runs N` — Paired runs for statistical validity (N>=4 for leaderboard)
- `--no-baseline` — Skip baseline comparison

When complete, show the leaderboard and ask if results should be posted to a GitHub issue.
