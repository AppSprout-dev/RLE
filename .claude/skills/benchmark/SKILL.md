---
name: benchmark
description: Run the full RLE benchmark suite (6 scenarios)
allowed-tools: Bash, Read
argument-hint: [--ticks N] [--dry-run] [--sequential]
---

Run the RLE benchmark. Read `.env` for OPENROUTER_API_KEY. Default: OpenRouter with Nemotron 120B, 10 ticks, parallel, no-think.

```bash
OPENAI_API_KEY=<key from .env> python scripts/run_benchmark.py \
  --provider openai \
  --model nvidia/nemotron-3-super-120b-a12b \
  --base-url https://openrouter.ai/api/v1 \
  --no-think --visualize \
  --output results/benchmark-latest/ \
  $ARGUMENTS
```

When complete, show the leaderboard and ask if results should be posted to a GitHub issue.
