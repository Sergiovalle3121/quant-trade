"""Tests for the conservative promotion V2 gate (recompute-from-artifacts)."""

from __future__ import annotations

import json

import numpy as np

from quant_trade.research.candidate import CandidateStrategy
from quant_trade.research.ledger import append_trial, append_trial_record, build_trial_record
from quant_trade.research.promotion_v2 import (
    PromotionPolicyV2,
    evaluate_promotion_v2,
)

POLICY = PromotionPolicyV2.from_yaml("configs/selection/conservative_v2.yaml")


def _candidate(notes: str = "Reviewed for simulated paper trading."):
    return CandidateStrategy(
        candidate_id="cand-1",
        name="cand",
        strategy_name="tsmom",
        strategy_params={"lookback_days": 21},
        universe=["AAA", "BBB"],
        benchmark="equal_weight_universe",
        data_start="2020-01-01",
        data_end="2024-01-01",
        research_run_dir="unused",
        selected_at_utc="2026-01-01T00:00:00+00:00",
        selected_by="test",
        approval_notes=notes,
    )


def _valid_results(**overrides) -> dict:
    payload = {
        "test_metrics": {
            "sharpe": 1.2,
            "sharpe_per_period": 0.20,
            "observations": 200,
            "skewness": 0.0,
            "kurtosis": 3.0,
            "max_drawdown": -0.10,
            "turnover": 1.5,
            "trade_count": 40,
        },
        "comparison_test": {"excess_return": 0.05},
        "robustness": {"cost_sensitivity_pass": True, "subperiod_pass": True},
        "bootstrap": {"available": True, "total_return_lower_positive": True},
        "execution_test": {"quantity_fill_rate": 0.98, "partial_or_expired_order_rate": 0.02},
        "execution_policy": {"specified": True, "hash": "abc"},
        "dataset_binding": {"data_sha256": "deadbeef"},
        "test_range": ["2023-01-01", "2024-01-01"],
    }
    payload.update(overrides)
    return payload


def _write_run(outputs, results: dict, name: str = "exp_123"):
    run_dir = outputs / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(json.dumps(results), encoding="utf-8")
    return run_dir


def _seed_clean_ledger(outputs, n: int = 4):
    for i in range(n):
        append_trial_record(
            outputs,
            build_trial_record(
                source="test",
                strategy="tsmom",
                strategy_params={"lookback_days": 21 + i},
                run_id="r",
                dataset_sha="deadbeef",
                test_sharpe_per_period=0.04 + 0.01 * i,
            ),
        )


# --- happy path -----------------------------------------------------------


def test_fully_valid_candidate_reaches_paper_candidate_only(tmp_path):
    run_dir = _write_run(tmp_path, _valid_results())
    _seed_clean_ledger(tmp_path)
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert decision.status == "paper_candidate", decision.failed_gates
    assert decision.failed_gates == []
    assert decision.real_money_authorized is False
    assert decision.recomputed["recomputed_dsr"] >= 0.95


# --- fail closed ----------------------------------------------------------


def test_missing_results_fails_closed(tmp_path):
    run_dir = tmp_path / "empty_run"
    run_dir.mkdir()
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert decision.status == "rejected"
    assert "results_json_readable" in decision.failed_gates


def test_missing_ledger_fails(tmp_path):
    run_dir = _write_run(tmp_path, _valid_results())
    # no ledger seeded
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert decision.status == "rejected"
    assert "ledger_integrity" in decision.failed_gates


def test_missing_dataset_sha_fails(tmp_path):
    results = _valid_results()
    del results["dataset_binding"]
    run_dir = _write_run(tmp_path, results)
    _seed_clean_ledger(tmp_path)
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert "dataset_binding_present" in decision.failed_gates


def test_missing_bootstrap_fails(tmp_path):
    results = _valid_results(bootstrap={"available": False})
    run_dir = _write_run(tmp_path, results)
    _seed_clean_ledger(tmp_path)
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert "bootstrap_ci_positive" in decision.failed_gates


