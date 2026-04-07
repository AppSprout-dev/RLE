# RLE Save Files

Compressed RimWorld save files used by the benchmark scenarios.

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
