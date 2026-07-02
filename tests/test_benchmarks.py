import pytest

from quant_trade.backtest.costs import CostModel
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.research.benchmarks import compare_to_benchmark, run_benchmark


def test_benchmarks():
    data = load_canonical_dataset("examples/data/sample_multi_asset_ohlcv.csv")
    spy = run_benchmark(data, {"type": "buy_and_hold_symbol", "symbol": "SPY"}, 10000, CostModel())
    ew = run_benchmark(data, {"type": "equal_weight_universe"}, 10000, CostModel())
    assert (
        compare_to_benchmark(spy.metrics, ew.metrics)["strategy_total_return"]
        == spy.metrics["total_return"]
    )
    with pytest.raises(ValueError):
        run_benchmark(data, {"type": "buy_and_hold_symbol", "symbol": "NOPE"}, 10000, CostModel())
