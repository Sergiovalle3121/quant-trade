"""Past-only feature engineering for canonical OHLCV data."""

from __future__ import annotations

import pandas as pd

FEATURE_COLUMNS = [
    "return_1d_lag1",
    "return_5d_lag1",
    "rolling_volatility_10d",
    "rolling_momentum_10d",
    "sma_distance_20d",
    "volume_change_5d",
    "drawdown_from_20d_high",
    "market_return_1d_lag1",
    "cross_sectional_return_rank",
]


def generate_features(data: pd.DataFrame) -> pd.DataFrame:
    frame = data.sort_values(["symbol", "timestamp"]).copy()
    pieces = []
    market = (
        frame.pivot(index="timestamp", columns="symbol", values="close")
        .pct_change()
        .mean(axis=1)
        .shift(1)
    )
    for _, group in frame.groupby("symbol", sort=False):
        g = group.copy()
        close = g["close"].astype(float)
        volume = g["volume"].astype(float)
        ret = close.pct_change()
        g["return_1d_lag1"] = ret.shift(1)
        g["return_5d_lag1"] = close.pct_change(5).shift(1)
        g["rolling_volatility_10d"] = (
            ret.shift(1).rolling(10, min_periods=3).std(ddof=0)
        )
        g["rolling_momentum_10d"] = close.pct_change(10).shift(1)
        g["sma_distance_20d"] = (
            close.shift(1) / close.shift(1).rolling(20, min_periods=5).mean()
        ) - 1.0
        g["volume_change_5d"] = volume.pct_change(5).shift(1)
        rolling_high = close.shift(1).rolling(20, min_periods=5).max()
        g["drawdown_from_20d_high"] = close.shift(1) / rolling_high - 1.0
        g["market_return_1d_lag1"] = g["timestamp"].map(market)
        pieces.append(g[["timestamp", "symbol", *FEATURE_COLUMNS[:-1]]])
    out = pd.concat(pieces, ignore_index=True).sort_values(["timestamp", "symbol"])
    out["cross_sectional_return_rank"] = out.groupby("timestamp")[
        "return_1d_lag1"
    ].rank(pct=True)
    return out[["timestamp", "symbol", *FEATURE_COLUMNS]].reset_index(drop=True)
