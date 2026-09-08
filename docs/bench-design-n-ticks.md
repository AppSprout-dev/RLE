# RLE bench design — N × ticks (QA → stats)

How we get from a working harness to a number we can defend. **Do not
conflate the stages.** This memo does not change CLI defaults, authorize a
matrix, or spend XAI.

## Four stages

| Stage | Question | Typical shape |
|-------|----------|---------------|
| **Harness QA** | Do writes, schema, and tooling work? | N=1, 10 ticks, cheap Flash cell |
| **Variance pilot** | What is within-cell σ? | N=8–10 seeds, 10 ticks, 1–2 keeper cells |
| **Horizon sweep** | Which tick count stops censoring the metrics we care about? | one cheap cell, N=3 × {10, 25, 50, 100} ticks; **25 locked** (2026-09-08) |
| **Publishable compare** | Can we detect a chosen δ? | size *after* σ + horizon; paired same-seed sets; **25-tick** default short horizon |

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

**25-tick is the default short horizon** for composite / harness compare
(2026-09-08 sweep). 100 ticks is not preferred.

## Locked sequence

1. **Finish gate N=1s.** 10 ticks is OK. Prove schema and write paths
   (including rejects that are availability, not bugs). Fold results
   below; leftover unexercised paths stay QA, not stats.
2. **Variance pilot.** N=8–10 seeds, 10 ticks, 1–2 keeper cells. Estimate
   σ. Stop if σ is unusable or the cell is still on fire.
3. **Horizon sweep.** One cheap cell, N=3 × {10, 25, 50, 100} ticks.
   Pick the **shortest** horizon where the metrics we care about are not
   mostly censored (neutral 0.5 / no event / no research tree, etc.).
   **Done 2026-09-08: 25 ticks is the chosen short horizon.**
4. **Only then size the matrix.** Per cell,
   `n ≈ 16 σ²/δ²` (80% power, α=0.05). Prefer **paired same-seed sets**
   across harnesses. Do not copy N=4 folklore.

## Cost

Flash cells run about **$0.02–$0.90**. Do not incinerate budget on a full
harness × model × scenario matrix before σ and horizon are known. Size
the expensive cells after the cheap ones have spoken.

## Horizon lock (2026-09-08)

Sweep: one cheap cell, N=3 × {10, 25, 50, 100} ticks. Mean composites:

| Horizon | Mean composite |
|---------|----------------|
| t25 | **0.816** |
| t50 | 0.806 |
| t100 | 0.744 |
| t10 (σ baseline, same three seeds) | ~0.796 |

**Lock 25-tick** as the default short horizon for composite / harness
compare. It is the shortest sweep point that holds (and slightly beats)
the t10 baseline composite.

**100 ticks degrades** composite on average (0.744 vs 0.816 at t25). It
is not the preferred compare horizon.

**Research stays floored at 0.226** at t10 / t25 / t50 / t100. Horizon
alone does not unlock research. That is separate tooling / scenario
work, not a reason to buy longer cells.

**Force-pause re-prompt storm** at 50 / 100:
`Dialog_NamePlayerFactionAndSettlement` dismiss counts rose sharply
(t25: 0; t50: 27–40; t100: 41–80 per run). Auto-dismiss works, but
longer horizons thrash the pause queue.

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
