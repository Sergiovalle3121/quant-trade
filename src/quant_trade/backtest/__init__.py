"""Deterministic backtesting components and convenience helpers."""

from __future__ import annotations

import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.engine import BacktestEngine, BacktestResult
from quant_trade.core.models import Trade
from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.metrics.performance import calculate_performance
from quant_trade.strategies.base import Strategy


def load_ohlcv(path: str) -> pd.DataFrame:
    """Load canonical timestamp-based OHLCV research data."""
    return load_ohlcv_csv(path)


def run_backtest(
    data: pd.DataFrame,
    strategy: Strategy,
    initial_cash: float = 10_000.0,
    cost_model: CostModel | None = None,
) -> BacktestResult:
    """Run the standard backtest engine with a strategy instance."""
    return BacktestEngine(initial_cash=initial_cash, cost_model=cost_model).run(data, strategy)


def calculate_metrics(
    equity_curve: pd.DataFrame,
    trades: list[Trade] | pd.DataFrame | None = None,
    initial_cash: float | None = None,
):
    """Backward-compatible metrics wrapper.

    ``initial_cash`` is accepted for older callers but metrics are derived from the
    equity curve itself.
    """
    del initial_cash
    if trades is None or isinstance(trades, pd.DataFrame):
        trade_list: list[Trade] = []
    else:
        trade_list = trades
    return calculate_performance(equity_curve, trade_list)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "CostModel",
    "calculate_metrics",
    "calculate_performance",
    "load_ohlcv",
    "load_ohlcv_csv",
    "run_backtest",
]
