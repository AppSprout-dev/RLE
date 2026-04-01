# RLE Save Files

Compressed RimWorld save files used by the benchmark scenarios.

## Install

Extract to your RimWorld saves folder:

```bash
# Windows
gunzip -k rle_crashlanded_v1.rws.gz
cp rle_crashlanded_v1.rws "%LOCALAPPDATA%\..\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Saves\"

# Or manually: extract the .gz, copy the .rws file to:
# C:\Users\<you>\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Saves\
```

`run_scenario.py` auto-loads the save by name — just make sure the `.rws` file exists in the saves folder.
