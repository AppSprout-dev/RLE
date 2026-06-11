# Changelog

## 0.1.0 (2026-06-11)

First tagged release. RLE is a multi-agent benchmark where 7 Felix Agent SDK
role-specialized LLM agents manage a RimWorld colony — multi-agent coordination
under uncertainty.

### Features

* **7-agent architecture** — MapAnalyst (spatial, runs first) + ResourceManager,
  DefenseCommander, ResearchDirector, SocialOverseer, ConstructionPlanner,
  MedicalOfficer, coordinating through Felix CentralPost hub-spoke.
* **Deterministic spatial analysis** — MAP_SUMMARY with verified build/farm/stockpile
  coordinates injected into every agent; agents may not invent coordinates.
* **6 scenarios** — Crashlanded, First Winter, Toxic Fallout, Raid Defense,
  Plague Response, Ship Launch, each with victory/failure conditions and weight overrides.
* **10-metric weighted composite scoring** with bootstrap confidence intervals and
  per-tick CSV export.
* **Provider-agnostic** via felix-agent-sdk 0.3.0 native async — local (LM Studio),
  OpenRouter, Anthropic, OpenAI, and the claude-code subscription provider.
* **RIMAPI integration** — async REST client + SSE event stream (raids, deaths,
  mental breaks injected into agent context).
* **Pinned no-agent baseline** — N=4, colony dead by day 8, committed as a provenance
  sidecar; every agent run is measured against it.
* **Helix phase adaptation** — exploration → analysis → synthesis as the colony progresses.
* **Docker headless mode**, React dashboard with 5 RLE widgets, W&B/HuggingFace loggers.
* **Post-run analysis & media toolkit** — cross-model leaderboard, story mining, footage
  indexing, and the `/run-analysis` skill.

### Notes

* First public benchmark data: a 6-model spread (Crashlanded, N=1 content-first).
  Grok 4.3 led on mean composite; full caveats in the README.
* 458 tests, mypy strict, ruff clean.
