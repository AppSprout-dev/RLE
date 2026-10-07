"""Load and evaluate public-proof challenge packs.

Pack shape (schema_version 1): challenge file, expected judgment names,
and pass/fail clauses over printed receipts. Chain-of-thought keys
(``reasoning_trace``, ``reasoning_traces``) fail closed — they are
narrative, not proof. Fixture mode reads checked-in files only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Judgment names drawn from existing RLE receipts. A name is the judgment.
JUDGMENT_NAMES: frozenset[str] = frozenset({
    "research_bench_present",
    "ensure_live_save",
    "research_adapters",
    "stockpile_delete_quarantine",
    "preflight_contract",
    "composite_receipt",
})

_COT_KEYS: frozenset[str] = frozenset({"reasoning_trace", "reasoning_traces"})
_OPS: frozenset[str] = frozenset({
    "eq",
    "ne",
    "lte",
    "gte",
    "contains",
    "not_contains",
    "type",
    "present",
    "absent",
    "eq_path",
})
_TYPES: frozenset[str] = frozenset({"number", "string", "bool", "list", "object"})
_MISSING = object()

PACK_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "challenge_packs"


@dataclass(frozen=True)
class Clause:
    """One deterministic check against a receipt object."""

    path: str
    op: str
    value: Any


@dataclass(frozen=True)
class Predicate:
    """Pass/fail rule for one expected judgment name."""

    judgment: str
    receipt: str
    match: str
    where: tuple[tuple[str, Any], ...]
    clauses: tuple[Clause, ...]
    absent: tuple[str, ...]


@dataclass(frozen=True)
class Challenge:
    """One challenge pack: challenge fields plus predicates."""

    id: str
    scenario: str
    seed: int
    tick_budget: int
    mode: str
    harness: str
    model: str
    scoring_version: str
    expected: tuple[str, ...]
    predicates: tuple[Predicate, ...]
    root: Path


@dataclass(frozen=True)
class EvalResult:
    """Outcome of evaluating every predicate on one receipt case."""

    passed: bool
    reasons: tuple[str, ...]


def load_packs(root: Path | None = None) -> tuple[Challenge, ...]:
    """Load every pack directory under ``root`` (sorted by id)."""
    base = root if root is not None else PACK_ROOT
    dirs = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    return tuple(load_pack(path) for path in dirs)


def load_pack(path: Path) -> Challenge:
    """Load and validate one pack directory."""
    challenge_path = _challenge_file(path)
    raw = yaml.safe_load(challenge_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{challenge_path} must be a mapping")
    _require_keys(raw, challenge_path)
    if raw["schema_version"] != 1:
        raise ValueError(f"{path.name}: schema_version must be 1")
    if raw["id"] != path.name:
        raise ValueError(f"{path.name}: id {raw['id']!r} does not match the directory")
    if raw["scoring_version"] != "1.2":
        raise ValueError(f"{path.name}: scoring_version must be '1.2'")
    mode = raw["mode"]
    if mode not in ("fixture", "harness"):
        raise ValueError(f"{path.name}: mode must be fixture or harness")
    harness = raw["harness"]
    model = raw["model"]
    if not isinstance(harness, str) or not harness:
        raise ValueError(f"{path.name}: harness must be a non-empty string")
    if not isinstance(model, str) or not model:
        raise ValueError(f"{path.name}: model must be a non-empty string")
    if mode == "fixture" and (harness != "fixture" or model != "fixture"):
        raise ValueError(f"{path.name}: fixture mode requires harness and model 'fixture'")
    if mode == "harness" and (harness == "fixture" or model == "fixture"):
        raise ValueError(f"{path.name}: harness mode requires a real harness and model")
    seed = raw["seed"]
    tick_budget = raw["tick_budget"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"{path.name}: seed must be an int")
    if not isinstance(tick_budget, int) or isinstance(tick_budget, bool) or tick_budget < 1:
        raise ValueError(f"{path.name}: tick_budget must be a positive int")
    scenario = raw["scenario"]
    if not isinstance(scenario, str) or not scenario:
        raise ValueError(f"{path.name}: scenario must be a non-empty string")
    expected = _expected(raw["expected"], path.name)
    predicates = _predicates(raw["pass_fail"], expected, path.name)
    pack = Challenge(
        id=path.name,
        scenario=scenario,
        seed=seed,
        tick_budget=tick_budget,
        mode=mode,
        harness=harness,
        model=model,
        scoring_version="1.2",
        expected=expected,
        predicates=predicates,
        root=path,
    )
    _require_receipts(pack)
    return pack


def evaluate(pack: Challenge, case: str) -> EvalResult:
    """Evaluate every predicate against ``receipts/<case>/``."""
    if case not in ("pass", "fail"):
        raise ValueError("case must be 'pass' or 'fail'")
    reasons: list[str] = []
    for predicate in pack.predicates:
        receipt_path = pack.root / "receipts" / case / predicate.receipt
        payload = _read_receipt(receipt_path, predicate.match)
        found = judge(predicate, payload)
        reasons.extend(f"{predicate.judgment}: {reason}" for reason in found)
    return EvalResult(passed=not reasons, reasons=tuple(reasons))


def judge(predicate: Predicate, payload: Any) -> tuple[str, ...]:
    """Return failure reasons for one predicate. Empty means pass."""
    if predicate.match == "object":
        return _judge_object(predicate, payload)
    if predicate.match == "any":
        return _judge_any(predicate, payload)
    return (f"unknown match {predicate.match!r}",)


def _judge_object(predicate: Predicate, payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ("receipt is not a JSON object",)
    reasons = _cot_reasons(payload)
    reasons.extend(_absent_reasons(predicate, payload))
    if reasons:
        return tuple(reasons)
    return tuple(
        reason
        for clause in predicate.clauses
        if (reason := _clause_reason(clause, payload)) is not None
    )


def _judge_any(predicate: Predicate, payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, list):
        return ("events receipt is not a list of JSONL objects",)
    eligible: list[dict[str, Any]] = []
    for line in payload:
        if not isinstance(line, dict):
            continue
        if _COT_KEYS.intersection(line):
            continue
        if any(_lookup(line, path) != expected for path, expected in predicate.where):
            continue
        if any(key in line for key in predicate.absent):
            continue
        eligible.append(line)
    if not eligible:
        return ("no eligible events line matched",)
    if any(
        all(_clause_reason(clause, line) is None for clause in predicate.clauses)
        for line in eligible
    ):
        return ()
    return ("no events line satisfied the clauses",)


def _clause_reason(clause: Clause, payload: dict[str, Any]) -> str | None:
    found = _lookup(payload, clause.path)
    if clause.op == "present":
        if found is _MISSING or found is None:
            return f"{clause.path} is absent"
        return None
    if clause.op == "absent":
        if found is _MISSING or found is None:
            return None
        return f"{clause.path} is present"
    if found is _MISSING:
        return f"{clause.path} is missing"
    if clause.op == "eq":
        return None if found == clause.value else f"{clause.path} {found!r} != {clause.value!r}"
    if clause.op == "ne":
        return None if found != clause.value else f"{clause.path} == {clause.value!r}"
    if clause.op == "eq_path":
        other = _lookup(payload, str(clause.value))
        if other is _MISSING:
            return f"{clause.value} is missing"
        if found != other:
            return f"{clause.path} {found!r} != {clause.value} {other!r}"
        return None
    if clause.op in ("lte", "gte"):
        if not _is_number(found) or not _is_number(clause.value):
            return f"{clause.path} is not numeric"
        if clause.op == "lte" and found > clause.value:
            return f"{clause.path} {found!r} > {clause.value!r}"
        if clause.op == "gte" and found < clause.value:
            return f"{clause.path} {found!r} < {clause.value!r}"
        return None
    if clause.op == "contains":
        if _contains(found, clause.value):
            return None
        return f"{clause.path} does not contain {clause.value!r}"
    if clause.op == "not_contains":
        if not _contains(found, clause.value):
            return None
        return f"{clause.path} contains {clause.value!r}"
    if clause.op == "type":
        if _matches_type(found, str(clause.value)):
            return None
        return f"{clause.path} is not {clause.value}"
    return f"unknown op {clause.op}"


def _cot_reasons(payload: dict[str, Any]) -> list[str]:
    return [
        f"{key} is narrative, not a receipt"
        for key in sorted(_COT_KEYS.intersection(payload))
    ]


def _absent_reasons(predicate: Predicate, payload: dict[str, Any]) -> list[str]:
    return [f"forbidden key {key}" for key in predicate.absent if key in payload]


def _contains(haystack: Any, needle: Any) -> bool:
    if isinstance(haystack, str):
        return isinstance(needle, str) and needle in haystack
    if isinstance(haystack, list):
        return needle in haystack
    return False


def _matches_type(value: Any, kind: str) -> bool:
    if kind == "number":
        return _is_number(value)
    if kind == "string":
        return isinstance(value, str)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "list":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    return False


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _lookup(payload: Any, path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return _MISSING
    return current


def _challenge_file(path: Path) -> Path:
    for name in ("challenge.yaml", "challenge.yml"):
        candidate = path / name
        if candidate.is_file():
            return candidate
    raise ValueError(f"{path} has no challenge.yaml")


def _require_keys(raw: dict[str, Any], challenge_path: Path) -> None:
    required = (
        "schema_version",
        "id",
        "scenario",
        "seed",
        "tick_budget",
        "mode",
        "harness",
        "model",
        "scoring_version",
        "expected",
        "pass_fail",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"{challenge_path.name} missing {missing}")


def _expected(raw: Any, pack_id: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{pack_id}: expected must be a non-empty list of names")
    names: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item not in JUDGMENT_NAMES:
            raise ValueError(f"{pack_id}: {item!r} is not a judgment name")
        if item in names:
            raise ValueError(f"{pack_id}: duplicate expected name {item}")
        names.append(item)
    return tuple(names)


def _predicates(raw: Any, expected: tuple[str, ...], pack_id: str) -> tuple[Predicate, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{pack_id}: pass_fail must be a list")
    predicates = tuple(_predicate(item, pack_id) for item in raw)
    got = tuple(item.judgment for item in predicates)
    if len(got) != len(set(got)):
        raise ValueError(f"{pack_id}: duplicate pass_fail judgment")
    if set(got) != set(expected):
        raise ValueError(f"{pack_id}: pass_fail judgments must match expected")
    return predicates


def _predicate(raw: Any, pack_id: str) -> Predicate:
    if not isinstance(raw, dict):
        raise ValueError(f"{pack_id}: pass_fail entry must be a mapping")
    judgment = raw.get("judgment")
    receipt = raw.get("receipt")
    match = raw.get("match")
    if not isinstance(judgment, str) or judgment not in JUDGMENT_NAMES:
        raise ValueError(f"{pack_id}: bad judgment {judgment!r}")
    if not isinstance(receipt, str) or "/" in receipt or "\\" in receipt:
        raise ValueError(f"{pack_id}: receipt must be a file name")
    if match not in ("object", "any"):
        raise ValueError(f"{pack_id}: match must be object or any")
    if match == "object" and not receipt.endswith(".json"):
        raise ValueError(f"{pack_id}: object receipts end with .json")
    if match == "any" and not receipt.endswith(".jsonl"):
        raise ValueError(f"{pack_id}: any-match receipts end with .jsonl")
    where_raw = raw.get("where") or {}
    if not isinstance(where_raw, dict):
        raise ValueError(f"{pack_id}: where must be a mapping")
    if match == "object" and where_raw:
        raise ValueError(f"{pack_id}: where is only for JSONL receipts")
    clauses_raw = raw.get("all")
    if not isinstance(clauses_raw, list) or not clauses_raw:
        raise ValueError(f"{pack_id}: {judgment} needs a non-empty all list")
    absent_raw = raw.get("absent") or []
    if not isinstance(absent_raw, list) or not all(isinstance(item, str) for item in absent_raw):
        raise ValueError(f"{pack_id}: absent must be a list of keys")
    return Predicate(
        judgment=judgment,
        receipt=receipt,
        match=match,
        where=tuple((str(key), value) for key, value in where_raw.items()),
        clauses=tuple(_clause(item, pack_id) for item in clauses_raw),
        absent=tuple(absent_raw),
    )


def _clause(raw: Any, pack_id: str) -> Clause:
    if not isinstance(raw, dict):
        raise ValueError(f"{pack_id}: clause must be a mapping")
    path = raw.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError(f"{pack_id}: clause needs a path")
    ops = [key for key in raw if key != "path"]
    if len(ops) != 1 or ops[0] not in _OPS:
        raise ValueError(f"{pack_id}: clause needs exactly one operator")
    op = ops[0]
    value = raw[op]
    if op == "type" and value not in _TYPES:
        raise ValueError(f"{pack_id}: type must be one of {sorted(_TYPES)}")
    if op in ("present", "absent") and value is not True:
        raise ValueError(f"{pack_id}: {op} clause value must be true")
    if op == "eq_path" and not isinstance(value, str):
        raise ValueError(f"{pack_id}: eq_path needs a path string")
    return Clause(path=path, op=op, value=value)


def _require_receipts(pack: Challenge) -> None:
    for case in ("pass", "fail"):
        for predicate in pack.predicates:
            receipt = pack.root / "receipts" / case / predicate.receipt
            if not receipt.is_file():
                raise ValueError(f"{pack.id}: missing {case} receipt {predicate.receipt}")


def _read_receipt(path: Path, match: str) -> Any:
    text = path.read_text(encoding="utf-8")
    if match == "object":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            return {"_unreadable": str(exc)}
    rows: list[Any] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"_unreadable_line": line_no})
    return rows
