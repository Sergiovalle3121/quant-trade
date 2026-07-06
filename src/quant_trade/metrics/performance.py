"""Robust performance metrics for research backtests."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.core.models import Trade

TRADING_DAYS = 252
_SECONDS_PER_YEAR = 365.25 * 24 * 3600


def periods_per_year(timestamps: Any) -> float:
    """Infer bars per year from observed bar density.

    Uses (bar count - 1) / span-in-years so a 252-bar/year equity calendar,
    a 365-day crypto calendar, and intraday bars all annualize correctly.
    Falls back to ``TRADING_DAYS`` when timestamps are missing or too sparse.
    """
    ts = pd.to_datetime(pd.Series(timestamps), utc=True, errors="coerce").dropna()
    if len(ts) < 3:
        return float(TRADING_DAYS)
    ts = ts.sort_values()
    span_seconds = (ts.iloc[-1] - ts.iloc[0]).total_seconds()
    if span_seconds <= 0:
        return float(TRADING_DAYS)
    return max(1.0, (len(ts) - 1) * _SECONDS_PER_YEAR / span_seconds)


def calculate_performance(equity_curve: pd.DataFrame, trades: list[Trade]) -> dict[str, Any]:
    """Calculate performance metrics while safely handling sparse or empty data."""
    if equity_curve.empty or "equity" not in equity_curve:
        return _empty_metrics()
    equity = pd.to_numeric(equity_curve["equity"], errors="coerce").dropna()
    if len(equity) < 1 or equity.iloc[0] <= 0:
        return _empty_metrics()

    ppy = (
        periods_per_year(equity_curve["timestamp"])
        if "timestamp" in equity_curve
        else float(TRADING_DAYS)
    )
    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1)
    years = max(len(equity) / ppy, 1 / ppy)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) if len(equity) > 1 else 0.0
    volatility = float(returns.std(ddof=0) * math.sqrt(ppy)) if len(returns) > 1 else 0.0
    downside = returns[returns < 0]
    downside_vol = float(downside.std(ddof=0) * math.sqrt(ppy)) if len(downside) > 1 else 0.0
    sharpe = float((returns.mean() * ppy) / volatility) if volatility > 0 else 0.0
    sortino = float((returns.mean() * ppy) / downside_vol) if downside_vol > 0 else 0.0
    drawdown = equity / equity.cummax() - 1
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    win_rate = float(sum(trade.pnl > 0 for trade in trades) / len(trades)) if trades else 0.0
    exposure = _exposure(equity_curve)
    return {
        "total_return": total_return,
        "cagr": cagr,
        "volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "number_of_trades": len(trades),
        "trade_count": len(trades),
        "exposure": exposure,
    }


def _exposure(equity_curve: pd.DataFrame) -> float:
    if "position_value" not in equity_curve or equity_curve.empty:
        return 0.0
    invested = pd.to_numeric(equity_curve["position_value"], errors="coerce").fillna(0) > 0
    return float(invested.mean())


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_return": 0.0,
        "cagr": 0.0,
        "volatility": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "number_of_trades": 0,
        "trade_count": 0,
        "exposure": 0.0,
    }
