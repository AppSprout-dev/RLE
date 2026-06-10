"""One-off chart generation for the Fable 5 launch thread.

Reads results/fable5-live-N1 artifacts and writes two PNGs next to them:
score trajectory annotated with the threat_response artifact, and the
wandering-shelter blueprint map (issue #26).
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

RUN_DIR = Path("results/fable5-live-N1")
THREAT_WEIGHT = 0.08  # crashlanded scenario override

# Blueprint rectangle origins per tick (from events.jsonl, issue #26)
SHELTER_SITES = [
    (133, 139), (133, 145), (140, 134), (147, 135), (152, 139),
    (153, 127), (156, 119), (144, 128), (145, 135), (145, 138),
]
WATER = (93, 105, 132, 185)  # approx, per DefenseCommander terrain reads


def load_scores() -> tuple[list[int], list[float], list[float]]:
    ticks, composite, threat = [], [], []
    with open(RUN_DIR / "01_crashlanded_survival.csv", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            ticks.append(i)
            composite.append(float(row["composite"]))
            threat.append(float(row["threat_response"]))
    return ticks, composite, threat


def trajectory_chart() -> None:
    ticks, composite, threat = load_scores()
    # Composite with the threat_response zeroing backed out
    ex_artifact = [c + (1.0 - t) * THREAT_WEIGHT for c, t in zip(composite, threat)]
    decay = [composite[0] - 0.013 * i for i in ticks]

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=160)
    ax.plot(ticks, composite, "o-", lw=2.5, color="#d4452c", label="Fable 5 composite (as scored)")
    ax.plot(ticks, ex_artifact, "o--", lw=2, color="#2c7fb8",
            label="Ex-artifact (threat_response bug backed out)")
    ax.plot(ticks, decay, ":", lw=1.5, color="#888888",
            label="Natural decay reference (−0.013/tick)")

    drop_tick = next(i for i, t in enumerate(threat) if t == 0.0)
    ax.annotate(
        "threat_response → 0.0\n(no raid ever existed —\n"
        "agent refused to draft, correctly.\nHarness bug, RLE issue #25)",
        xy=(drop_tick, composite[drop_tick]),
        xytext=(drop_tick - 4.4, composite[drop_tick] - 0.018),
        fontsize=9, color="#d4452c",
        arrowprops={"arrowstyle": "->", "color": "#d4452c"},
    )
    ax.set_xlabel("Tick")
    ax.set_ylabel("Composite score")
    ax.set_title("Claude Fable 5 × RimWorld Crashlanded — 10 ticks, 7 agents (RLE, seed 42)")
    ax.legend(loc="lower left", fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(RUN_DIR / "fable5_trajectory.png")


def shelter_chart() -> None:
    fig, ax = plt.subplots(figsize=(7.5, 7.5), dpi=160)
    wx1, wz1, wx2, wz2 = WATER
    ax.add_patch(Rectangle((wx1, wz1), wx2 - wx1, wz2 - wz1,
                           facecolor="#a6cee3", edgecolor="none", alpha=0.6))
    ax.text((wx1 + wx2) / 2, (wz1 + wz2) / 2, "water", ha="center",
            color="#1f6090", fontsize=10, style="italic")

    xs = [s[0] for s in SHELTER_SITES]
    zs = [s[1] for s in SHELTER_SITES]
    for i, (x, z) in enumerate(SHELTER_SITES):
        ax.add_patch(Rectangle((x, z), 7, 7, facecolor="none",
                               edgecolor="#d4452c", lw=1.4, alpha=0.85))
        ax.annotate(str(i), (x + 3.5, z + 3.5), ha="center", va="center",
                    fontsize=9, color="#d4452c", weight="bold")
    ax.plot(
        [x + 3.5 for x in xs], [z + 3.5 for z in zs],
        "--", color="#555555", lw=1, alpha=0.7,
    )

    ax.set_xlim(85, 175)
    ax.set_ylim(100, 195)
    ax.set_aspect("equal")
    ax.set_xlabel("map x")
    ax.set_ylabel("map z")
    ax.set_title(
        "The wandering shelter — one blueprint per tick, ticks 0–9\n"
        "10 sites, 10 successful placements, 0 shelters built (RLE issue #26)",
        fontsize=11,
    )
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(RUN_DIR / "fable5_wandering_shelter.png")


def quote_card() -> None:
    """Transcript card for the DefenseCommander tick-9 quote (verbatim)."""
    bg, dim, body, hot = "#0d1117", "#8b949e", "#c9d1d9", "#f0883e"
    fig = plt.figure(figsize=(7.5, 4.22), dpi=160)
    fig.patch.set_facecolor(bg)

    def t(y: float, s: str, color: str, size: int, weight: str = "normal") -> None:
        fig.text(0.06, y, s, color=color, fontsize=size, family="monospace",
                 weight=weight, va="top")

    t(0.93, "RLE · RimWorld Learning Environment — events.jsonl, verbatim", dim, 10)
    t(0.86, "agent: defense_commander (claude-fable-5)   tick: 9   confidence: 0.92", dim, 10)

    t(0.74, '"Threat assessment: the single \'threat\' entry has', body, 12)
    t(0.685, 'enemy_count=0 and threat_level=0.0 — there is no hostile', body, 12)
    t(0.63, "presence on the map. The 'ThreatBig' alert in recent events", body, 12)
    t(0.575, 'is a MENTAL BREAK warning for Bob (mood 0.22), not a raid."', body, 12)

    t(0.44, '"Drafting Bob in his current state would be', hot, 14, "bold")
    t(0.375, ' the single most dangerous \'defensive\'', hot, 14, "bold")
    t(0.31, ' action available."', hot, 14, "bold")

    t(0.14, "Our scoring zeroed threat_response for this. The agent was right.", dim, 10)
    t(0.08, "github.com/AppSprout-dev/RLE", dim, 10)

    fig.savefig(RUN_DIR / "fable5_quote_card.png", facecolor=bg)


if __name__ == "__main__":
    trajectory_chart()
    shelter_chart()
    quote_card()
    print("wrote", RUN_DIR / "fable5_trajectory.png")
    print("wrote", RUN_DIR / "fable5_wandering_shelter.png")
    print("wrote", RUN_DIR / "fable5_quote_card.png")
