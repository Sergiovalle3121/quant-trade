"""Educational SMA crossover baseline.

This simple trend-following example is not a production strategy. It ignores many
market realities and exists to exercise the research/backtest framework.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


class SmaCrossoverStrategy(BaseModel):
    """Buy when a fast SMA crosses above a slow SMA; sell on the reverse."""

    fast_window: int = Field(default=3, gt=1)
    slow_window: int = Field(default=7, gt=2)
    name: str = "sma_crossover"

    def __call__(self, data: pd.DataFrame, **params: object) -> pd.DataFrame:
        """Backward-compatible callable strategy interface."""
        if params:
            return self.__class__(**params).generate_signals(data)
        return self.generate_signals(data)

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        signals = data[["timestamp", "close"]].copy()
        signals["fast_sma"] = signals["close"].rolling(self.fast_window).mean()
        signals["slow_sma"] = signals["close"].rolling(self.slow_window).mean()
        regime = np.where(signals["fast_sma"] > signals["slow_sma"], 1, 0)
        signals["signal"] = pd.Series(regime, index=signals.index).diff().fillna(0).clip(-1, 1)
        signals.loc[signals["slow_sma"].isna(), "signal"] = 0
        return signals[["timestamp", "signal", "fast_sma", "slow_sma"]]