def test_missing_execution_policy_fails(tmp_path):
    results = _valid_results(execution_policy={"specified": False})
    run_dir = _write_run(tmp_path, results)
    _seed_clean_ledger(tmp_path)
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert "execution_policy_specified" in decision.failed_gates


def test_in_sample_only_fails(tmp_path):
    # strong nothing OOS: weak Sharpe, negative excess
    results = _valid_results()
    results["test_metrics"]["sharpe"] = 0.1
    results["test_metrics"]["sharpe_per_period"] = 0.01
    results["comparison_test"]["excess_return"] = -0.02
    run_dir = _write_run(tmp_path, results)
    _seed_clean_ledger(tmp_path)
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert decision.status == "rejected"
    assert "oos_sharpe" in decision.failed_gates
    assert "net_excess_return_positive" in decision.failed_gates


def test_low_fill_rate_fails(tmp_path):
    results = _valid_results(
        execution_test={"quantity_fill_rate": 0.70, "partial_or_expired_order_rate": 0.35}
    )
    run_dir = _write_run(tmp_path, results)
    _seed_clean_ledger(tmp_path)
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert "fill_rate" in decision.failed_gates
    assert "incomplete_order_rate" in decision.failed_gates


def test_deflated_sharpe_below_threshold_fails(tmp_path):
    # Inflate the ledger with many high-variance trials so the expected-max
    # Sharpe threshold dwarfs the candidate and DSR drops below 0.95.
    run_dir = _write_run(tmp_path, _valid_results())
    rng = np.random.default_rng(1)
    for _ in range(500):
        append_trial_record(
            tmp_path,
            build_trial_record(
                source="test",
                strategy="tsmom",
                strategy_params={"lookback_days": int(rng.integers(5, 200))},
                run_id="r",
                dataset_sha="deadbeef",
                test_sharpe_per_period=float(rng.normal(0, 0.5)),
            ),
        )
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert decision.status == "rejected"
    assert "deflated_sharpe" in decision.failed_gates
    assert decision.recomputed["recomputed_dsr"] < 0.95


def test_corrupt_ledger_blocks_promotion(tmp_path):
    run_dir = _write_run(tmp_path, _valid_results())
    _seed_clean_ledger(tmp_path)
    # append a corrupt line directly
    (tmp_path / "trial_ledger.jsonl").open("a", encoding="utf-8").write("{broken json\n")
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    assert "ledger_integrity" in decision.failed_gates


def test_missing_approval_notes_fails(tmp_path):
    run_dir = _write_run(tmp_path, _valid_results())
    _seed_clean_ledger(tmp_path)
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate(notes="  "))
    assert "human_approval_notes" in decision.failed_gates


def test_stored_flags_are_not_trusted(tmp_path):
    # Inject a bogus DSR flag; the gate must ignore it and recompute.
    results = _valid_results()
    results["test_metrics"]["dsr"] = 0.999
    results["test_metrics"]["sharpe_per_period"] = 0.01  # true evidence is weak
    results["test_metrics"]["sharpe"] = 0.05
    run_dir = _write_run(tmp_path, results)
    _seed_clean_ledger(tmp_path)
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    # despite the friendly stored flag, recomputed DSR is weak -> rejected
    assert decision.status == "rejected"
    assert "deflated_sharpe" in decision.failed_gates


def test_legacy_ledger_rows_still_supported(tmp_path):
    run_dir = _write_run(tmp_path, _valid_results())
    append_trial(tmp_path, {"source": "old", "test_sharpe_per_period": 0.05})
    append_trial(tmp_path, {"source": "old", "test_sharpe_per_period": 0.06})
    decision = evaluate_promotion_v2(run_dir, POLICY, candidate=_candidate())
    # legacy rows are intact (not corrupt), so integrity passes
    assert "ledger_integrity" not in decision.failed_gates
