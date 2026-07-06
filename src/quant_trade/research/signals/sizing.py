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


def correlation_regime_scaler(
    weights: pd.DataFrame,
    close: pd.DataFrame,
    correlation_window: int = 42,
    correlation_threshold: float = 0.75,
    derisk_factor: float = 0.5,
) -> pd.DataFrame:
    """De-risk when cross-asset correlation spikes.

    Vol targeting handles volatility regimes; this handles the failure mode
    it misses — diversification evaporating as everything starts moving
    together (the signature of systemic crypto sell-offs). When the trailing
    mean pairwise correlation exceeds the threshold at a rebalance date, the
    whole row scales down by ``derisk_factor``. Causal: correlation at t uses
    returns through t; the engine executes at t+1's open.
    """
    if not 0 < derisk_factor <= 1:
        raise ValueError("derisk_factor must be in (0, 1]")
    if close.shape[1] < 2:
        return weights
    returns = close.pct_change()
    mean_corr = pd.Series(index=returns.index, dtype=float)
    for i in range(correlation_window, len(returns.index)):
        window = returns.iloc[i - correlation_window + 1 : i + 1]
        corr = window.corr()
        n = corr.shape[0]
        if n < 2:
            continue
        off_diagonal = (corr.sum().sum() - n) / (n * (n - 1))
        mean_corr.iloc[i] = off_diagonal
    scaled = weights.copy().astype(float)
    for ts in weights.index:
        value = mean_corr.get(ts)
        if value is not None and pd.notna(value) and value > correlation_threshold:
            scaled.loc[ts] = scaled.loc[ts] * derisk_factor
    return scaled
