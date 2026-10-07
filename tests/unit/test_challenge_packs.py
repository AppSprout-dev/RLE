"""Challenge packs: load challenge + expected + pass/fail over fixture receipts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tests.unit.challenge_pack_loader import (
    JUDGMENT_NAMES,
    PACK_ROOT,
    evaluate,
    judge,
    load_pack,
    load_packs,
)

PACK_IDS = (
    "research_unblock",
    "ensure_live_save",
    "preflight_contract",
    "composite_receipt",
)


def test_four_packs_load() -> None:
    packs = load_packs(PACK_ROOT)
    assert tuple(pack.id for pack in packs) == tuple(sorted(PACK_IDS))


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_pack_is_crashlanded_fixture(pack_id: str) -> None:
    pack = load_pack(PACK_ROOT / pack_id)
    assert pack.scenario == "Crashlanded Survival"
    assert pack.seed == 42
    assert pack.tick_budget == 10
    assert pack.mode == "fixture"
    assert pack.harness == "fixture"
    assert pack.model == "fixture"
    assert pack.scoring_version == "1.2"
    assert set(pack.expected) <= JUDGMENT_NAMES
    assert {item.judgment for item in pack.predicates} == set(pack.expected)


def test_expected_names_cover_the_catalog_shapes() -> None:
    packs = {pack.id: pack for pack in load_packs(PACK_ROOT)}
    assert packs["research_unblock"].expected == (
        "research_bench_present",
        "research_adapters",
    )
    assert packs["ensure_live_save"].expected == ("ensure_live_save",)
    assert packs["preflight_contract"].expected == (
        "stockpile_delete_quarantine",
        "preflight_contract",
    )
    assert packs["composite_receipt"].expected == ("composite_receipt",)


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_pass_receipts_pass(pack_id: str) -> None:
    result = evaluate(load_pack(PACK_ROOT / pack_id), "pass")
    assert result.passed, result.reasons


@pytest.mark.parametrize("pack_id", PACK_IDS)
def test_fail_receipts_fail(pack_id: str) -> None:
    result = evaluate(load_pack(PACK_ROOT / pack_id), "fail")
    assert not result.passed
    assert result.reasons


def test_ensure_live_save_pin_match_versus_stale_appdata() -> None:
    root = PACK_ROOT / "ensure_live_save" / "receipts"
    passed = json.loads((root / "pass" / "preflight.json").read_text(encoding="utf-8"))
    failed = json.loads((root / "fail" / "preflight.json").read_text(encoding="utf-8"))
    assert passed["live_save_sha256"] == passed["pinned_sha256"]
    assert passed["error"] is None
    assert failed["live_save_sha256"] != failed["pinned_sha256"]
    assert failed["error"] == "LiveSavePinError"
    pack = load_pack(PACK_ROOT / "ensure_live_save")
    assert evaluate(pack, "pass").passed
    assert not evaluate(pack, "fail").passed


def test_stockpile_delete_pass_is_quarantined_event() -> None:
    root = PACK_ROOT / "preflight_contract" / "receipts"
    passed = json.loads((root / "pass" / "events.jsonl").read_text(encoding="utf-8"))
    failed = json.loads((root / "fail" / "events.jsonl").read_text(encoding="utf-8"))
    assert passed["data"]["action_type"] == "stockpile_delete"
    assert passed["data"]["success"] is False
    assert "quarantined" in passed["data"]["error"]
    assert failed["data"]["success"] is True


def test_composite_receipt_rejects_n_claim_and_reasoning_trace() -> None:
    root = PACK_ROOT / "composite_receipt" / "receipts"
    passed = json.loads((root / "pass" / "summary.json").read_text(encoding="utf-8"))
    failed = json.loads((root / "fail" / "summary.json").read_text(encoding="utf-8"))
    assert passed["scoring_version"] == "1.2"
    assert isinstance(passed["final_score"], (int, float))
    assert "n_runs" not in passed
    assert "pass_rate" not in passed
    assert "reasoning_traces" not in passed
    assert "n_runs" in failed
    assert "pass_rate" in failed
    assert "reasoning_traces" in failed
    pack = load_pack(PACK_ROOT / "composite_receipt")
    predicate = pack.predicates[0]
    lte = next(clause for clause in predicate.clauses if clause.op == "lte")
    assert lte.value == pack.tick_budget
    assert evaluate(pack, "pass").passed
    assert not evaluate(pack, "fail").passed


def test_reasoning_traces_fail_closed_even_on_a_passing_summary() -> None:
    pack = load_pack(PACK_ROOT / "composite_receipt")
    summary = json.loads(
        (PACK_ROOT / "composite_receipt" / "receipts" / "pass" / "summary.json").read_text(
            encoding="utf-8",
        ),
    )
    summary["reasoning_traces"] = [{"summary": "abridged"}]
    reasons = judge(pack.predicates[0], summary)
    assert reasons
    assert any("reasoning_traces" in reason for reason in reasons)


def test_unknown_judgment_name_is_rejected(tmp_path: Path) -> None:
    pack_dir = tmp_path / "not_a_judgment"
    pack_dir.mkdir()
    (pack_dir / "challenge.yaml").write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "id": "not_a_judgment",
            "scenario": "Crashlanded Survival",
            "seed": 42,
            "tick_budget": 10,
            "mode": "fixture",
            "harness": "fixture",
            "model": "fixture",
            "scoring_version": "1.2",
            "expected": ["invented_rate"],
            "pass_fail": [],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not a judgment name"):
        load_pack(pack_dir)
