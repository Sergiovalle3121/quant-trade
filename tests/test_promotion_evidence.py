import json

from quant_trade.research.candidate import CandidateStrategy
from quant_trade.research.promotion import evaluate_promotion


def _candidate(**overrides):
    values = {
        "candidate_id": "candidate-1",
        "name": "candidate",
        "strategy_name": "time_series_momentum",
        "strategy_params": {},
        "universe": ["SPY"],
        "benchmark": "equal_weight_universe",
        "data_start": "2020-01-01",
        "data_end": "2024-01-01",
        "research_run_dir": "unused",
        "selected_at_utc": "2026-01-01T00:00:00+00:00",
        "selected_by": "test",
        "approval_notes": "Reviewed for simulated paper trading.",
        "estimated_turnover": 1.0,
    }
    values.update(overrides)
    return CandidateStrategy(**values)


def _risk():
    return {
        "kill_switch_enabled": True,
        "max_drawdown": 0.20,
        "max_turnover": 3.0,
        "min_net_excess_return": 0.0,
        "min_quantity_fill_rate": 0.90,
        "max_partial_or_expired_order_rate": 0.10,
    }


def _write_results(
    path,
    *,
    excess=0.05,
    cost_pass=True,
    fill_rate=0.98,
    incomplete_rate=0.02,
):
    path.mkdir(exist_ok=True)
    (path / "results.json").write_text(
        json.dumps(
            {
                "comparison_test": {"excess_return": excess},
                "test_metrics": {"max_drawdown": -0.10},
                "robustness": {"cost_sensitivity_pass": cost_pass},
                "execution_test": {
                    "quantity_fill_rate": fill_rate,
                    "partial_or_expired_order_rate": incomplete_rate,
                },
                "test_range": ["2023-01-01", "2024-01-01"],
            }
        ),
        encoding="utf-8",
    )


def test_promotion_passes_only_with_real_economic_evidence(tmp_path):
    _write_results(tmp_path)
    report = evaluate_promotion(_candidate(), tmp_path, _risk())
    assert report.overall_status == "pass"
    assert not report.blocking_issues


def test_promotion_blocks_negative_after_cost_excess_and_failed_stress(tmp_path):
    _write_results(tmp_path, excess=-0.01, cost_pass=False)
    report = evaluate_promotion(_candidate(), tmp_path, _risk())
    assert report.overall_status == "fail"
    failed = {check.name for check in report.checks if check.status == "fail"}
    assert "beats_benchmark_after_costs" in failed
    assert "cost_sensitivity_ok" in failed


def test_promotion_blocks_missing_results_and_prior_rejections(tmp_path):
    report = evaluate_promotion(
        _candidate(status="rejected", rejection_reasons=["insufficient OOS evidence"]),
        tmp_path,
        _risk(),
    )
    assert report.overall_status == "fail"
    failed = {check.name for check in report.checks if check.status == "fail"}
    assert "candidate_not_rejected" in failed
    assert "selection_rejections_empty" in failed
    assert "results_json_readable" in failed


def test_promotion_blocks_unexecutable_oos_orders(tmp_path):
    _write_results(tmp_path, fill_rate=0.75, incomplete_rate=0.40)
    report = evaluate_promotion(_candidate(), tmp_path, _risk())
    assert report.overall_status == "fail"
    failed = {check.name for check in report.checks if check.status == "fail"}
    assert "execution_fill_rate_ok" in failed
    assert "execution_completion_rate_ok" in failed


def test_promotion_can_require_walk_forward_overfitting_evidence(tmp_path):
    _write_results(tmp_path)
    risk = {
        **_risk(),
        "require_overfitting_evidence": True,
        "max_walk_forward_pbo": 0.50,
        "min_walk_forward_windows": 4,
    }
    missing = evaluate_promotion(_candidate(), tmp_path, risk)
    assert missing.overall_status == "fail"

    payload = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    payload["overfitting_evidence"] = {
        "decision": "PASS",
        "walk_forward_pbo": 0.25,
        "windows": 6,
    }
    (tmp_path / "results.json").write_text(json.dumps(payload), encoding="utf-8")
    passed = evaluate_promotion(_candidate(), tmp_path, risk)
    assert passed.overall_status == "pass"
