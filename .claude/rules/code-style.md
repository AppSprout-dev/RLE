# Code Style Rules

- No `Any` type annotations for dataclass fields. Use `TYPE_CHECKING` imports to break circular dependencies.
- Pydantic v2 with `frozen=True` for all data models.
- Async-first. All RIMAPI calls are async. Game loop is async.
- Tests use pytest-asyncio with `asyncio_mode = "auto"`.
- Run `pytest` and `ruff check src/ tests/ scripts/` before committing. All must pass.
