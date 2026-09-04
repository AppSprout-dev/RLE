# ADR-004: Swappable harnesses (harness x model benchmark)

**Date:** 2026-09-04
**Status:** Accepted
**Deciders:** @jkbennitt
**Tracks:** #51 (scoring 1.2), #6, #8, #46

## Decision

Make the *harness* — the machinery that turns colony state into actions each
tick — a first-class benchmark variable, swappable from the CLI exactly like
the model. RLE core becomes a framework-free environment; the original Felix
7-agent stack becomes one harness among several, behind an optional extra.
Harnesses are discovered through the `rle.harnesses` entry-point group;
harnesses that wrap third-party tools live in their own repositories.

## Context

RLE was built around one harness before "harness" was a common term: seven
Felix SDK role agents over a CentralPost hub, merged by a conflict resolver.
Only the model behind that stack could be swapped. Two consequences:

1. **Scientific:** the benchmark could not answer whether the multi-agent
   design itself helps. There was no way to run the same model under a
   different decision architecture on the same scenarios and saves.
2. **Structural:** `felix-agent-sdk` was a core dependency imported by the
   game loop, config, scripts and tracking. Two of the ten composite metrics
   (`coordination`, `communication_efficiency`) read CentralPost / resolver
   counters — Felix-shaped by construction and, it turned out, ≈1.0 in every
   run (issue #51).

Meanwhile, capable open-source coding agents (OpenCode, Grok Build, ...) ship
headless modes and native MCP support. They are harnesses in the same sense,
and the interesting benchmark question is *harness x model*.

## What changes

### Harness protocol (`rle.harness`)

`RLEGameLoop` owns only the environment: pause, state refresh, execution,
scoring, evaluation, export. Each tick it calls `harness.step(state, tick,
macro_time, events) -> StepResult`. `StepResult.plan` is executed by the loop;
a harness that already applied its writes during its turn (tool-using coding
agents) returns `StepResult.execution` and the loop scores that instead.
`on_tick_end` delivers execution results and the score back to the harness.
`HarnessStepError` and a loop-level `tick_timeout_s` degrade to an empty,
scored tick rather than aborting the run.

`FelixHarness` receives everything Felix-specific verbatim from the old loop
(hub/spoke wiring, MapAnalyst-first deliberation, per-agent timeouts, phase
and score broadcasts, helix visualiser, generation-id accounting).
`BaselineHarness` is the unmanaged colony. Legacy `RLEGameLoop(agents=...,
no_agent=...)` calls still work through `rle.harness.compat`.

### Registry = entry points

```toml
[project.entry-points."rle.harnesses"]
baseline = "rle.harness.baseline:PLUGIN"
felix    = "rle.harness.felix:PLUGIN"
```

Built-ins and third-party packages register identically. A plugin exposes
`available()`, `option_schema()` (pydantic, validated from `--harness-opt
key=value`), `create()`, `smoke()` (runs with no external tool or LLM) and
`describe()` (versions for run metadata). CLI: `--harness NAME`, `--harness
list`, `--harness-opt K=V`; `--no-agent` remains an alias for `--harness
baseline`; `run_benchmark.py` accepts `--harness` repeatedly for a matrix.

### Zero-Felix core

`felix-agent-sdk` is the optional `felix` extra. Role agents, `base_role` and
the claude-code provider moved under `rle.harness.felix/`; `rle.agents` keeps
only the neutral action vocabulary. `scripts/check_harness_boundary.py` and a
`test-no-felix` CI job enforce that `felix_agent_sdk` is imported nowhere else
and that no third-party harness name appears in `src/`, `tests/` or
`scripts/`. The harness-neutral scenario brief (`rle.harness.brief`: goals,
state, MAP_SUMMARY, action catalog) is what every harness receives; prompt
engineering beyond it is the harness under test.

### RimAPI as MCP

`rle.mcp` exposes one tool per `WRITE_CATALOG` entry (executed immediately
through `ActionExecutor`, recorded in a per-tick ledger), `get_brief`,
`get_state`, `rimapi_read`, `end_turn`. The harness hosts it in-process over
streamable HTTP so the agent's MCP client and the loop share one ledger.
`rle.harness.cli_base.HeadlessCliHarness` is the tool-agnostic scaffold for
CLI coding agents (turn protocol, timeouts, ledger drain, cost/latency);
`rle.testing.scripted_agent.ScriptedMcpHarness` plays a fixed tool script so
plugin CI exercises the full round trip without the binary.

### Repo boundary rule

RLE core ships only RLE-authored harnesses (`baseline`, `felix`). Harnesses
wrapping third-party tools are separate `AppSprout-dev/rle-harness-*`
packages (template, OpenCode, Grok Build). RLE CI installs the template from
GitHub as the plugin-API contract test.

### Scoring 1.2 (#51)

`coordination` and `communication_efficiency` removed; `plan_coherence`
(1 − contradictory executed writes / executed writes per tick) added.
`efficiency` and `plan_coherence` return a neutral 0.5 for ticks with no
writes so the baseline earns no free process points. Both are computed from
the writes that reached RIMAPI — the only surface every harness shares.

### Tracking

Runs record `harness`, `harness_options`, `harness_versions`
(`describe()`), per-tick `step_latency_s`, and a `harness_failed`
quarantine flag (RIMAPI null-ref / plant-def markers) that excludes a run
from leaderboard means. Leaderboard rows are keyed by harness x model with
cost and mean step latency as Pareto axes. Both CLIs use one load-and-settle
helper (`rle.orchestration.save_loader`) instead of a fixed sleep.

## Alternatives rejected

1. **Keep Felix as core, add adapters inside it.** Would keep the SDK as a
   hard dependency and leave process metrics Felix-shaped; other harnesses
   would be benchmarked through Felix's own abstractions.
2. **In-tree adapters for OpenCode / Grok Build.** Ties RLE's release cadence
   to third-party tools and grows core with every harness; the entry-point
   registry makes a package the natural unit.
3. **Buffer MCP writes and execute after the turn.** Coding agents need tool
   results inside their turn to decide the next call; immediate execution
   with a ledger is the only shape that works, so `StepResult.execution`
   exists.
4. **Fix `coordination` by counting unresolved conflicts.** Still measures a
   Felix-internal process a single-agent harness cannot have; scoring on
   executed writes is the fair common surface.

## Consequences

**Positive:** the benchmark can now attribute results to the harness, the
model, or both; adding a harness is `pip install`; core is lighter and
importable without any agent framework; process metrics discriminate.

**Negative / follow-ups:** the pinned Crashlanded baseline sidecar is stale
until recalibrated against a live game (scoring 1.2); the coding-agent
harnesses are verified against mocks and documented CLI/API surfaces, not yet
against a live colony; `helix_preset` and other Felix knobs moved from
`RLEConfig` to `--harness-opt`, which is a CLI change for existing scripts.
