---
name: run-analysis
description: Full post-run pipeline for RLE benchmark runs — leaderboard analysis vs baseline, failure taxonomy, story mining with verbatim verification, footage indexing, and X-ready video production. Use after any live run or model spread completes.
---

# RLE Post-Run Pipeline

Process the output of a live run/spread end-to-end. Proven on the Stage S 6-model spread
(2026-06-10). Governing discipline: **separate harness artifacts from model quality before
ranking anything**, and **verify every quote verbatim before publishing it**.

Inputs per model: `results/<run>/<name>/` containing `01_*_summary.json`, `01_*.csv`,
`events.jsonl`, `01_*_deliberations.jsonl`. Read with `PYTHONIOENCODING=utf-8`.

## Phase 0 — Media capture setup (BEFORE launching the run)

Everything here must be running before tick 1 — capture started late on the Stage S spread
and lost the first model's early tick snapshots + 4.7 min of OBS coverage.

1. **OBS** (user starts it): source must be **Game Capture** — Display/Window capture
   region-grabs whatever floats over the game (dialogs, browser tabs with API keys).
   Output to **D:** (~10 GB/hour at the spread's settings; check free space). The default
   filename encodes the start time (`2026-06-10 20-55-09.mkv`) — that timestamp is the
   `--obs-start` input for the footage index later.
2. **Verify OBS is actually recording** — silence is not success. NTFS under-reports size
   for open files; check the real stream length twice a few seconds apart:
   `[System.IO.File]::Open($p,'Open','Read','ReadWrite').Length` (PowerShell). It must grow.
3. **Capture loop** (frames + tick snapshots), in background for the whole run:
   `bash scripts/capture_run_media.sh results/<run> D:/RLE_media/footage/frames`
   (set FFMPEG env var if ffmpeg isn't on PATH; winget package Gyan.FFmpeg).
   Note: ffmpeg gdigrab needs even dimensions — the script's single-frame mode is fine,
   but any direct video capture needs `-vf "crop=trunc(iw/2)*2:trunc(ih/2)*2"`.
4. **Game hygiene for clean footage**: disable dev-mode auto-open of the debug log
   (issue #33) and expect the camera to sit at map center unless #34 is built — plan for
   caption-driven clips, not action footage.
5. Don't screen-record the desktop yourself (privacy: anything can float over the game
   region) — periodic stills are auditable; OBS Game Capture is the continuous source.

## Phase 1 — Analysis (deterministic)

```
PYTHONIOENCODING=utf-8 python scripts/analyze_spread.py --spread-dir results/<run>
```

Writes `leaderboard.json` + `analysis.md`. Key rules baked in:
- **Day-align** against the baseline (`results/baseline/.../seed*/...csv`), never tick-align —
  the no-agent baseline ticks ~30x/day, agent runs ~2-3x/day.
- Rank by **mean composite over the run**, not the final tick (endpoint = one bad event).
- Action success reported raw AND ex-artifact (harness failure markers are listed in the
  script — keep them current as harness bugs are fixed/found).
- Always reconcile estimated cost against the OpenRouter dashboard/key endpoint — the
  tracker has undercounted reasoning tokens before (issue #33).

Then per playbook: check per-type action success for any type at 0/N (suspect harness, not
model), count repeated identical failures (perseveration — check whether DO-NOT-REPEAT
feedback was delivered before blaming the model), find best/worst tick and tie each to an
event.

## Phase 2 — Story mining (parallel agents, then VERIFY)

Fan out one Explore agent per model over `01_*_deliberations.jsonl` asking for 3-5 quotable
moments (tick, agent role, VERBATIM quote, why it's good content). Give each agent that
model's stats (rank, quirks) as context.

**Then re-grep every quote against the actual log before using it anywhere.** Miners
paraphrase: in the Stage S spread, 2 of 6 "verbatim" headline quotes were embellishments.
Save the verified bank to `results/<run>/stories.md` with ✅/⚠ verification marks.

## Phase 3 — Footage index (if Phase 0 ran)

With the OBS master + capture-loop output from Phase 0:

```
python scripts/build_footage_index.py --log <console.log> --obs-file <rec.mkv> \
    --obs-start "YYYY-MM-DD HH:MM:SS" --out footage_index.json
```

Maps every model + tick to wall clock and OBS file offsets, and catalogs warnings.

## Phase 4 — Videos (EDL → ffmpeg → Remotion)

Deck workflow (thariqs cc-video-editing-deck): edit-decision-list as JSON with rationale →
ffmpeg executes cuts → Remotion renders data-driven graphics → verify by extracting stills
of every segment (Read the PNGs — never ship an unviewed render).

- Remotion project: `D:\RLE_media\rle_video\` (timing knobs in `src/anim.ts`, leaderboard
  data in `src/data.json` regenerated from `leaderboard.json`). Assets must live under
  `public/` (staticFile) — junctions break the bundler.
- Timelapse source: `ffmpeg -i master.mkv -vf "setpts=PTS/60,fps=24,crop=trunc(iw/2)*2:trunc(ih/2)*2" -an`.
- **Dashboard clip rig** (source: `D:\RLE_media\capture\record_dashboard.mjs` — the
  rle-media repo, which is the set-up scratch dir with playwright already installed) —
  headless Playwright recording, never screen capture. Four processes, in order:
  1. RimWorld + RIMAPI up (the dashboard's connect gate probes :8765; CORS is fine, but
     the URL field starts EMPTY — the script fills it and clicks Connect).
  2. `./.venv/Scripts/python scripts/serve_dashboard.py results/replay` (CORS server :9000).
  3. Dashboard: `PORT=3001 BROWSER=none bun run start` in rimapi-dashboard — NOT :3000
     (Remotion's render server squats on 3000; craco exits "already running" instead of failing loud).
  4. `python scripts/replay_ticks.py --model <name> --interval 2 --loop` (feeds
     results/replay/latest_tick.json from the run's tick_snapshots).
  Then record from `D:\RLE_media\capture\` (playwright already installed there; if starting
  fresh elsewhere, `bun add playwright && bunx playwright install chromium` first) and run
  with **node** — Playwright's chromium launch hangs 180s under bun on Windows. The script
  seeds the 5 RLE widgets via a localStorage `dashboard_presets` preset (the dashboard now
  also ships built-in `RLE Capture`/`RLE Vertical` presets selectable via `?preset=`, and
  `?api=<url>` skips the connect gate — either path works). Record 1920x1080 and 1080x1920 passes; trim the
  connect/load preamble (~8s) when converting webm → mp4
  (`ffmpeg -ss 8 -i in.webm -c:v libx264 -crf 19 -pix_fmt yuv420p -r 30 out.mp4`).
- Verify every render before calling it done: extract stills of each segment with ffmpeg
  and actually Read them — stale ports, empty widgets, and black OffthreadVideo frames all
  look identical to success in the exit code.
- Render 16:9 and 9:16 variants (compositions take portrait into account via useVideoConfig).
- All media outputs to **D:** (`D:\RLE_media\`), never C:.

## Phase 5 — Publish prep

- Update memory (`project_benchmark_spread` or successor) with results + artifact locations.
- X thread: 3-5 posts max. Lead with the strongest narrative clip (hero or disaster), data
  (leaderboard) in the middle, method/repo last. Draft to `D:\RLE_media\x_thread.md`.
- File issues for every harness bug found before the next run.
