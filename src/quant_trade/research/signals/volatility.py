from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.data.panel import calculate_returns, pivot_close
from quant_trade.research.signals.base import rebalance_mask, weights_to_long


def volatility_scaled_momentum(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Positive momentum weighted by inverse realized volatility.

    Volatility estimates can be noisy and unstable.
    """
    lb = int(params.get("lookback_days", 126))
    vw = int(params.get("volatility_window", 63))
    max_w = float(params.get("max_weight_per_asset", 1.0))
    close = pivot_close(data)
    ret = calculate_returns(close)
    mom = close / close.shift(lb) - 1
    vol = ret.rolling(vw).std()
    raw = (1 / vol).where(mom > 0).replace([float("inf")], pd.NA)
    weights = raw.div(raw.sum(axis=1), axis=0).fillna(0).clip(upper=max_w)
    rb = rebalance_mask(close.index, str(params.get("rebalance_frequency", "monthly")))
    rb_frame = pd.DataFrame({column: rb for column in weights.columns}, index=weights.index)
    weights = weights.where(rb_frame, 0.0)
    return weights_to_long(weights)
