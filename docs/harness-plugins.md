# Writing an RLE harness plugin

RLE benchmarks **harnesses × models**. A *model* is whatever LLM sits behind
the decisions; a *harness* is the machinery that turns game state into
actions — one agent or many, an agent framework, or a coding agent attached
over MCP. Both are swappable from the CLI:

```bash
python scripts/run_benchmark.py --harness felix    --model gpt-4o
python scripts/run_benchmark.py --harness opencode --model gpt-4o
python scripts/run_benchmark.py --harness list
```

## Repo boundary rule

RLE core ships only harnesses that are RLE-authored code: `baseline`
(unmanaged colony) and `felix` (the original 7-agent stack). **A harness that
wraps a third-party tool lives in its own repository and package**
(`rle-harness-opencode`, `rle-harness-grok-build`, ...). Nothing tool-specific
is committed to RLE core; adding a harness is `pip install`, never a core PR.

Start from the template: <https://github.com/AppSprout-dev/rle-harness-template>.

## The contract

Register a module-level `PLUGIN` object under the `rle.harnesses` entry-point
group:

```toml
# pyproject.toml of your harness package
[project]
name = "rle-harness-mytool"
dependencies = ["rimworld-learning-environment>=0.5"]

[project.entry-points."rle.harnesses"]
mytool = "rle_harness_mytool:PLUGIN"
```

`PLUGIN` implements `rle.harness.HarnessPlugin`:

| Method | Purpose |
|---|---|
| `name`, `description` | Shown by `--harness list` |
| `available() -> Availability` | Cheap probe: is the binary / extra installed? Never import heavy deps at module load. |
| `option_schema() -> type[BaseModel]` | Pydantic model validated from `--harness-opt key=value` (use `EmptyOptions` if none). |
| `create(ctx, options) -> BaseHarness` | Build the real harness. |
| `smoke(ctx, options) -> BaseHarness` | Build a variant that runs with no external tool / LLM (used by `--smoke-test` and CI). |
| `describe() -> dict[str, str]` | Versions recorded in run metadata. |

The harness itself subclasses `rle.harness.BaseHarness`:

```python
class MyHarness(BaseHarness):
    name = "mytool"

    async def setup(self, ctx: HarnessContext) -> None: ...
    async def step(self, state, tick, macro_time, events) -> StepResult: ...
    async def on_tick_end(self, tick, state, step, execution, score) -> None: ...
    async def teardown(self) -> None: ...
```

### `StepResult`

Return `StepResult(plan=ActionPlan(...))` and the loop executes the actions
through `ActionExecutor` (same normalisation and guards as Felix). If your
harness already applied its writes during the turn — the normal case for a
coding agent calling tools through the RLE MCP server — return the recorded
`ExecutionResult` in `StepResult.execution` and the loop skips execution and
scores what you report. `proposals` (per-sub-agent plans) and `extras`
(telemetry) are optional and surface in the dashboard export.

### Turn-based, always

Each tick the environment pauses the game, refreshes state, calls
`step(...)` once (bounded by `--tick-timeout` when set), executes, scores,
calls `on_tick_end(...)`, and unpauses. Coding-agent harnesses get one prompt
per tick and must return when the agent is idle; free-running sessions are
not part of v1.

### Failure semantics

Raise `HarnessStepError` for an expected failure (agent crashed, tool
unreachable). The loop logs an `ERROR` event, scores the tick with no actions,
and continues. Any other exception is treated as a bug and propagates.

## What core gives you

- `rle.harness` — `BaseHarness`, `StepResult`, `HarnessContext`,
  `HarnessPlugin`, `Availability`, `EmptyOptions`, `HarnessStepError`,
  `TickObserver`, registry helpers.
- `rle.harness.cli_base.HeadlessCliHarness` — scaffold for CLI coding agents.
  Subclass and implement three hooks: `start_agent(mcp_url)` (launch/attach
  the tool and register the RLE MCP server), `send_turn(prompt) -> TurnResult`
  (deliver one prompt, return when the agent has finished responding, with
  token counts if you have them), `stop_agent()`. The base hosts the MCP
  server in-process, builds the brief and prompt, waits for `end_turn` (or a
  short idle grace), drains the ledger into `StepResult`, applies
  `turn_timeout_s`, and records latency/cost/deliberation log. Options extend
  `HeadlessCliOptions` (`model`, `turn_timeout_s`, `idle_grace_s`,
  `extra_instructions`). Needs the `mcp` extra.
- `rle.testing.scripted_agent.ScriptedMcpHarness` — a fake coding agent that
  plays a fixed tool script through the MCP server. Return it from
  `plugin.smoke()` so your package's CI exercises the full round trip
  without the real binary.
- `rle.harness.brief` — the harness-neutral scenario brief every harness
  receives (goals, filtered state, MAP_SUMMARY, action catalog).
- `rle.mcp` — the RimAPI MCP server + per-tick write ledger (`rle-mcp`).
- `rle.testing` — `MockRimAPI` and `run_harness_smoke(plugin)`; run the
  latter in your CI:

```python
from rle.testing import run_harness_smoke

async def test_smoke() -> None:
    report = await run_harness_smoke("mytool", ticks=3)
    assert report.ok
```

## Scoring is harness-agnostic

Process metrics (`efficiency`, `plan_coherence`) are computed from the writes
that reached RIMAPI, never from a harness's internal messaging. A harness is
free to coordinate however it likes; what is scored is whether coherent,
valid writes reached the game and how the colony fared. Prompt engineering
beyond the neutral brief is part of the harness being benchmarked.

## Metadata

Every run records `harness`, `harness_options`, `harness_versions`
(`describe()` output), `model`, `provider`, `scoring_version`, and per-tick
`step_latency_s`. Leaderboards key on harness × model × scenario.
