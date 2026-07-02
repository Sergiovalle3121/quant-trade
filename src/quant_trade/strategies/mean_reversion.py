"""Educational rolling z-score mean reversion baseline.

This is a toy long-only strategy. It assumes mean reversion without proving it,
ignores borrow/financing constraints, and should not be used for live trading.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


class MeanReversionStrategy(BaseModel):
    """Buy when price is below its rolling mean, sell after reverting."""

    window: int = Field(default=5, gt=2)
    entry_z: float = Field(default=-1.0, lt=0)
    exit_z: float = Field(default=0.0)
    name: str = "mean_reversion"

    def __call__(self, data: pd.DataFrame, **params: object) -> pd.DataFrame:
        """Backward-compatible callable strategy interface."""
        if params:
            return self.__class__(**params).generate_signals(data)
        return self.generate_signals(data)

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        signals = data[["timestamp", "close"]].copy()
        rolling_mean = signals["close"].rolling(self.window).mean()
        rolling_std = signals["close"].rolling(self.window).std(ddof=0).replace(0, np.nan)
        signals["z_score"] = (signals["close"] - rolling_mean) / rolling_std
        signals["signal"] = 0
        in_position = False
        for idx, z_score in signals["z_score"].items():
            if np.isnan(z_score):
                continue
            if not in_position and z_score <= self.entry_z:
                signals.at[idx, "signal"] = 1
                in_position = True
            elif in_position and z_score >= self.exit_z:
                signals.at[idx, "signal"] = -1
                in_position = False
        return signals[["timestamp", "signal", "z_score"]]
