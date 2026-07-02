"""Buy-and-hold baseline strategy for research comparisons."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel


class BuyAndHoldStrategy(BaseModel):
    """Emit one buy signal near the beginning and then hold the position."""

    name: str = "buy_and_hold"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        signals = data[["timestamp"]].copy()
        signals["signal"] = 0
        if len(signals) > 1:
            signals.loc[signals.index[0], "signal"] = 1
        return signals[["timestamp", "signal"]]


def generate_signals(data: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible functional wrapper."""
    return BuyAndHoldStrategy().generate_signals(data)
