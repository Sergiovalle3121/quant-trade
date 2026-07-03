"""Conservative OHLCV-only execution price simulation models."""
from __future__ import annotations

import pandas as pd

from quant_trade.tca.benchmark_prices import vwap_proxy


def execution_price_for_row(row: pd.Series, model: str, side: str, spread_bps: float) -> float:
    base = {
        "next_open": row["open"],
        "next_close": row["close"],
        "vwap_proxy": vwap_proxy(row),
        "spread_adjusted_open": row["open"],
        "volume_participation_limited": row["open"],
        "partial_fill_model": row["open"],
        "adverse_gap_model": (
            max(row["open"], row["close"])
            if side == "buy"
            else min(row["open"], row["close"])
        ),
    }.get(model, row["open"])
    adjustment = float(base) * spread_bps / 10000.0 / 2.0
    return float(base + adjustment if side == "buy" else base - adjustment)
