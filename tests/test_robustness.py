from quant_trade.backtest.costs import CostModel
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.research.benchmarks import run_benchmark
from quant_trade.research.robustness import (
    cost_sensitivity,
    parameter_sensitivity_grid,
    rolling_metrics,
    subperiod_analysis,
)


def test_robustness_functions():
    data = load_canonical_dataset("examples/data/sample_multi_asset_ohlcv.csv")
    cs = cost_sensitivity(data, "time_series_momentum", {"lookback_days": 20}, 10000)
    assert len(cs) == 4
    grid = parameter_sensitivity_grid(
        data, "time_series_momentum", {"lookback_days": [10, 20]}, 10000, CostModel()
    )
    assert len(grid) == 2
    assert not rolling_metrics(
        run_benchmark(data, {"type": "cash"}, 10000, CostModel()).equity_curve
    ).empty
    assert not subperiod_analysis(
        run_benchmark(data, {"type": "cash"}, 10000, CostModel()).equity_curve
    ).empty
