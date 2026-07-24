"""Tests for carry capital/margin accounting and the artifact promotion review."""

from __future__ import annotations

import json

import pytest

from quant_trade.carry.capital import (
    capital_required,
    collateral_invariants,
    residual_delta,
    simulate_perp_margin_path,
)
from quant_trade.carry.data import synthetic_funding_snapshots, write_snapshots_json
from quant_trade.carry.research import evaluate_carry_promotion
from quant_trade.evidence.canonical_json import atomic_write_json
from quant_trade.evidence.manifest import build_dataset_manifest
from quant_trade.research.ledger import append_trial_record, build_trial_record

# --- capital & margin -----------------------------------------------------


def test_capital_required_breakdown():
    cap = capital_required(100_000.0, perp_leverage=2.0, buffer_fraction=0.10)
    assert cap.spot_capital_usd == 100_000.0
    assert cap.perp_initial_margin_usd == 50_000.0
    assert cap.liquidity_buffer_usd == 10_000.0
    assert cap.total_capital_usd == 160_000.0


def test_margin_path_benign_no_breach():
    prices = [100.0, 101.0, 99.5, 100.5]
    result = simulate_perp_margin_path(prices, perp_leverage=1.0, maintenance_margin_rate=0.005)
    assert not result.breached
    assert result.min_margin_distance > 0
    assert result.max_adverse_excursion == pytest.approx(0.01)


def test_margin_path_adverse_breaches_with_leverage():
    # short perp at 100, price rockets to 125: at 5x leverage the 20% initial
    # margin is wiped out before maintenance
    prices = [100.0, 110.0, 125.0]
    result = simulate_perp_margin_path(prices, perp_leverage=5.0, maintenance_margin_rate=0.005)
    assert result.breached
    assert result.breach_index == 2
    assert result.max_adverse_excursion == pytest.approx(0.25)


def test_margin_path_records_variation_margin_sign():
    result = simulate_perp_margin_path([100.0, 90.0], perp_leverage=1.0)
    # short gains when price falls
    assert result.final_variation_margin == pytest.approx(0.10)


def test_collateral_invariants_balance_and_violation():
    ok = collateral_invariants(
        initial_capital_usd=160_000.0,
        cash_usd=10_000.0,
        spot_value_usd=101_000.0,
        perp_margin_account_usd=50_000.0,
        cumulative_pnl_usd=1_000.0,
    )
    assert ok == []
    broken = collateral_invariants(
        initial_capital_usd=160_000.0,
        cash_usd=10_000.0,
        spot_value_usd=101_000.0,
        perp_margin_account_usd=50_000.0,
        cumulative_pnl_usd=0.0,  # 1,000 USD appeared from nowhere
    )
    assert any("identity broken" in v for v in broken)


def test_residual_delta_hedged_and_unhedged():
    delta, hedged = residual_delta(1.0, 1.0)
    assert hedged and delta == 0.0
    delta, hedged = residual_delta(1.0, 0.7)
    assert not hedged
    assert delta == pytest.approx(0.3)


# --- artifact promotion review -------------------------------------------


def _paper_candidate_artifacts(tmp_path, *, tamper: bool = False):
    dataset = tmp_path / "real.json"
    snaps = synthetic_funding_snapshots(periods=30, seed=9)
    import dataclasses

    write_snapshots_json(dataset, [dataclasses.replace(s, data_source="real") for s in snaps])
    manifest = build_dataset_manifest(dataset).to_dict()
    payload = {
        "decision": "PAPER_CANDIDATE",
        "data_source": "real",
        "dataset_manifest": manifest,
        "walk_forward": [{"test_total_return": 0.01}],
        "test_metrics": {
            "sharpe_per_period": 0.25,
            "observations": 200,
            "skewness": 0.0,
            "kurtosis": 3.0,
        },
    }
    results = tmp_path / "results.json"
    atomic_write_json(results, payload)
    append_trial_record(
        tmp_path,
        build_trial_record(
            source="test", strategy="carry", strategy_params={}, run_id="r",
            dataset_sha=str(manifest["byte_sha256"]), test_sharpe_per_period=0.25,
        ),
    )
    if tamper:
        raw = bytearray(dataset.read_bytes())
        raw[len(raw) // 2] ^= 0x01
        dataset.write_bytes(bytes(raw))
    return results


def test_promotion_review_accepts_complete_bound_artifacts(tmp_path):
    results = _paper_candidate_artifacts(tmp_path)
    review = evaluate_carry_promotion(results)
    assert review["status"] == "PAPER_CANDIDATE", review["failures"]
    assert review["real_money_authorized"] is False


def test_promotion_review_rejects_tampered_dataset(tmp_path):
    results = _paper_candidate_artifacts(tmp_path, tamper=True)
    review = evaluate_carry_promotion(results)
    assert review["status"] == "REJECTED"
    assert any("bytes changed" in f for f in review["failures"])


def test_promotion_review_rejects_non_candidate_and_empty_walkforward(tmp_path):
    results = _paper_candidate_artifacts(tmp_path)
    payload = json.loads(results.read_text())
    payload["decision"] = "REJECTED"
    payload["walk_forward"] = []
    atomic_write_json(results, payload)
    review = evaluate_carry_promotion(results)
    assert review["status"] == "REJECTED"
    assert any("not PAPER_CANDIDATE" in f for f in review["failures"])
    assert any("walk-forward" in f for f in review["failures"])


def test_promotion_review_rejects_weak_psr(tmp_path):
    results = _paper_candidate_artifacts(tmp_path)
    payload = json.loads(results.read_text())
    payload["test_metrics"]["sharpe_per_period"] = 0.01  # weak
    atomic_write_json(results, payload)
    review = evaluate_carry_promotion(results)
    assert review["status"] == "REJECTED"
    assert any("PSR" in f for f in review["failures"])


def test_promotion_review_rejects_yaml_results(tmp_path):
    import yaml

    results = tmp_path / "results.json"
    results.write_text(yaml.safe_dump({"decision": "PAPER_CANDIDATE"}), encoding="utf-8")
    review = evaluate_carry_promotion(results)
    assert review["status"] == "REJECTED"
    assert any("strict JSON" in f for f in review["failures"])
