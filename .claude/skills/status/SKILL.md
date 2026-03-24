---
name: status
description: Show current RLE project status
allowed-tools: Bash, Read
---

Show the full project status:

1. `git log --oneline -5` — recent commits
2. `gh issue list --state open` — open issues
3. `python -m pytest tests/ --co -q 2>&1 | tail -1` — test count
4. Check LM Studio: `curl -s http://localhost:1234/v1/models 2>&1 | head -1`
5. Check RIMAPI: `curl -s http://localhost:8765/api/v1/game/state 2>&1 | head -1`
6. Check dashboard: `curl -s http://localhost:3000 2>&1 | head -c 50`

Summarize in a clean table.
