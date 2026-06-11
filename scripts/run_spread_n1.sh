#!/usr/bin/env bash
# Stage S: N=1 content-first model spread on Crashlanded, 10 ticks, seed 42.
# Sequential (one live game). Continue-on-error so one model can't block the rest.
set -u
cd "$(dirname "$0")/.."
PY=./.venv/Scripts/python
export ROLE_TIMEOUT_S=180
export PYTHONIOENCODING=utf-8

# Per-model OBS capture via scripts/obs_record.py (requires OBS running with
# WebSocket server enabled). Set OBS_RECORD=0 to disable.
OBS_RECORD="${OBS_RECORD:-1}"
obs() {
  [ "$OBS_RECORD" = "1" ] || return 0
  uv run scripts/obs_record.py "$@" || echo "(obs $1 failed — continuing)"
}

# name | provider | model | prompt$/MTok | completion$/MTok | base-url(optional) | extra-flags(optional)
RUNS=(
  "fable5|claude-code|claude-fable-5|10|50||"
  "opus48|claude-code|claude-opus-4-8|5|25||"
  "gpt55|openai|openai/gpt-5.5|5|30|https://openrouter.ai/api/v1|"
  "gemini35|openai|google/gemini-3.5-flash|1.5|9|https://openrouter.ai/api/v1|"
  "grok43|openai|x-ai/grok-4.3|1.25|2.5|https://openrouter.ai/api/v1|"
  "deepseekv4|openai|deepseek/deepseek-v4-pro|0.435|0.87|https://openrouter.ai/api/v1|"
  # v0.2.0 validation spread additions (pricing from OpenRouter /models 2026-06-11)
  "qwen37max|openai|qwen/qwen3.7-max|1.25|3.75|https://openrouter.ai/api/v1|--no-think"
  "kimi26|openai|moonshotai/kimi-k2.6|0.67|3.39|https://openrouter.ai/api/v1|"
  "glm51|openai|z-ai/glm-5.1|0.98|3.08|https://openrouter.ai/api/v1|"
  "mistralmed35|openai|mistralai/mistral-medium-3-5|1.5|7.5|https://openrouter.ai/api/v1|"
  "nemotron120b|openai|nvidia/nemotron-3-super-120b-a12b|0.09|0.45|https://openrouter.ai/api/v1|--no-think"
)

echo "=== STAGE S SPREAD START ==="
for entry in "${RUNS[@]}"; do
  IFS='|' read -r name provider model pin pout baseurl extraflags <<< "$entry"
  out="results/spread/${name}"
  echo ""
  echo ">>> [$name] provider=$provider model=$model"
  args=(scripts/run_scenario.py crashlanded
        --provider "$provider" --model "$model"
        --ticks 10 --seed 42 --tick-interval 30 --no-pause --visualize
        --output "$out"
        --prompt-price-per-mtok "$pin" --completion-price-per-mtok "$pout")
  [ -n "$baseurl" ] && args+=(--base-url "$baseurl")
  [ -n "$extraflags" ] && args+=($extraflags)
  obs start --label "$name"
  "$PY" "${args[@]}"
  rc=$?
  obs stop
  if [ $rc -eq 0 ]; then echo "<<< [$name] OK"; else echo "<<< [$name] FAILED rc=$rc (continuing)"; fi
done
echo ""
echo "=== STAGE S SPREAD DONE ==="
