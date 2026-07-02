from datetime import datetime, timedelta

import pandas as pd

from quant_trade.core.models import Trade
from quant_trade.metrics.performance import calculate_performance


def test_metrics_handle_empty_data() -> None:
    metrics = calculate_performance(pd.DataFrame(), [])
    assert metrics["total_return"] == 0.0
    assert metrics["number_of_trades"] == 0


def test_metrics_handle_normal_case() -> None:
    dates = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(4)]
    equity = pd.DataFrame(
        {
            "timestamp": dates,
            "equity": [100.0, 101.0, 99.0, 104.0],
            "position_value": [0, 50, 50, 0],
        }
    )
    trades = [
        Trade(
            entry_time=dates[0],
            exit_time=dates[-1],
            quantity=1,
            entry_price=100,
            exit_price=104,
            pnl=4,
            return_pct=0.04,
        )
    ]
    metrics = calculate_performance(equity, trades)
    assert metrics["total_return"] == 0.04
    assert metrics["number_of_trades"] == 1
    assert metrics["win_rate"] == 1.0
    assert metrics["max_drawdown"] < 0
