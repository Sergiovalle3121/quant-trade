"""Parity report driven by real backtest-engine output (no fixtures)."""

from __future__ import annotations

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.paper.parity import compare_executions
from quant_trade.paper.parity_adapters import execution_record_from_backtest
from quant_trade.research.strategy_registry import get_research_signal_model

DATA = "examples/data/sample_multi_asset_ohlcv.csv"


def _run(cost: CostModel):
    data = load_canonical_dataset(DATA)
    model = get_research_signal_model("time_series_momentum")
    weights = model.generate(data, {"lookback_days": 20})
    return run_multi_asset_backtest(data, weights, 10_000, cost)


def test_record_from_backtest_has_expected_shape():
    result = _run(CostModel())
    record = execution_record_from_backtest(result, source="backtest")
    assert record.source == "backtest"
    assert record.fills  # trades became fills
    assert record.final_equity > 0
    assert record.final_positions  # ended with positions


def test_backtest_reconciles_with_itself():
    result = _run(CostModel())
    a = execution_record_from_backtest(result, source="backtest")
    b = execution_record_from_backtest(result, source="simulated_paper")
    report = compare_executions(a, b)
    assert report.reconciled
    assert report.equity_drift == 0.0


def test_different_costs_diverge_on_equity_and_fees():
    cheap = execution_record_from_backtest(_run(CostModel()), source="backtest")
    pricey = execution_record_from_backtest(
        _run(CostModel(percentage_commission=0.01, slippage_bps=20, spread_bps=10)),
        source="simulated_paper",
    )
    report = compare_executions(cheap, pricey)
    assert not report.reconciled
    diverged = {c.field for c in report.comparisons if c.status == "divergence"}
    # higher costs move fees and final equity
    assert "total_fees" in diverged or "final_equity" in diverged
