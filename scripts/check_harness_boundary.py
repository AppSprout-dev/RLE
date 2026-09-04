"""Enforce the harness boundary rules (run in CI, stdlib only).

1. ``felix_agent_sdk`` may be imported only under ``src/rle/harness/felix/``.
   Everything else in core must run with the ``felix`` extra uninstalled.
2. Third-party harnesses (OpenCode, Grok Build, ...) live in their own repos.
   Their names may appear in docs, never in ``src/``, ``tests/`` or ``scripts/``.

Exit code 1 with a file:line listing on any violation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "rle"
FELIX_DIR = SRC / "harness" / "felix"

FELIX_IMPORT = re.compile(r"^\s*(from|import)\s+felix_agent_sdk\b", re.MULTILINE)
THIRD_PARTY = re.compile(r"\b(opencode|grok[-_ ]?build|grok_build)\b", re.IGNORECASE)
CODE_DIRS = (ROOT / "src", ROOT / "tests", ROOT / "scripts")


def _py_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def check_felix_boundary() -> list[str]:
    violations: list[str] = []
    for path in _py_files(SRC):
        if FELIX_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for match in FELIX_IMPORT.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(
                f"{path.relative_to(ROOT)}:{line}: felix_agent_sdk import outside "
                f"src/rle/harness/felix/",
            )
    return violations


def check_no_third_party_harness_code() -> list[str]:
    violations: list[str] = []
    for root in CODE_DIRS:
        for path in _py_files(root):
            if path.resolve() == Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            for match in THIRD_PARTY.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(
                    f"{path.relative_to(ROOT)}:{line}: third-party harness name "
                    f"{match.group(0)!r} in core code (belongs in its own repo)",
                )
    return violations


def main() -> int:
    violations = check_felix_boundary() + check_no_third_party_harness_code()
    if violations:
        print("Harness boundary violations:")
        for v in violations:
            print(f"  {v}")
        return 1
    print("Harness boundary OK: felix_agent_sdk confined to src/rle/harness/felix/; "
          "no third-party harness code in tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
