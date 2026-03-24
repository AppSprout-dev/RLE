---
paths:
  - "src/rle/rimapi/**"
  - "src/rle/orchestration/action_executor.py"
---

# RIMAPI Integration Rules

- RIMAPI uses SnakeCaseContractResolver — all request body fields must be snake_case (e.g. `pawn_id`, not `PawnId`).
- Use `_int_id()` for all pawn/colonist IDs sent to RIMAPI.
- Some colonist data (skills, traits, current_job, detailed needs) is NOT available from RIMAPI. Don't assume these fields exist.
- State adapters in `client.py` bridge upstream response shapes to our Pydantic schemas. Always adapt, never assume matching shapes.
- Growing zones use rect coordinates (x1, z1, x2, z2), not cell lists.
