"""Multi-horizon time-series momentum with volatility-targeted sizing.

The flagship v1 signal: a continuous momentum score blended across several
lookbacks (instead of a single binary lookback), sized inversely to each
asset's own volatility, then scaled so ex-ante portfolio volatility hits a
target. Long-only by default; shorts require an explicit ``allow_short``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant_trade.data.panel import pivot_close
from quant_trade.metrics.performance import periods_per_year
from quant_trade.research.signals.base import rebalance_mask, weights_to_long
from quant_trade.research.signals.sizing import (
    cap_weights,
    correlation_regime_scaler,
    scale_to_portfolio_vol_target,
)

DEFAULT_LOOKBACKS = (21, 63, 126, 252)


def multi_horizon_tsmom(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Blend momentum across horizons into a continuous score in [-1, 1].

    score(asset) = mean over lookbacks of sign(trailing return); weights are
    score / asset_vol, normalized to unit gross, capped per asset, and scaled
    to the portfolio volatility target.
    """
    lookbacks = [int(v) for v in params.get("lookbacks", DEFAULT_LOOKBACKS)]
    if not lookbacks or min(lookbacks) < 2:
        raise ValueError("lookbacks must be >= 2 bars")
    vol_window = int(params.get("volatility_window", 63))
    target_vol = float(params.get("portfolio_volatility_target", 0.20))
    max_w = float(params.get("max_weight_per_asset", 0.25))
    max_gross = float(params.get("max_gross_exposure", 1.0))
    allow_short = bool(params.get("allow_short", False))
    freq = str(params.get("rebalance_frequency", "weekly"))

    close = pivot_close(data)
    returns = close.pct_change()
    score = sum(np.sign(close / close.shift(lb) - 1.0) for lb in lookbacks) / len(lookbacks)
    score = score.where(close.notna())
    if not allow_short:
        score = score.clip(lower=0.0)

    ppy = periods_per_year(close.index)
    asset_vol = returns.rolling(vol_window).std() * np.sqrt(ppy)
    raw = (score / asset_vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    gross = raw.abs().sum(axis=1)
    weights = raw.div(gross.where(gross > 0), axis=0).fillna(0.0)
    weights = cap_weights(weights, max_w)
    weights = scale_to_portfolio_vol_target(
        weights,
        close,
        target_volatility=target_vol,
        volatility_window=vol_window,
        max_gross_exposure=max_gross,
    )
    # Vol targeting may scale UP toward the gross cap; the per-asset cap must
    # survive that scaling or the engine rejects the weights.
    weights = cap_weights(weights, max_w)
    # Optional correlation-regime de-risking: vol targeting misses the moment
    # diversification evaporates because everything sells off together.
    corr_threshold = params.get("regime_correlation_threshold")
    if corr_threshold is not None:
        weights = correlation_regime_scaler(
            weights,
            close,
            correlation_window=int(params.get("regime_correlation_window", 42)),
            correlation_threshold=float(corr_threshold),
            derisk_factor=float(params.get("regime_derisk_factor", 0.5)),
        )
    return weights_to_long(
        weights, rebalance=rebalance_mask(close.index, freq), allow_short=allow_short
    )
