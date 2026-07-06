from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.data.panel import calculate_returns, pivot_close
from quant_trade.research.signals.base import rebalance_mask, weights_to_long
from quant_trade.research.signals.trend import _cap_equal


def simple_mean_reversion_etf(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """ETF baseline: buy short-term weakness in longer-term uptrends.

    Not suitable for thin assets or live use.
    """
    sw = int(params.get("short_window", 5))
    z = float(params.get("z_entry", -1.0))
    tw = int(params.get("trend_window", 100))
    max_w = float(params.get("max_weight_per_asset", 1.0))
    close = pivot_close(data)
    r = calculate_returns(close).rolling(sw).sum()
    mu = r.rolling(tw).mean()
    sig = r.rolling(tw).std()
    score = (r - mu) / sig
    mask = (score < z) & (close > close.rolling(tw).mean())
    rb = rebalance_mask(close.index, str(params.get("rebalance_frequency", "weekly")))
    return weights_to_long(_cap_equal(mask, max_w), rebalance=rb)
