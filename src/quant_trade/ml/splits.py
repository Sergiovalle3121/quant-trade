"""Chronological ML validation splits."""

from __future__ import annotations

import pandas as pd


def chronological_split(
    frame: pd.DataFrame, train_fraction: float = 0.7, embargo_days: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(pd.to_datetime(frame["timestamp"], utc=True).dropna().unique())
    if not dates:
        return frame.copy(), frame.iloc[0:0].copy()
    cut = max(1, min(len(dates) - 1, int(len(dates) * train_fraction)))
    train_end = dates[cut - 1]
    test_start_index = min(len(dates) - 1, cut + max(0, embargo_days))
    test_start = dates[test_start_index]
    ts = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.loc[ts <= train_end].copy(), frame.loc[ts >= test_start].copy()
