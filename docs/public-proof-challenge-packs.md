# Public-proof challenge packs

A public RLE proof is three printed artifacts:

1. a **challenge file** (`challenge.yaml` or `challenge.yml`)
2. an **expected judgment name**
3. a **pass/fail** result of a deterministic predicate over a **printed receipt**

That is the whole proof. The receipt is one of `summary.json`, an events JSONL file, or a preflight-adapter JSON file. If those three artifacts are absent, the claim does not count.

This memo defines the pack. It does not change scoring, the game loop, or any published board number. The live cite stays `spread-2026-09-07` (Crashlanded, 10 ticks, seed 42, N=1, scoring 1.2). That board is content-first: one observation per cell, no within-cell σ. See [bench-design-n-ticks.md](bench-design-n-ticks.md).

## Chain-of-thought is not a receipt

A private chain-of-thought, an abridged `reasoning_trace` / `reasoning_traces` dump, or a narrative math writeup is a story about a run. It is not an RLE proof.

Predicates read receipt fields only. They do not read reasoning text. A receipt object that carries `reasoning_trace` or `reasoning_traces` fails closed: those keys are narrative, and packing them into the proof artifact does not satisfy a judgment. The same keys on an events line make that line ineligible. OpenAI-style abridged reasoning traces stay in that category.

## Pack shape

One directory per pack. `challenge.yaml` is the challenge. `receipts/pass/` and `receipts/fail/` hold the printed files the predicates name. Fixture packs check both directories in unit tests. A harness pack checked into the tree uses the same shape; producing the receipt still means printing `summary.json`, events, or a preflight adapter — not a transcript.

```yaml
schema_version: 1
id: research_bench_present          # matches the directory name
scenario: Crashlanded Survival      # scenarios/definitions name
seed: 42                            # RLE-side seed recorded on the summary
tick_budget: 10                     # ticks the receipt may consume
mode: fixture                       # fixture | harness
harness: fixture                    # harness name; "fixture" when mode is fixture
model: fixture                      # model id; "fixture" when mode is fixture
scoring_version: "1.2"              # SCORING_VERSION the receipt was scored under
expected:                           # judgment names only — no prose, no rates
  - research_bench_present
pass_fail:
  - judgment: research_bench_present
    receipt: preflight.json         # file under receipts/<case>/
    match: object                   # object (JSON) | any (JSONL line)
    all:
      - path: research_bench_present
        eq: true
      - path: structures.0.def_name
        eq: SimpleResearchBench
    absent:                         # top-level keys that fail the judgment
      - reasoning_trace
      - reasoning_traces
```

`mode: harness` uses the same fields with `harness` and `model` set to the pair that printed the receipt. Naming a pair records provenance. It does not add a leaderboard row and it does not authorize an N>1 matrix.

| Field | Rule |
|-------|------|
| `schema_version` | `1` |
| `id` | Directory name |
| `scenario` | Scenario `name` from YAML. These packs use `Crashlanded Survival`. |
| `seed` | Integer. Compared to `summary.json` `random_seed` when that judgment reads the summary. |
| `tick_budget` | Positive integer. `ticks_run` on a summary receipt must be ≤ this budget. |
| `mode` | `fixture` (checked-in receipts, no live game, no billed model) or `harness` (a printed run). |
| `harness`, `model` | Both `fixture` when `mode` is `fixture`. Both non-empty and not `fixture` when `mode` is `harness`. |
| `scoring_version` | `"1.2"` (`SCORING_VERSION` in `tracking/metadata.py`). |
| `expected` | List of judgment names from the catalog below. |
| `pass_fail` | One predicate per expected name. `judgment` must appear in `expected`. |

## Expected names

`expected` is a list of typed names. A name is the judgment. It is not a score, a rate, or a sentence.

| Name | What the predicate reads |
|------|--------------------------|
| `research_bench_present` | Brief flag from `research_bench_present()`: true when a structure `def_name` matches `is_research_bench_def` (`SimpleResearchBench`, `HiTechResearchBench`, and the same aliases). |
| `research_adapters` | `RimAPIClient._adapt_research` fields `current_project`, `progress`, `completed`, `available`, plus `research_target_status` (`available`, `current`, `finished`, `locked`). The failure shape is the tech-level bag the adapter refuses: `completed: ["Medieval"]`, empty `available`, status `locked`. |
| `ensure_live_save` | `LiveSaveStatus` fields `save_name`, `live_save_sha256`, `pinned_sha256`, `copied`. Pin-match: the two hashes are equal and `error` is absent. Stale AppData that cannot be staged raises `LiveSavePinError` and fails closed (`scenarios/loader.py`). |
| `stockpile_delete_quarantine` | `action_exec` event for `stockpile_delete`: `success` false and `error` containing `quarantined`. `QUARANTINED_WRITES` hides the endpoint; the executor refuses it before HTTP. |
| `preflight_contract` | The five dispatch gates in `orchestration/preflight.py`: growing-zone already covered, `work_priority` normalized to a WorkTypeDef, `research_target_status`, a resolved tend pair, and `stockpile_delete` quarantined. |
| `composite_receipt` | Per-run `summary.json` from `scripts/run_scenario.py`: `scoring_version`, `scenario`, `random_seed`, `harness`, `model`, `ticks_run`, `final_score`, `outcome`. |

Names outside this catalog are not judgments. Adding a name is a doc change plus a fixture, not a new board number.

## Pass/fail

Each predicate names one receipt file and a list of clauses. A case passes when every clause holds. `match: object` applies clauses to one JSON object. `match: any` applies them to at least one JSONL line after `where` (a map of dotted-path equalities, usually `event_type: action_exec`).

A clause has one operator:

| Operator | Holds when |
|----------|------------|
| `eq`, `ne` | The value at `path` equals / differs. |
| `lte`, `gte` | Numeric comparison. Booleans are not numbers. |
| `contains`, `not_contains` | Substring, or list membership. |
| `type` | `number`, `string`, `bool`, `list`, or `object`. |
| `present` | Path exists and is not null. |
| `absent` | Path is missing or null. On the predicate itself, `absent:` is a list of top-level keys. |
| `eq_path` | Value at `path` equals the value at another dotted path (`live_save_sha256` vs `pinned_sha256`). |

Paths are dotted. A numeric segment indexes a list (`structures.0.def_name`).

`final_score` is checked only as a number on the summary. The predicate does not compare it to a published composite. A fixture may carry any in-range shape value; that value is not a result.

## Receipts

**`summary.json`** — the object `_build_run_summary` writes (`collect_metadata` plus scenario, harness, model, `ticks_run`, `outcome`, `final_score`, `live_save_sha256`, `live_save_copied`). One file is one run.

**Events JSONL** — `Event` lines from `tracking/event_log.py` (`event_type`, `tick`, `data`). `action_exec` lines carry `action_type`, `success`, `error`, `parameters`.

**`preflight.json`** — a printed adapter or gate receipt: the research-bench flag and structure defs, the research-adapter object, a `LiveSaveStatus` / `LiveSavePinError` record, or the preflight gate fields. It is not a model transcript.

## N stays on the claim surface

Per-run `summary.json` has no `n_runs` field and no pass rate. `n_runs` exists on `BaselineReference` and `BaselinePoint` (how many no-agent runs were aggregated into the pinned baseline sidecar). A `composite_receipt` predicate rejects `n_runs` and `pass_rate` on the summary so a single receipt cannot pose as a matrix cell.

The published N=1 caveat is unchanged: `spread-2026-09-07` is one observation per cell. This packing spec does not size a matrix, does not report a new pass rate, and does not move the 25-tick horizon lock.
