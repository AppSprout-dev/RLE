---
name: live
description: Run RLE against a live RimWorld colony with dashboard
allowed-tools: Bash, Read
argument-hint: [scenario] [--ticks N]
---

Run a live game session. Before starting, verify prerequisites:

1. Check LM Studio: `curl -s http://localhost:1234/v1/models`
2. Check RIMAPI: `curl -s http://localhost:8765/api/v1/game/state`
3. If either is down, tell the user what to start and stop.

Then run three services:

1. **Game loop**: Read `.env` for config, run `python scripts/run_scenario.py` with `--provider openai --model` from .env, `--no-think --visualize --output results/live/ $ARGUMENTS`
2. **File server**: `python scripts/serve_dashboard.py results/live`
3. **Dashboard**: `cd c:\Users\redmo\Projects\rimapi-dashboard && bun run start`

Tell the user to open http://localhost:3000 once compiled.
