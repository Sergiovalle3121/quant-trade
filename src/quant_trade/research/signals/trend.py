from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.data.panel import pivot_close, validate_panel_schema
from quant_trade.research.signals.base import rebalance_mask, weights_to_long


def _cap_equal(mask: pd.DataFrame, max_w: float) -> pd.DataFrame:
    counts = mask.sum(axis=1).replace(0, pd.NA)
    w = mask.div(counts, axis=0).fillna(0.0)
    return w.clip(upper=max_w)


def equal_weight_buy_and_hold(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Long-only equal-weight baseline; not an alpha claim and ignores changing investability."""
    f = validate_panel_schema(data)
    close = pivot_close(f)
    min_bars = int(params.get("min_history_bars", 1))
    max_w = float(params.get("max_weight_per_asset", 1.0))
    eligible = close.notna() & (close.expanding().count() >= min_bars)
    return weights_to_long(_cap_equal(eligible, max_w))


def moving_average_trend_filter(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Hold assets above their SMA.

    Simple trend-following baseline with whipsaw/crowding limitations.
    """
    window = int(params.get("sma_window", 50))
    max_w = float(params.get("max_weight_per_asset", 1.0))
    freq = str(params.get("rebalance_frequency", "monthly"))
    if window < 2:
        raise ValueError("sma_window must be >= 2")
    close = pivot_close(data)
    mask = (close > close.rolling(window).mean()) & rebalance_mask(close.index, freq).values[
        :, None
    ]
    return weights_to_long(_cap_equal(mask, max_w))
