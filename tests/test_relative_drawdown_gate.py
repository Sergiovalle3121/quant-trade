"""Tests for the benchmark-relative drawdown criterion.

The criterion exists because an absolute drawdown threshold silently encodes an
asset class. These tests pin the three properties that make it honest: it is
additive (never replaces the absolute bar), it fails closed when the benchmark
drawdown is missing, and it is genuinely benchmark-anchored — which on the
committed ETF data makes it LOOSER, not stricter. That last one is asserted
rather than described, so nobody has to take the claim on trust.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.research.candidate import SelectionCriteria
from quant_trade.research.selection import _reasons

ETF_RUNS = Path("docs/real_data_evidence/runs")


def _result(strategy_dd: float, benchmark_dd: float) -> dict:
    """A result that passes everything except, possibly, the drawdown gates."""
    return {
        "strategy": "s",
        "universe": ["A"],
        "test_metrics": {
            "sharpe": 1.0,
            "max_drawdown": -abs(strategy_dd),
            "turnover": 1.0,
            "trade_count": 100,
        },
        "train_metrics": {"sharpe": 1.0},
        "comparison_test": {
            "excess_return": 0.1,
            "benchmark_max_drawdown": -abs(benchmark_dd),
        },
        "test_months": 24,
        "robustness": {"cost_sensitivity_pass": True},
    }


def _dd_reasons(criteria: SelectionCriteria, result: dict) -> list[str]:
    return [r for r in _reasons(result, criteria) if "drawdown" in r]


def test_disabled_by_default_so_existing_configs_are_unchanged() -> None:
    assert SelectionCriteria().max_drawdown_ratio_vs_benchmark is None
    criteria = SelectionCriteria(max_test_drawdown=0.20)
    assert _dd_reasons(criteria, _result(0.30, 0.80)) == ["missing or excessive test drawdown"]


def test_the_ratio_is_additive_not_a_replacement() -> None:
    # 30% drawdown against a 25% benchmark: fails BOTH, and says so twice.
    criteria = SelectionCriteria(
        max_test_drawdown=0.20, max_drawdown_ratio_vs_benchmark=1.0
    )
    reasons = _dd_reasons(criteria, _result(0.30, 0.25))
    assert len(reasons) == 2
    assert any("excessive test drawdown" in r for r in reasons)
    assert any("1.20x the benchmark" in r for r in reasons)


def test_ratio_passes_when_the_strategy_fell_less_than_the_benchmark() -> None:
    criteria = SelectionCriteria(
        max_test_drawdown=1.0, max_drawdown_ratio_vs_benchmark=1.0
    )
    assert _dd_reasons(criteria, _result(0.60, 0.766)) == []
    assert _dd_reasons(criteria, _result(0.80, 0.766)) != []


def test_a_missing_benchmark_drawdown_fails_closed() -> None:
    """An unmeasurable ratio must not read as a cleared gate."""
    criteria = SelectionCriteria(
        max_test_drawdown=1.0, max_drawdown_ratio_vs_benchmark=1.0
    )
    reasons = _dd_reasons(criteria, _result(0.30, 0.0))
    assert reasons == ["benchmark drawdown missing; cannot judge relative drawdown"]


def test_zero_strategy_drawdown_is_not_treated_as_missing() -> None:
    criteria = SelectionCriteria(max_test_drawdown=0.20)
    assert _dd_reasons(criteria, _result(0.0, 0.20)) == []


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), "not-a-number", None])
def test_invalid_strategy_drawdown_fails_closed(invalid) -> None:
    criteria = SelectionCriteria(max_test_drawdown=0.20)
    result = _result(0.10, 0.20)
    result["test_metrics"]["max_drawdown"] = invalid
    assert _dd_reasons(criteria, result) == ["missing or excessive test drawdown"]


@pytest.mark.parametrize(
    ("section", "metric", "expected_reason"),
    [
        ("test_metrics", "sharpe", "missing or insufficient test Sharpe"),
        ("test_metrics", "turnover", "missing or excessive turnover"),
        ("comparison_test", "excess_return", "missing or insufficient excess return"),
    ],
)
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), "invalid"])
def test_non_finite_or_malformed_selection_metrics_fail_closed(
    section, metric, expected_reason, invalid
) -> None:
    result = _result(0.10, 0.20)
    result[section][metric] = invalid
    assert expected_reason in _reasons(result, SelectionCriteria())


@pytest.mark.skipif(not ETF_RUNS.exists(), reason="committed ETF artifacts absent")
def test_on_the_etf_data_the_ratio_gate_is_looser_than_the_absolute_one() -> None:
    """The uncomfortable direction, asserted against the committed artifacts.

    Swapping an absolute 20% bar for a 1.0x benchmark ratio is not a
    tightening dressed up as a translation. On the ETF panel it admits four
    strategies the absolute bar rejected. The crypto gate is defensible on the
    grounds that 20% is unanswerable against a 76.6% benchmark — not on the
    grounds that the replacement is stricter, because it is not.
    """
    absolute_failures, ratio_failures = [], []
    for results_path in sorted(ETF_RUNS.rglob("results.json")):
        payload = json.loads(results_path.read_text(encoding="utf-8"))
        comparison = payload.get("comparison_test") or {}
        strategy_dd = abs(comparison.get("strategy_max_drawdown") or 0.0)
        benchmark_dd = abs(comparison.get("benchmark_max_drawdown") or 0.0)
        if not benchmark_dd:
            continue
        name = payload.get("experiment_name", results_path.parent.name)
        if strategy_dd > 0.20:
            absolute_failures.append(name)
        if strategy_dd / benchmark_dd > 1.0:
            ratio_failures.append(name)
    assert len(absolute_failures) == 5
    assert len(ratio_failures) == 1
    assert ratio_failures[0].startswith("equal_weight_quarterly")
    assert set(ratio_failures) < set(absolute_failures)
