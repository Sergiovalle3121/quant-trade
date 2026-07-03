"""OHLCV-only spread proxies."""

import pandas as pd


def estimate_bid_ask_spread_proxy(
    frame: pd.DataFrame,
    floor_bps: float = 1.0,
    cap_bps: float = 100.0,
) -> pd.Series:
    close = frame["close"].abs().replace(0, pd.NA)
    proxy = ((frame["high"] - frame["low"]).abs() / close * 10000.0 * 0.10).fillna(
        floor_bps
    )
    return proxy.clip(lower=floor_bps, upper=cap_bps)
