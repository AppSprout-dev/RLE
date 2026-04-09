# Code Style Rules

- Python 3.14+. Use `uv sync --extra dev` to install.
- mypy strict mode. All code must pass `mypy src/` with `strict = true`.
- No `Any` type annotations for dataclass fields. Use `TYPE_CHECKING` imports to break circular dependencies.
- `from __future__ import annotations` at top of every Python file.
- Pydantic v2 with `frozen=True` for all data models.
- Async-first. All RIMAPI calls are async. Game loop is async.
- No scipy/numpy. Use stdlib only (random, math, statistics). See ADR-003.
- Tests use pytest-asyncio with `asyncio_mode = "auto"`.
- Run `pytest`, `ruff check src/ tests/ scripts/`, and `mypy src/` before committing. All must pass.
