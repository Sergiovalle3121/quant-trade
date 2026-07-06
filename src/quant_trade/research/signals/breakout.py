"""Donchian channel breakout with ATR trailing exits.

The classic complement to return-based momentum: entries on N-day highs,
exits on an ATR trailing stop, so entry dynamics and exits differ genuinely
from the TSMOM family. Long-only by default; symmetric shorts (N-day lows,
trailing stop above) behind ``allow_short``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quant_trade.data.panel import validate_panel_schema
from quant_trade.research.signals.base import weights_to_long
from quant_trade.research.signals.trend import _cap_equal


def _atr(frame: pd.DataFrame, window: int) -> pd.Series:
    high, low, close = frame["high"], frame["low"], frame["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return true_range.rolling(window).mean()


def _positions_for_symbol(
    frame: pd.DataFrame, entry_window: int, atr_window: int, atr_multiple: float, allow_short: bool
) -> pd.Series:
    """Walk bars once, tracking breakout entries and ATR trailing exits.

    Channels are shifted one bar so today's close never enters today's own
    channel (no self-referential breakouts).
    """
    close = frame["close"].to_numpy(dtype=float)
    upper = frame["close"].rolling(entry_window).max().shift(1).to_numpy(dtype=float)
    lower = frame["close"].rolling(entry_window).min().shift(1).to_numpy(dtype=float)
    atr = _atr(frame, atr_window).to_numpy(dtype=float)
    state = 0  # -1 short, 0 flat, +1 long
    stop = np.nan
    out = np.zeros(len(close))
    for i in range(len(close)):
        if np.isnan(upper[i]) or np.isnan(atr[i]):
            out[i] = 0.0
            continue
        if state == 1:
            stop = max(stop, close[i] - atr_multiple * atr[i])
            if close[i] <= stop:
                state = 0
        elif state == -1:
            stop = min(stop, close[i] + atr_multiple * atr[i])
            if close[i] >= stop:
                state = 0
        if state == 0:
            if close[i] > upper[i]:
                state = 1
                stop = close[i] - atr_multiple * atr[i]
            elif allow_short and close[i] < lower[i]:
                state = -1
                stop = close[i] + atr_multiple * atr[i]
        out[i] = float(state)
    return pd.Series(out, index=frame["timestamp"].to_numpy())


def donchian_breakout(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    entry_window = int(params.get("entry_window", 55))
    atr_window = int(params.get("atr_window", 20))
    atr_multiple = float(params.get("atr_multiple", 3.0))
    max_w = float(params.get("max_weight_per_asset", 0.25))
    allow_short = bool(params.get("allow_short", False))
    if entry_window < 2 or atr_window < 2 or atr_multiple <= 0:
        raise ValueError("entry_window/atr_window must be >= 2 and atr_multiple positive")
    f = validate_panel_schema(data)
    states = {
        str(symbol): _positions_for_symbol(
            group.sort_values("timestamp").reset_index(drop=True),
            entry_window,
            atr_window,
            atr_multiple,
            allow_short,
        )
        for symbol, group in f.groupby("symbol")
    }
    state = pd.DataFrame(states).sort_index()
    longs = _cap_equal(state > 0, max_w)
    if allow_short:
        shorts = _cap_equal(state < 0, max_w)
        weights = longs - shorts
        gross = weights.abs().sum(axis=1)
        over = gross > 1.0
        weights.loc[over] = weights.loc[over].div(gross[over], axis=0)
    else:
        weights = longs
    # Breakouts are event-driven: emit targets every bar so exits happen the
    # bar after the stop is hit, not at the next calendar rebalance.
    return weights_to_long(weights, allow_short=allow_short)
