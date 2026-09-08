# RLE Save Files

Compressed RimWorld save files used by the benchmark scenarios.

`rle_crashlanded_v1` seeds a built, player-owned `SimpleResearchBench`
(wood, `(128, 0, 136)`, no power required) and queues `currentProj=Smithing`.
Without the bench, scoring 1.2 research floors at **7/31 ≈ 0.2258** — the
starting finished/available ratio — because colonists cannot finish tech and
`research_target` is rejected as bench/prereqs missing. That floor is not σ.
The other five scenario saves are derived from this base; rebuild them via
`scripts/create_scenario_saves.py` if they need the same bench.

## Install

Extract to your RimWorld saves folder:

### Windows (PowerShell)

```powershell
# From the saves/ directory
tar -xzf rle_crashlanded_v1.rws.gz
Copy-Item rle_crashlanded_v1.rws "$env:LOCALAPPDATA\..\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Saves\"
```

### Linux / macOS

```bash
# From the saves/ directory
gunzip -k rle_crashlanded_v1.rws.gz
cp rle_crashlanded_v1.rws ~/.config/unity3d/Ludeon\ Studios/RimWorld\ by\ Ludeon\ Studios/Saves/
```

`run_scenario.py` auto-loads the save by name — just make sure the `.rws` file exists in the saves folder.
