from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.data.panel import pivot_close
from quant_trade.research.signals.base import rebalance_mask, weights_to_long
from quant_trade.research.signals.trend import _cap_equal


def time_series_momentum(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Hold assets with positive trailing returns.

    Baseline only; sensitive to lookback and costs.
    """
    lb = int(params.get("lookback_days", 126))
    max_w = float(params.get("max_weight_per_asset", 1.0))
    freq = str(params.get("rebalance_frequency", "monthly"))
    if lb < 1:
        raise ValueError("lookback_days must be >= 1")
    close = pivot_close(data)
    mom = close / close.shift(lb) - 1
    mask = mom > 0
    return weights_to_long(_cap_equal(mask, max_w), rebalance=rebalance_mask(close.index, freq))


def cross_sectional_momentum(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Rank assets by trailing return and hold leaders; can fail when leadership reverses."""
    lb = int(params.get("lookback_days", 126))
    max_w = float(params.get("max_weight_per_asset", 1.0))
    freq = str(params.get("rebalance_frequency", "monthly"))
    close = pivot_close(data)
    mom = close / close.shift(lb) - 1
    top_n = params.get("top_n")
    top_q = params.get("top_quantile")
    ranks = mom.rank(axis=1, ascending=False, method="first")
    if top_n is not None:
        mask = ranks <= int(top_n)
    elif top_q is not None:
        mask = ranks.le(max(1, int(len(close.columns) * float(top_q))))
    else:
        mask = ranks <= max(1, len(close.columns) // 2)
    mask = mask & mom.notna()
    return weights_to_long(_cap_equal(mask, max_w), rebalance=rebalance_mask(close.index, freq))
