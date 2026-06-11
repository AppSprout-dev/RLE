# Changelog

## [0.2.0](https://github.com/AppSprout-dev/RLE/compare/rimworld-learning-environment-v0.1.0...rimworld-learning-environment-v0.2.0) (2026-06-11)


### Features

* reasoning-token costs, growing-zone overlap guard, auto-dismiss dialogs, camera director ([#33](https://github.com/AppSprout-dev/RLE/issues/33), [#34](https://github.com/AppSprout-dev/RLE/issues/34)) ([c48b408](https://github.com/AppSprout-dev/RLE/commit/c48b408ffff5d89a17f14a9130c100dbc600aa1c))
* reasoning-token costs, growing-zone overlap guard, auto-dismiss dialogs, camera director ([#33](https://github.com/AppSprout-dev/RLE/issues/33), [#34](https://github.com/AppSprout-dev/RLE/issues/34)) ([563f976](https://github.com/AppSprout-dev/RLE/commit/563f97698a78f84a52d1c1fe977300164676ab76))

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
