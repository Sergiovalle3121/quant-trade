"""Benchmark-aware, low-turnover allocation baselines.

These are not alpha signals. They are cheap-to-hold allocations that exist to
test one question: does anything mechanically simple improve on the
equal-weight benchmark after realistic costs? Definitions and parameters were
fixed before any real-data results were observed (see
docs/BENCHMARK_AWARE_VERDICT.md).

Like every registered signal, weights at time t depend only on bars <= t
(enforced by the truncation-invariance tests).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.data.panel import calculate_returns, pivot_close
from quant_trade.research.signals.base import rebalance_mask, weights_to_long


def inverse_volatility(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Simple risk parity: weights proportional to inverse realized volatility.

    Fully invested by construction (weights normalized to sum to 1 before the
    per-asset cap); lower-volatility assets receive larger weights.
    """
    vw = int(params.get("volatility_window", 63))
    max_w = float(params.get("max_weight_per_asset", 1.0))
    freq = str(params.get("rebalance_frequency", "monthly"))
    if vw < 2:
        raise ValueError("volatility_window must be >= 2")
    close = pivot_close(data)
    vol = calculate_returns(close).rolling(vw).std()
    raw = (1.0 / vol).replace([float("inf")], pd.NA)
    weights = raw.div(raw.sum(axis=1), axis=0).fillna(0.0).clip(upper=max_w)
    return weights_to_long(weights, rebalance=rebalance_mask(close.index, freq))


def vol_targeted_equal_weight(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Equal weight scaled down when trailing portfolio volatility exceeds target.

    Scale = min(1, target / realized), so the portfolio never levers up; it
    only de-risks toward cash when the trailing equal-weight volatility runs
    above ``target_volatility``. Annualization assumes an equity daily
    calendar (sqrt(252)), matching the panel this experiment is defined on.
    """
    vw = int(params.get("volatility_window", 63))
    target = float(params.get("target_volatility", 0.10))
    max_w = float(params.get("max_weight_per_asset", 1.0))
    freq = str(params.get("rebalance_frequency", "monthly"))
    if vw < 2:
        raise ValueError("volatility_window must be >= 2")
    if target <= 0:
        raise ValueError("target_volatility must be positive")
    close = pivot_close(data)
    base = 1.0 / len(close.columns)
    portfolio_returns = calculate_returns(close).mean(axis=1)
    realized = portfolio_returns.rolling(vw).std() * (252.0**0.5)
    scale = (target / realized).clip(upper=1.0)
    weights = (
        pd.DataFrame(base, index=close.index, columns=close.columns)
        .mul(scale, axis=0)
        .fillna(0.0)
        .clip(upper=max_w)
    )
    return weights_to_long(weights, rebalance=rebalance_mask(close.index, freq))


def equal_weight_quarterly(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Equal weight reset on the first trading day of each calendar quarter.

    Control for rebalance friction against the daily-refreshed equal-weight
    benchmark: identical target portfolio, strictly fewer rebalances. Between
    rebalances the portfolio drifts (no rows emitted means "hold").

    ``rebalance_frequency`` (default ``quarterly``) exists so an accelerated
    paper-validation session can exercise the identical code path at a
    faster cadence; production configs leave it at the default.
    """
    max_w = float(params.get("max_weight_per_asset", 1.0))
    freq = str(params.get("rebalance_frequency", "quarterly"))
    close = pivot_close(data)
    weights = pd.DataFrame(
        min(1.0 / len(close.columns), max_w), index=close.index, columns=close.columns
    )
    return weights_to_long(weights, rebalance=rebalance_mask(close.index, freq))
