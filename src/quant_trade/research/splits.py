"""Timestamp-based, purged research data splits.

The earlier row-based splits (``int(len(df) * fraction)`` + ``iloc``) leaked
across the train/test boundary on long-form multi-asset panels: two rows that
share a timestamp but belong to different symbols could land on opposite sides
of the cut, putting the *same bar* in both train and test. Every split here
partitions **unique timestamps**, so all symbols of a timestamp always move
together and a train window always ends strictly before its test window.

Two families:

- ``chronological_train_test_split`` / ``walk_forward_splits`` — backward
  compatible signatures; now timestamp-based (identical output for single-asset
  data, leak-free for panels). ``embargo_bars`` counts timestamps.
- ``purged_chronological_split`` / ``purged_walk_forward_splits`` — add
  López de Prado style *purging*: ``purge_bars`` (the label/feature horizon)
  drops that many timestamps from the *end of train* so a training label whose
  horizon reaches into the test window cannot leak, and ``embargo_bars`` drops
  that many timestamps from the *start of test*. Both return a ``PurgedSplit``
  that records exactly which timestamps were purged and embargoed.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

TIME_COLUMN = "timestamp"


def _sorted(data: pd.DataFrame) -> pd.DataFrame:
    if TIME_COLUMN not in data.columns:
        raise ValueError(f"data must contain a {TIME_COLUMN!r} column")
    return data.sort_values(TIME_COLUMN, kind="stable").reset_index(drop=True)


def _unique_timestamps(data: pd.DataFrame) -> list[Any]:
    if TIME_COLUMN not in data.columns:
        raise ValueError(f"data must contain a {TIME_COLUMN!r} column")
    return sorted(pd.Index(data[TIME_COLUMN].unique()).tolist())


def _rows_for(data: pd.DataFrame, timestamps: list[Any]) -> pd.DataFrame:
    keep = set(timestamps)
    subset = data[data[TIME_COLUMN].isin(keep)]
    return subset.sort_values(TIME_COLUMN, kind="stable").reset_index(drop=True)


def chronological_train_test_split(
    data: pd.DataFrame, train_fraction: float, embargo_bars: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split on unique timestamps with an optional embargo.

    ``embargo_bars`` drops that many timestamps at the start of the test window
    so lookback features straddling the boundary cannot leak train information.
    All symbols sharing a timestamp stay on the same side of the cut.
    """
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if embargo_bars < 0:
        raise ValueError("embargo_bars must be >= 0")
    dates = _unique_timestamps(data)
    cut = int(len(dates) * train_fraction)
    test_start = cut + embargo_bars
    if cut <= 0 or test_start >= len(dates):
        raise ValueError("insufficient data for train/test split with embargo")
    return _rows_for(data, dates[:cut]), _rows_for(data, dates[test_start:])


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
    """Rolling walk-forward over unique timestamps (sizes count timestamps)."""
    if min(train_size, test_size, step_size) <= 0:
        raise ValueError("window sizes must be positive")
    if embargo_bars < 0:
        raise ValueError("embargo_bars must be >= 0")
    dates = _unique_timestamps(data)
    out: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    start = 0
    while start + train_size + embargo_bars + test_size <= len(dates):
        train_ts = dates[start : start + train_size]
        test_from = start + train_size + embargo_bars
        test_ts = dates[test_from : test_from + test_size]
        if train_ts[-1] >= test_ts[0]:
            raise ValueError("test window must occur after train window")
        out.append((_rows_for(data, train_ts), _rows_for(data, test_ts)))
        start += step_size
    if not out:
        raise ValueError("insufficient data for walk-forward splits")
    return out


@dataclass
class PurgedSplit:
    """A single purged/embargoed split plus the audit trail of what was removed."""

    train: pd.DataFrame
    test: pd.DataFrame
    purged_timestamps: list[Any] = field(default_factory=list)
    embargoed_timestamps: list[Any] = field(default_factory=list)
    train_range: tuple[Any, Any] | None = None
    test_range: tuple[Any, Any] | None = None

    def __iter__(self) -> Iterator[pd.DataFrame]:
        # Supports ``for train, test in ...`` and ``train, test = split``.
        yield self.train
        yield self.test


def _purged_from_timestamps(
    data: pd.DataFrame,
    dates: list[Any],
    train_lo: int,
    train_hi: int,
    test_lo: int,
    test_hi: int,
    purge_bars: int,
    embargo_bars: int,
) -> PurgedSplit:
    """Build a PurgedSplit from timestamp index bounds.

    ``[train_lo, train_hi)`` is the nominal train window and
    ``[test_lo, test_hi)`` the nominal test window; ``purge_bars`` are removed
    from the end of train and ``embargo_bars`` from the start of test.
    """
    train_keep_hi = train_hi - purge_bars
    test_keep_lo = test_lo + embargo_bars
    if train_keep_hi <= train_lo:
        raise ValueError("purge_bars removes the entire train window")
    if test_keep_lo >= test_hi:
        raise ValueError("embargo_bars removes the entire test window")
    train_ts = dates[train_lo:train_keep_hi]
    test_ts = dates[test_keep_lo:test_hi]
    purged = dates[train_keep_hi:train_hi]
    embargoed = dates[test_lo:test_keep_lo]
    if train_ts[-1] >= test_ts[0]:
        raise ValueError("train window must end before the test window")
    return PurgedSplit(
        train=_rows_for(data, train_ts),
        test=_rows_for(data, test_ts),
        purged_timestamps=purged,
        embargoed_timestamps=embargoed,
        train_range=(train_ts[0], train_ts[-1]),
        test_range=(test_ts[0], test_ts[-1]),
    )


def purged_chronological_split(
    data: pd.DataFrame,
    train_fraction: float,
    *,
    purge_bars: int = 0,
    embargo_bars: int = 0,
) -> PurgedSplit:
    """Chronological split with purge (train tail) and embargo (test head).

    ``purge_bars`` should be at least the label/feature horizon so a training
    observation whose label reaches ``purge_bars`` timestamps forward cannot
    overlap the test window.
    """
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if purge_bars < 0 or embargo_bars < 0:
        raise ValueError("purge_bars and embargo_bars must be >= 0")
    dates = _unique_timestamps(data)
    cut = int(len(dates) * train_fraction)
    if cut <= 0 or cut >= len(dates):
        raise ValueError("insufficient data for a purged chronological split")
    return _purged_from_timestamps(
        data, dates, 0, cut, cut, len(dates), purge_bars, embargo_bars
    )


def purged_walk_forward_splits(
    data: pd.DataFrame,
    train_size: int,
    test_size: int,
    step_size: int,
    *,
    purge_bars: int = 0,
    embargo_bars: int = 0,
) -> list[PurgedSplit]:
    """Rolling walk-forward over timestamps with purge and embargo per window."""
    if min(train_size, test_size, step_size) <= 0:
        raise ValueError("window sizes must be positive")
    if purge_bars < 0 or embargo_bars < 0:
        raise ValueError("purge_bars and embargo_bars must be >= 0")
    if purge_bars >= train_size:
        raise ValueError("purge_bars must be smaller than train_size")
    dates = _unique_timestamps(data)
    out: list[PurgedSplit] = []
    start = 0
    while start + train_size + embargo_bars + test_size <= len(dates):
        train_hi = start + train_size
        test_lo = train_hi
        out.append(
            _purged_from_timestamps(
                data,
                dates,
                start,
                train_hi,
                test_lo,
                test_lo + embargo_bars + test_size,
                purge_bars,
                embargo_bars,
            )
        )
        start += step_size
    if not out:
        raise ValueError("insufficient data for purged walk-forward splits")
    return out
