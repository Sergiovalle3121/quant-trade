from datetime import datetime, timedelta

import pandas as pd
import pytest

from quant_trade.core.models import Trade
from quant_trade.metrics.performance import calculate_performance, downside_deviation


def test_metrics_handle_empty_data() -> None:
    metrics = calculate_performance(pd.DataFrame(), [])
    assert metrics["total_return"] == pytest.approx(0.0)
    assert metrics["number_of_trades"] == 0
    assert metrics["trade_count"] == 0


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
    assert metrics["total_return"] == pytest.approx(0.04)
    assert metrics["number_of_trades"] == 1
    assert metrics["trade_count"] == 1
    assert metrics["win_rate"] == pytest.approx(1.0)
    assert metrics["max_drawdown"] < 0


def test_downside_deviation_uses_all_observations_and_zero_mar() -> None:
    returns = pd.Series([0.02, -0.01, 0.03, -0.01])
    assert downside_deviation(returns, periods=1.0) == pytest.approx((0.0002 / 4) ** 0.5)


def test_cagr_uses_elapsed_calendar_time() -> None:
    equity = pd.DataFrame(
        {
            "timestamp": [datetime(2023, 1, 1), datetime(2024, 1, 1)],
            "equity": [100.0, 110.0],
        }
    )
    assert calculate_performance(equity, [])["cagr"] == pytest.approx(0.10, rel=2e-3)
