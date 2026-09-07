# RLE bench design — N × ticks (QA → stats)

How we get from a working harness to a number we can defend. **Do not
conflate the stages.** This memo does not change CLI defaults, authorize a
matrix, or spend XAI.

## Four stages

| Stage | Question | Typical shape |
|-------|----------|---------------|
| **Harness QA** | Do writes, schema, and tooling work? | N=1, 10 ticks, cheap Flash cell |
| **Variance pilot** | What is within-cell σ? | N=8–10 seeds, 10 ticks, 1–2 keeper cells |
| **Horizon sweep** | Which tick count stops censoring the metrics we care about? | one cheap cell, N=3 × {10, 25, 50, 100} ticks |
| **Publishable compare** | Can we detect a chosen δ? | size *after* σ + horizon; paired same-seed sets |

A gate score is not σ. A 10-tick leaderboard is not a horizon. N=4 without
σ is not a compare.

## Current fact (scoring 1.2)

Almost every published scoring-1.2 cell is **seed 42, N=1** (see
`spread-2026-09-06`). One observation per cell ⇒ **no within-cell σ**.
Declaring “significance” without σ is theater.

The live board already labels N=1 as content-first / not statistically
valid. “Winners advance to N=4” is still not a substitute for measuring
variance first.

## Jason lock

**10-tick is software / harness validation first.** Longer horizon only
after the tooling is trustworthy. Do not buy 50- or 100-tick cells to
“see more game” while gates still miss write paths.

## Locked sequence

1. **Finish gate N=1s.** 10 ticks is OK. Prove schema and write paths
   (including rejects that are availability, not bugs). Fold results
   below; leftover unexercised paths stay QA, not stats.
2. **Variance pilot.** N=8–10 seeds, 10 ticks, 1–2 keeper cells. Estimate
   σ. Stop if σ is unusable or the cell is still on fire.
3. **Horizon sweep.** One cheap cell, N=3 × {10, 25, 50, 100} ticks.
   Pick the **shortest** horizon where the metrics we care about are not
   mostly censored (neutral 0.5 / no event / no research tree, etc.).
4. **Only then size the matrix.** Per cell,
   `n ≈ 16 σ²/δ²` (80% power, α=0.05). Prefer **paired same-seed sets**
   across harnesses. Do not copy N=4 folklore.

## Cost

Flash cells run about **$0.02–$0.90**. Do not incinerate budget on a full
harness × model × scenario matrix before σ and horizon are known. Size
the expensive cells after the cheap ones have spoken.

## Gate fold (2026-09-07)

Both cells: `opencode` × `deepseek-v4-flash`, ~$0.025 console. Pin
`f818246e` @ `41fd015`. These are **QA**, not σ.

| | Val N=1 | Gates2 N=1 |
|--|---------|------------|
| Seed | 42 | **314159** (+ short research/tend bias) |
| Score | **0.7073** | **0.6803** |
| Proved | check-zone; work-priority schema | work-priority **6× pass**; doctor+patient **9× tend pass** |
| Research | unexercised | availability **4× unavailable rejects** (no bench / prereqs) |
| Tend | unexercised | 9× pass (see above) |
| Farm already-covered | — | branch not hit |
| Stockpile-delete | not exercised | not exercised |

Val proved check-zone + work-priority schema. Gates2 proved work-priority
repeats and tend; research rejects were **no bench / prereqs**, not a
schema miss. Stockpile-delete and the farm already-covered branch are
still open QA.
