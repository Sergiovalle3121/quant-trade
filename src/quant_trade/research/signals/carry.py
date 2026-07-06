"""Funding-rate carry for perpetual futures.

Longs earn when funding is negative (shorts pay longs); shorts earn when
funding is positive. The signal ranks assets by trailing mean funding: hold
the cheapest-to-hold (most negative funding) names and, when shorts are
enabled, short the most expensive (highest positive funding) names.

Requires the panel to carry a ``funding_rate`` column (per bar, per symbol) —
see ``quant-trade data fetch-funding`` and ``attach_funding_rates``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_trade.data.panel import validate_panel_schema
from quant_trade.research.signals.base import rebalance_mask, weights_to_long
from quant_trade.research.signals.trend import _cap_equal

FUNDING_COLUMN = "funding_rate"


def funding_carry(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    if FUNDING_COLUMN not in data.columns:
        raise ValueError(
            "funding_carry requires a funding_rate column in the panel; "
            "join funding history with quant_trade.data.panel.attach_funding_rates"
        )
    window = int(params.get("funding_window", 21))
    quantile = float(params.get("quantile", 0.34))
    max_w = float(params.get("max_weight_per_asset", 0.25))
    allow_short = bool(params.get("allow_short", False))
    freq = str(params.get("rebalance_frequency", "weekly"))
    if not 0 < quantile <= 0.5:
        raise ValueError("quantile must be in (0, 0.5]")
    f = validate_panel_schema(data)
    funding = (
        f.assign(funding_rate=pd.to_numeric(data[FUNDING_COLUMN], errors="coerce").to_numpy())
        .pivot(index="timestamp", columns="symbol", values="funding_rate")
        .sort_index()
    )
    trailing = funding.rolling(window).mean()
    count = trailing.notna().sum(axis=1)
    bucket = (count * quantile).clip(lower=1).astype(int)
    ranks = trailing.rank(axis=1, method="first")  # low rank = cheapest funding
    longs_mask = ranks.le(bucket, axis=0) & trailing.notna()
    weights = _cap_equal(longs_mask, max_w)
    if allow_short:
        shorts_mask = ranks.gt(count.sub(bucket), axis=0) & trailing.notna()
        weights = weights - _cap_equal(shorts_mask, max_w)
        gross = weights.abs().sum(axis=1)
        over = gross > 1.0
        weights.loc[over] = weights.loc[over].div(gross[over], axis=0)
    rb = rebalance_mask(weights.index, freq)
    return weights_to_long(weights, rebalance=rb, allow_short=allow_short)
