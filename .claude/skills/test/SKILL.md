---
name: test
description: Run full test suite and lint
allowed-tools: Bash
---

Run the full test suite and lint check:

1. `python -m pytest tests/ -v`
2. `ruff check src/ tests/ scripts/`

Report results. If anything fails, diagnose and fix.
