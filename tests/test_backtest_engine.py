from quant_trade.backtest.engine import BacktestEngine
from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.risk.risk_manager import RiskManager
from quant_trade.strategies.sma_crossover import SmaCrossoverStrategy


def test_backtest_runs_end_to_end() -> None:
    data = load_ohlcv_csv("examples/data/sample_ohlcv.csv")
    result = BacktestEngine(initial_cash=10_000).run(data, SmaCrossoverStrategy())
    assert not result.equity_curve.empty
    assert result.equity_curve["equity"].iloc[0] > 0
    assert "total_return" in result.metrics


def test_risk_manager_prevents_oversizing() -> None:
    risk = RiskManager(max_position_pct=0.2, max_trade_pct=0.1)
    quantity = risk.size_buy_quantity(
        cash=10_000, equity=10_000, price=100, current_position_value=0
    )
    assert quantity == 10
    no_capacity = risk.size_buy_quantity(
        cash=10_000, equity=10_000, price=100, current_position_value=2_000
    )
    assert no_capacity == 0
