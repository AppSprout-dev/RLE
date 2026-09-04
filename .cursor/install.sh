#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the RimWorld Learning Environment.
# Installs the uv package manager (which manages the pinned Python 3.14
# toolchain) and syncs project dependencies with the dev extra.
set -euo pipefail

# Install uv if it is not already available. The official installer pins the
# binary under ~/.local/bin and appends PATH setup to ~/.bashrc and ~/.profile,
# so later login/interactive shells (and agent commands) resolve `uv`.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# Resolve/download the pinned Python (see .python-version) and install all
# runtime + dev dependencies from the committed uv.lock. --frozen keeps the
# lockfile authoritative so setup never silently rewrites it.
uv sync --extra dev --frozen
