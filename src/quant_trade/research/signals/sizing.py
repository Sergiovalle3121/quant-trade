"""Position-sizing helpers shared by signal models.

Everything here is causal by construction: sizing at timestamp t uses only
returns through t, and the engine executes the resulting targets at t+1's
open.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quant_trade.metrics.performance import periods_per_year


def scale_to_portfolio_vol_target(
    weights: pd.DataFrame,
    close: pd.DataFrame,
    target_volatility: float,
    volatility_window: int = 63,
    max_gross_exposure: float = 1.0,
) -> pd.DataFrame:
    """Scale each row of target weights so ex-ante portfolio volatility hits
    ``target_volatility`` (annualized), capped at ``max_gross_exposure``.

    Ex-ante vol at t is the trailing standard deviation of the portfolio
    return series implied by holding row t's weights over the last
    ``volatility_window`` bars. Rows without enough history keep zero weights
    rather than trading unsized risk.
    """
    if target_volatility <= 0:
        raise ValueError("target_volatility must be positive")
    returns = close.pct_change()
    ppy = periods_per_year(close.index)
    annualizer = math.sqrt(ppy)
    scaled = weights.copy().astype(float)
    matrix = returns[weights.columns].to_numpy(dtype=float)
    positions = {ts: i for i, ts in enumerate(returns.index)}
    for ts, row in weights.iterrows():
        w = row.fillna(0.0).to_numpy(dtype=float)
        gross = float(np.abs(w).sum())
        if gross <= 0:
            continue
        end = positions.get(ts)
        if end is None or end + 1 < volatility_window:
            scaled.loc[ts] = 0.0
            continue
        window = matrix[end + 1 - volatility_window : end + 1]
        port = np.nansum(window * w, axis=1)
        vol = float(np.std(port, ddof=0)) * annualizer
        if vol <= 0:
            scaled.loc[ts] = 0.0
            continue
        scale = min(target_volatility / vol, max_gross_exposure / gross)
        scaled.loc[ts] = w * scale
    return scaled


def cap_weights(weights: pd.DataFrame, max_weight_per_asset: float) -> pd.DataFrame:
    """Symmetric per-asset cap that preserves sign."""
    return weights.clip(lower=-max_weight_per_asset, upper=max_weight_per_asset)
