# RIMAPI path probe

Run metadata must pin the **compiled** AppSprout-dev/RIMAPI checkout, not the Steam Workshop DLL.

## Known pins

| Source | DLL SHA-256 prefix | Fork commit | Role |
|--------|--------------------|-------------|------|
| Compiled checkout (`../RIMAPI/1.6/Assemblies/RIMAPI.dll`) | `BFC9DD53…` | `b6c5003` | Source of truth |
| Steam Workshop overlay | `73E659E8…` | — | Flash drift; not SoT |

Do not re-hash these pins to "discover" them. AppSprout runs set `RIMAPI_DLL_PATH` and `RIMAPI_FORK_PATH` to the compiled checkout.

## Probe order

`collect_metadata()` in `src/rle/tracking/metadata.py` records `rimapi_dll_path`, `rimapi_dll_sha256`, and `rimapi_fork_commit`.

DLL (first existing file wins):

1. `$RIMAPI_DLL_PATH`
2. `$RIMAPI_FORK_PATH/1.6/Assemblies/RIMAPI.dll`
3. Sibling of the RLE git toplevel: `../RIMAPI/1.6/Assemblies/RIMAPI.dll`
4. Workshop path (optional last fallback)

Fork commit (first checkout with `.git` wins; empty string if none):

1. `$RIMAPI_FORK_PATH`
2. Sibling of `git rev-parse --show-toplevel` (not only `Path(__file__).parents[3]`, which is empty from site-packages / `.venv`)

## Box draft

The requested operator memo path `/workspace/drafts/2026-09-07-rimapi-path-probe.md` is outside this repository and will be written separately.
