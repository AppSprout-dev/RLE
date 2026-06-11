#!/usr/bin/env bash
# Stage S: N=1 content-first model spread on Crashlanded, 10 ticks, seed 42.
# Sequential (one live game). Continue-on-error so one model can't block the rest.
set -u
cd "$(dirname "$0")/.."
PY=./.venv/Scripts/python
export ROLE_TIMEOUT_S=180
export PYTHONIOENCODING=utf-8

# name | provider | model | prompt$/MTok | completion$/MTok | base-url(optional)
RUNS=(
  "fable5|claude-code|claude-fable-5|10|50|"
  "opus48|claude-code|claude-opus-4-8|5|25|"
  "gpt55|openai|openai/gpt-5.5|5|30|https://openrouter.ai/api/v1"
  "gemini35|openai|google/gemini-3.5-flash|1.5|9|https://openrouter.ai/api/v1"
  "grok43|openai|x-ai/grok-4.3|1.25|2.5|https://openrouter.ai/api/v1"
  "deepseekv4|openai|deepseek/deepseek-v4-pro|0.435|0.87|https://openrouter.ai/api/v1"
)

echo "=== STAGE S SPREAD START ==="
for entry in "${RUNS[@]}"; do
  IFS='|' read -r name provider model pin pout baseurl <<< "$entry"
  out="results/spread/${name}"
  echo ""
  echo ">>> [$name] provider=$provider model=$model"
  args=(scripts/run_scenario.py crashlanded
        --provider "$provider" --model "$model"
        --ticks 10 --seed 42 --tick-interval 30 --no-pause --visualize
        --output "$out"
        --prompt-price-per-mtok "$pin" --completion-price-per-mtok "$pout")
  [ -n "$baseurl" ] && args+=(--base-url "$baseurl")
  "$PY" "${args[@]}"
  rc=$?
  if [ $rc -eq 0 ]; then echo "<<< [$name] OK"; else echo "<<< [$name] FAILED rc=$rc (continuing)"; fi
done
echo ""
echo "=== STAGE S SPREAD DONE ==="
