"""Tests for timestamp-based, purged/embargoed research splits."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.research.splits import (
    PurgedSplit,
    chronological_train_test_split,
    purged_chronological_split,
    purged_walk_forward_splits,
    walk_forward_splits,
)


def _panel(n_days: int = 40, symbols=("AAA", "BBB", "CCC"), seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n_days, freq="D", tz="UTC")
    rows = []
    for sym in symbols:
        px = 100 * np.cumprod(1 + rng.normal(0, 0.01, n_days))
        for ts, p in zip(dates, px, strict=True):
            rows.append({"timestamp": ts, "symbol": sym, "close": float(p)})
    # deliberately shuffle so ordering cannot be relied on
    return pd.DataFrame(rows).sample(frac=1.0, random_state=seed).reset_index(drop=True)


def _no_shared_timestamp(train: pd.DataFrame, test: pd.DataFrame) -> bool:
    return not (set(train["timestamp"]) & set(test["timestamp"]))


def _all_symbols_together(frame: pd.DataFrame, symbols) -> bool:
    # Every timestamp present in the frame carries all symbols that exist for it.
    counts = frame.groupby("timestamp")["symbol"].nunique()
    return bool((counts == len(symbols)).all())


# --- panel leakage --------------------------------------------------------


def test_no_timestamp_shared_between_train_and_test_panel():
    panel = _panel()
    train, test = chronological_train_test_split(panel, 0.6)
    assert _no_shared_timestamp(train, test)
    assert train["timestamp"].max() < test["timestamp"].min()


def test_symbols_stay_together_at_boundary():
    symbols = ("AAA", "BBB", "CCC")
    panel = _panel(symbols=symbols)
    train, test = chronological_train_test_split(panel, 0.55)
    assert _all_symbols_together(train, symbols)
    assert _all_symbols_together(test, symbols)


def test_old_row_based_leak_is_gone_at_fractional_cut():
    # The exact panel/fraction that leaked under the row-based split.
    ts = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"], utc=True)
    panel = pd.DataFrame(
        {"timestamp": list(ts) * 2, "symbol": ["AAA"] * 4 + ["BBB"] * 4, "close": range(8)}
    )
    train, test = chronological_train_test_split(panel, 0.4)
    assert _no_shared_timestamp(train, test)


# --- purge / embargo exactness -------------------------------------------


def test_purge_and_embargo_are_exact():
    panel = _panel(n_days=40)
    split = purged_chronological_split(panel, 0.5, purge_bars=3, embargo_bars=2)
    dates = sorted(panel["timestamp"].unique())
    cut = int(len(dates) * 0.5)
    assert split.purged_timestamps == dates[cut - 3 : cut]
    assert split.embargoed_timestamps == dates[cut : cut + 2]
    # purged/embargoed appear in neither train nor test
    boundary = set(split.purged_timestamps) | set(split.embargoed_timestamps)
    assert not (set(split.train["timestamp"]) & boundary)
    assert not (set(split.test["timestamp"]) & boundary)
    assert _no_shared_timestamp(split.train, split.test)


def test_label_horizon_greater_than_embargo():
    panel = _panel(n_days=60)
    split = purged_chronological_split(panel, 0.5, purge_bars=10, embargo_bars=2)
    # 10 purged timestamps at the train tail even though embargo is only 2
    assert len(split.purged_timestamps) == 10
    assert len(split.embargoed_timestamps) == 2
    gap = (split.test["timestamp"].min() - split.train["timestamp"].max()).days
    assert gap == 10 + 2 + 1  # purge + embargo timestamps + one normal step


def test_purged_split_unpacks_like_a_tuple():
    panel = _panel()
    split = purged_chronological_split(panel, 0.6, purge_bars=1)
    assert isinstance(split, PurgedSplit)
    train, test = split
    assert train["timestamp"].max() < test["timestamp"].min()


# --- irregular panels -----------------------------------------------------


def test_irregular_panel_missing_bars():
    panel = _panel(n_days=30, symbols=("AAA", "BBB"))
    # drop some BBB rows so the panel is ragged
    mask = ~((panel["symbol"] == "BBB") & (panel["timestamp"].dt.day % 7 == 0))
    ragged = panel[mask].reset_index(drop=True)
    split = purged_chronological_split(ragged, 0.6, purge_bars=2, embargo_bars=1)
    assert _no_shared_timestamp(split.train, split.test)
    assert split.train["timestamp"].max() < split.test["timestamp"].min()


# --- walk forward ---------------------------------------------------------


def test_purged_walk_forward_windows_are_clean():
    panel = _panel(n_days=80, symbols=("AAA", "BBB"))
    windows = purged_walk_forward_splits(
        panel, train_size=20, test_size=10, step_size=10, purge_bars=3, embargo_bars=2
    )
    assert len(windows) >= 2
    for w in windows:
        assert _no_shared_timestamp(w.train, w.test)
        assert w.train["timestamp"].max() < w.test["timestamp"].min()
        assert len(w.purged_timestamps) == 3
        assert len(w.embargoed_timestamps) == 2
        assert w.test["timestamp"].nunique() == 10


# --- causality ------------------------------------------------------------


def test_train_partition_is_invariant_to_future_perturbation():
    # Truncation/future-perturbation causality: the train set must not depend on
    # anything in (or beyond) the test window.
    panel = _panel(n_days=50, symbols=("AAA", "BBB"), seed=7)
    split_a = purged_chronological_split(panel, 0.6, purge_bars=2, embargo_bars=1)
    perturbed = panel.copy()
    test_ts = set(split_a.test["timestamp"])
    perturbed.loc[perturbed["timestamp"].isin(test_ts), "close"] *= 3.14
    split_b = purged_chronological_split(perturbed, 0.6, purge_bars=2, embargo_bars=1)
    pd.testing.assert_frame_equal(
        split_a.train.sort_values(["timestamp", "symbol"]).reset_index(drop=True),
        split_b.train.sort_values(["timestamp", "symbol"]).reset_index(drop=True),
    )


# --- error handling -------------------------------------------------------


def test_insufficient_window_raises():
    panel = _panel(n_days=10, symbols=("AAA",))
    with pytest.raises(ValueError, match="insufficient|walk-forward"):
        purged_walk_forward_splits(panel, train_size=8, test_size=8, step_size=2)


def test_purge_cannot_erase_whole_train():
    panel = _panel(n_days=20, symbols=("AAA",))
    with pytest.raises(ValueError, match="purge_bars"):
        purged_walk_forward_splits(panel, train_size=5, test_size=3, step_size=2, purge_bars=5)


def test_single_asset_backward_compatible():
    # For single-asset data, timestamp-based == the old row-based behaviour.
    frame = pd.DataFrame(
        {"timestamp": pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"),
         "close": range(100)}
    )
    train, test = chronological_train_test_split(frame, 0.7, embargo_bars=5)
    assert len(train) == 70
    assert len(test) == 25
    for tr, te in walk_forward_splits(frame, 30, 10, 10, embargo_bars=5):
        assert (te["timestamp"].min() - tr["timestamp"].max()).days == 6
