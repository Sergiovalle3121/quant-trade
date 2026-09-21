"""Tests for the measured-cost-drag criterion.

A raw turnover cap encodes a cost level; this criterion reads the drag the
cost model actually charged. Three properties keep it honest: it is additive
to ``max_turnover`` and never replaces it, it is off unless a config turns it
on, and it fails closed when no measured drag was reported.
"""

from __future__ import annotations

from quant_trade.research.candidate import SelectionCriteria
from quant_trade.research.selection import _reasons


def _result(drag: float | None, turnover: float = 1.0) -> dict:
    metrics = {
        "sharpe": 1.0,
        "max_drawdown": -0.10,
        "turnover": turnover,
        "trade_count": 100,
    }
    if drag is not None:
        metrics["cost_drag_bps_per_year"] = drag
    return {
        "strategy": "s",
        "universe": ["A"],
        "test_metrics": metrics,
        "train_metrics": {"sharpe": 1.0},
        "comparison_test": {"excess_return": 0.1, "benchmark_max_drawdown": -0.2},
        "test_months": 24,
        "robustness": {"cost_sensitivity_pass": True},
    }


def _drag_reasons(criteria: SelectionCriteria, result: dict) -> list[str]:
    return [r for r in _reasons(result, criteria) if "cost drag" in r or "turnover" in r]


def test_disabled_by_default_so_existing_configs_are_unchanged() -> None:
    assert SelectionCriteria().max_cost_drag_bps_per_year is None
    assert _drag_reasons(SelectionCriteria(), _result(None)) == []
    assert _drag_reasons(SelectionCriteria(), _result(9_999.0)) == []


def test_the_cap_is_additive_to_turnover_not_a_replacement() -> None:
    criteria = SelectionCriteria(max_turnover=3.0, max_cost_drag_bps_per_year=500.0)
    reasons = _drag_reasons(criteria, _result(800.0, turnover=12.0))
    assert "missing or excessive turnover" in reasons
    assert any("800 bps/year exceeds the maximum 500" in r for r in reasons)
    assert len(reasons) == 2


def test_a_strategy_under_budget_passes() -> None:
    criteria = SelectionCriteria(max_turnover=100.0, max_cost_drag_bps_per_year=500.0)
    assert _drag_reasons(criteria, _result(499.0, turnover=12.0)) == []


def test_a_missing_drag_fails_closed() -> None:
    """No cost model is not a free cost model."""
    criteria = SelectionCriteria(max_turnover=100.0, max_cost_drag_bps_per_year=500.0)
    assert _drag_reasons(criteria, _result(None)) == [
        "measured cost drag missing; cannot judge annual cost drag"
    ]
