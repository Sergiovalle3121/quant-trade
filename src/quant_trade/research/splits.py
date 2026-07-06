"""Chronological research data split helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd

TIME_COLUMN = "timestamp"


def _sorted(data: pd.DataFrame) -> pd.DataFrame:
    if TIME_COLUMN not in data.columns:
        raise ValueError(f"data must contain a {TIME_COLUMN!r} column")
    return data.sort_values(TIME_COLUMN).reset_index(drop=True)


def chronological_train_test_split(
    data: pd.DataFrame, train_fraction: float, embargo_bars: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split with an optional embargo.

    ``embargo_bars`` drops that many bars at the start of the test window so
    lookback features straddling the boundary cannot leak train information
    into the out-of-sample evidence.
    """
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if embargo_bars < 0:
        raise ValueError("embargo_bars must be >= 0")
    df = _sorted(data)
    cut = int(len(df) * train_fraction)
    test_start = cut + embargo_bars
    if cut <= 0 or test_start >= len(df):
        raise ValueError("insufficient data for train/test split with embargo")
    return df.iloc[:cut].copy(), df.iloc[test_start:].copy()


def date_based_split(
    data: pd.DataFrame,
    train_start: Any,
    train_end: Any,
    test_start: Any,
    test_end: Any,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ts, te, ss, se = (
        pd.to_datetime(v, utc=True) for v in [train_start, train_end, test_start, test_end]
    )
    if not (ts <= te < ss <= se):
        raise ValueError("dates must satisfy train_start <= train_end < test_start <= test_end")
    df = _sorted(data)
    train = df[(df[TIME_COLUMN] >= ts) & (df[TIME_COLUMN] <= te)].copy()
    test = df[(df[TIME_COLUMN] >= ss) & (df[TIME_COLUMN] <= se)].copy()
    if train.empty or test.empty:
        raise ValueError("date split produced empty train or test data")
    return train, test


def walk_forward_splits(
    data: pd.DataFrame, train_size: int, test_size: int, step_size: int, embargo_bars: int = 0
) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
    if min(train_size, test_size, step_size) <= 0:
        raise ValueError("window sizes must be positive")
    if embargo_bars < 0:
        raise ValueError("embargo_bars must be >= 0")
    df = _sorted(data)
    out = []
    start = 0
    while start + train_size + embargo_bars + test_size <= len(df):
        train = df.iloc[start : start + train_size].copy()
        test_from = start + train_size + embargo_bars
        test = df.iloc[test_from : test_from + test_size].copy()
        if train[TIME_COLUMN].max() >= test[TIME_COLUMN].min():
            raise ValueError("test window must occur after train window")
        out.append((train, test))
        start += step_size
    if not out:
        raise ValueError("insufficient data for walk-forward splits")
    return out
