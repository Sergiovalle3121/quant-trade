"""Forward labels for supervised ML research."""

from __future__ import annotations

import pandas as pd

LABEL_COLUMNS = [
    "forward_return",
    "direction",
    "quantile_rank",
    "vol_adjusted_forward_return",
]


def generate_labels(data: pd.DataFrame, horizon_days: int = 5) -> pd.DataFrame:
    pieces = []
    for _, group in data.sort_values(["symbol", "timestamp"]).groupby(
        "symbol", sort=False
    ):
        g = group.copy()
        close = g["close"].astype(float)
        fwd = close.shift(-horizon_days) / close - 1.0
        vol = close.pct_change().rolling(20, min_periods=5).std(ddof=0)
        g["forward_return"] = fwd
        g["direction"] = (fwd > 0).astype(int)
        g["vol_adjusted_forward_return"] = fwd / vol.replace(0.0, pd.NA)
        pieces.append(
            g[
                [
                    "timestamp",
                    "symbol",
                    "forward_return",
                    "direction",
                    "vol_adjusted_forward_return",
                ]
            ]
        )
    out = pd.concat(pieces, ignore_index=True).sort_values(["timestamp", "symbol"])
    out["quantile_rank"] = out.groupby("timestamp")["forward_return"].rank(pct=True)
    return out[["timestamp", "symbol", *LABEL_COLUMNS]].reset_index(drop=True)
