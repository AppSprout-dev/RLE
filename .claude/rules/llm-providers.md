---
paths:
  - "src/rle/agents/**"
  - "scripts/**"
---

# LLM Provider Rules

- Default local model: Nemotron 3 Nano 4B via LM Studio.
- Always use `--no-think` for thinking models (Qwen3.5, Nemotron). It injects `</think>` as assistant prefix.
- JSON repair (`json_repair.py`) runs on ALL LLM output before parsing. Never parse raw output directly.
- Parse retry with correction prompt is the fallback. Never silently drop a failed deliberation — log it.
- OpenRouter is the preferred cloud provider. Model: `nvidia/nemotron-3-super-120b-a12b`.
