# ADR-003: Automated Benchmark Infrastructure

**Date:** 2026-04-09
**Status:** Accepted
**Deciders:** @jkbennitt, @calebisgross

## Decision

Replace mock benchmarks with Docker-containerized HeadlessRim for real automated game sessions. Expand scoring from 8 to 10 metrics (adding coordination + communication_efficiency). Add bootstrap confidence intervals, real-time cost tracking via OpenRouter API, and structured event logging for full decision trace observability.

## Context

Current `--dry-run` benchmarks test JSON parse rate against static mock data — zero signal about colony management quality. The mock state never changes (3 colonists, 8000 wealth, flat metrics every tick). The leaderboard vision (#8) requires 6 scenarios × N models × 4+ runs = hundreds of automated game sessions. This is impossible manually.

IlyaChichkov confirmed RIMAPI works headlessly (HeadlessRim#1, 2026-03-22) and published HeadlessRimPatch v1.0.0 the same day. The patch strips Unity UI/rendering via Harmony, enabling RimWorld to run in Docker with Xvfb.

Industry research (FLE/NeurIPS 2025, SWE-bench, ARC-AGI-2, WebArena, Chatbot Arena, M3-Bench) identified patterns we adopt:

- Docker isolation for reproducibility (SWE-bench, FLE)
- Bootstrap confidence intervals (14/24 major benchmarks skip this per BetterBench 2024)
- Cost-per-task metrics (ARC-AGI-2's key innovation: accuracy without cost is meaningless)
- Process-aware evaluation (M3-Bench: score HOW agents coordinate, not just outcomes)
- RimWorld's stochastic events provide built-in contamination resistance

## Decision Drivers

- `--dry-run` produces zero signal — agents always score 0.706 on static data
- No benchmark without a live game, no live game automation without Docker
- Multi-model leaderboard requires 96+ automated game sessions (6 scenarios × 4 models × 4 runs)
- Process metrics (coordination, communication) differentiate RLE from single-agent benchmarks
- Cost tracking enables ARC-AGI-2-style accuracy-vs-cost Pareto frontiers

## What Changes

### 1. Docker infrastructure (HeadlessRim + HeadlessRimPatch + RIMAPI)

Docker container runs headless RimWorld with RIMAPI on :8765. Game files mounted at runtime (not baked in) to avoid distributing copyrighted content. Entrypoint: Xvfb → RimWorldLinux → HeadlessRimPatch auto-starts game → RIMAPI serves → we load benchmark save via REST.

### 2. Scoring: 8 → 10 metrics with process awareness

Two new metrics folded into the composite score:
- `coordination`: conflicts resolved / total conflicts (from ActionResolver)
- `communication_efficiency`: messages acted on / total messages sent

Process metrics get 20% combined weight. No historical data to protect (pre-release). All 6 scenario YAMLs updated.

### 3. Bootstrap confidence intervals (stdlib-only)

We evaluated `resample` (scikit-hep, best modern option) but it pulls in scipy (~150MB) + numpy (~50MB). For percentile bootstrap CIs and Welch's t-test at N≥4, stdlib `random.choices()` + `math` is mathematically correct and keeps the install lightweight. The existing hand-rolled Welch's t-test in `delta.py` uses a normal CDF approximation (Abramowitz & Stegun) documented as "very accurate for df > 30, approximate for smaller df." Our N≥4 minimum guarantees sufficient accuracy.

If we later need BCa intervals or power analysis, we upgrade to scipy — the `BootstrapCI` pydantic model API won't change.

### 4. Cost tracking via OpenRouter API

Real-time per-token pricing from `GET https://openrouter.ai/api/v1/models` (public, no auth). Works for all providers (Anthropic, OpenAI, Meta, etc.) since OpenRouter lists every model. Graceful fallback to $0.00 if unreachable. Cached per benchmark run.

### 5. Structured event log (dual observability)

Append-only JSONL capturing every event: deliberations (raw LLM output + parsed plan), conflicts, action executions (RIMAPI call + response), scores, errors. This is the offline source of truth.

W&B Weave provides optional rich LLM trace visualization on top — same events, interactive UI. Graceful degradation if wandb not installed.

### 6. N≥4 enforcement for leaderboard submissions

`--push-hf` requires `--runs 4` or higher. Warning printed for N < 4. Bootstrap CIs require multiple runs to be meaningful.

## Alternatives Rejected

1. **Keep mock benchmarks** — zero signal about colony management quality.
2. **Build simulation mode with advancing fake state** — we'd be building a fake RimWorld engine. The real game has 156+ interacting systems.
3. **Manual live runs only** — doesn't scale beyond 2 models, no CI integration, no reproducibility.
4. **scipy/numpy for statistics** — `resample` package requires scipy (~150MB) + numpy (~50MB). Percentile bootstrap with stdlib is mathematically correct for our N≥4 use case and keeps install under 5 seconds.

## Consequences

**Positive:**
- Real benchmarks with real game state that changes per tick
- Multi-model leaderboard becomes automatable (Docker + CI)
- Process metrics differentiate RLE from all existing benchmarks
- Cost-normalized rankings prevent "just throw more compute at it" gaming
- Full decision traces enable post-hoc analysis of model behavior
- Bootstrap CIs give credible statistical comparisons

**Negative:**
- Linux RimWorld game files required for Docker (via SteamCMD)
- Historical mock benchmark data invalidated (acceptable: pre-release)
- Docker image size (~2GB with game files mounted)
- OpenRouter API dependency for cost tracking (graceful fallback)

**Risks:**
- RIMAPI IPv6 binding in Docker — may need config for port forwarding. Test early.
- HeadlessRimPatch `SetupForQuickTestPlay()` creates a throwaway map before we load our save — wasted startup time. Feature request filed (HeadlessRimPatch#5).
- Small models may struggle with 10 metrics in scoring — mitigated by per-scenario weight overrides.

## Related

- Issue #13: HeadlessRim Docker — real automated benchmarks + leaderboard infrastructure
- Issue #8: RLE v1.0 multi-model colony management leaderboard
- Issue #6: Agents must beat unmanaged baseline
- HeadlessRim#1: RIMAPI compatibility confirmed
- HeadlessRimPatch#5: Feature request for direct save loading
