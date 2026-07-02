import pytest

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.research.signals.trend import equal_weight_buy_and_hold

DATA = "examples/data/sample_multi_asset_ohlcv.csv"


def test_backtest_outputs_and_costs():
    data = load_canonical_dataset(DATA).query("symbol in ['SPY','QQQ']")
    w = equal_weight_buy_and_hold(data, {"max_weight_per_asset": 0.5})
    a = run_multi_asset_backtest(data, w, 10000, CostModel())
    b = run_multi_asset_backtest(data, w, 10000, CostModel(percentage_commission=0.01))
    assert {
        "timestamp",
        "equity",
        "cash",
        "gross_exposure",
        "net_exposure",
        "turnover",
        "number_of_positions",
    } <= set(a.equity_curve.columns)
    assert not a.positions.empty and not a.trades.empty
    assert b.equity_curve.equity.iloc[-1] < a.equity_curve.equity.iloc[-1]
    bad = w.copy()
    bad["target_weight"] = 0.75
    with pytest.raises(ValueError):
        run_multi_asset_backtest(data, bad, 10000, CostModel(), max_weight_per_asset=0.5)
