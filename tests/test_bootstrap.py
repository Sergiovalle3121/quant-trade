"""Tests for the reproducible resampling APIs (block/stationary bootstrap)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.research.bootstrap import (
    STATISTICS,
    _iid_indices,
    _moving_block_indices,
    bootstrap_confidence_intervals,
    iid_bootstrap,
    moving_block_bootstrap,
    observed_statistics,
    stationary_bootstrap,
)


def _ar1(n: int, phi: float, seed: int, sigma: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    eps = rng.normal(0.0, sigma, n)
    x = np.empty(n)
    x[0] = eps[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def _lag1_autocorr(series: np.ndarray) -> float:
    a, b = series[:-1], series[1:]
    if a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


# --- known values ---------------------------------------------------------


def test_constant_series_has_known_statistics():
    # Every resample of a constant series is that constant, so the statistics
    # are analytically known regardless of method or seed.
    r = pd.Series([0.01] * 50)
    for method in ("iid", "moving_block", "stationary"):
        draws = {
            "iid": iid_bootstrap(r, samples=100, seed=1),
            "moving_block": moving_block_bootstrap(r, samples=100, seed=1, block_size=5),
            "stationary": stationary_bootstrap(r, samples=100, seed=1, expected_block_size=5),
        }[method]
        assert np.allclose(draws["mean"], 0.01)
        assert np.allclose(draws["volatility"], 0.0)
        assert np.allclose(draws["sharpe"], 0.0)
        assert np.allclose(draws["max_drawdown"], 0.0)
        assert np.allclose(draws["total_return"], 1.01**50 - 1)


def test_observed_statistics_match_direct_computation():
    r = pd.Series([0.02, -0.01, 0.03, -0.02, 0.01])
    stats = observed_statistics(r)
    assert stats["mean"] == pytest.approx(float(np.mean(r)))
    assert stats["total_return"] == pytest.approx(float(np.prod(1 + r.to_numpy()) - 1))
    assert set(stats) == set(STATISTICS)


# --- reproducibility ------------------------------------------------------


@pytest.mark.parametrize(
    "fn,kwargs",
    [
        (iid_bootstrap, {}),
        (moving_block_bootstrap, {"block_size": 10}),
        (stationary_bootstrap, {"expected_block_size": 10}),
    ],
)
def test_same_seed_is_reproducible(fn, kwargs):
    r = pd.Series(_ar1(200, 0.5, seed=3))
    a = fn(r, samples=200, seed=7, **kwargs)
    b = fn(r, samples=200, seed=7, **kwargs)
    pd.testing.assert_frame_equal(a, b)


@pytest.mark.parametrize(
    "fn,kwargs",
    [
        (iid_bootstrap, {}),
        (moving_block_bootstrap, {"block_size": 10}),
        (stationary_bootstrap, {"expected_block_size": 10}),
    ],
)
def test_different_seeds_differ(fn, kwargs):
    r = pd.Series(_ar1(200, 0.5, seed=3))
    a = fn(r, samples=200, seed=7, **kwargs)
    b = fn(r, samples=200, seed=8, **kwargs)
    assert not a["total_return"].equals(b["total_return"])


# --- block behaviour ------------------------------------------------------


def test_block_size_is_actually_applied():
    # The old bug: block_size ignored. Two block sizes must give different draws.
    r = pd.Series(_ar1(300, 0.6, seed=11))
    small = moving_block_bootstrap(r, samples=300, seed=2, block_size=2)
    large = moving_block_bootstrap(r, samples=300, seed=2, block_size=60)
    assert not small["total_return"].equals(large["total_return"])


def test_block_size_one_approximates_iid():
    r = pd.Series(_ar1(300, 0.4, seed=13))
    mb = moving_block_bootstrap(r, samples=500, seed=5, block_size=1)
    iid = iid_bootstrap(r, samples=500, seed=5)
    # block_size=1 moving-block == IID resampling in distribution
    assert mb["total_return"].mean() == pytest.approx(iid["total_return"].mean(), abs=1e-9)


def test_blocks_preserve_autocorrelation_better_than_iid():
    values = _ar1(500, phi=0.7, seed=21)
    rng = np.random.default_rng(99)
    block_idx = _moving_block_indices(len(values), 400, block_size=25, wrap=True, rng=rng)
    rng2 = np.random.default_rng(99)
    iid_idx = _iid_indices(len(values), 400, rng2)
    block_ac = np.mean([_lag1_autocorr(values[row]) for row in block_idx])
    iid_ac = np.mean([_lag1_autocorr(values[row]) for row in iid_idx])
    original_ac = _lag1_autocorr(values)
    assert original_ac > 0.5
    assert iid_ac < 0.15  # IID destroys autocorrelation
    assert block_ac > 0.4  # blocks retain most of it
    assert abs(block_ac - original_ac) < abs(iid_ac - original_ac)


# --- no look-ahead / causality -------------------------------------------


def test_resamples_use_only_observed_values():
    values = np.array([0.01, -0.02, 0.03, 0.04, -0.05, 0.02])
    rng = np.random.default_rng(0)
    idx = _moving_block_indices(len(values), 50, block_size=3, wrap=True, rng=rng)
    assert idx.min() >= 0 and idx.max() < len(values)
    resampled = np.unique(values[idx])
    assert set(np.round(resampled, 10)).issubset(set(np.round(values, 10)))


def test_appending_future_data_does_not_change_prefix_result():
    prefix = pd.Series(_ar1(120, 0.5, seed=31))
    extended = pd.concat([prefix, pd.Series(_ar1(60, 0.5, seed=32))], ignore_index=True)
    a = stationary_bootstrap(prefix, samples=100, seed=1, expected_block_size=10)
    # Re-running on just the prefix must be identical: the function never sees
    # beyond the array it is handed.
    b = stationary_bootstrap(
        extended.iloc[: len(prefix)], samples=100, seed=1, expected_block_size=10
    )
    pd.testing.assert_frame_equal(a, b)


# --- confidence intervals -------------------------------------------------


def test_confidence_intervals_shape_and_ordering():
    r = pd.Series(_ar1(300, 0.5, seed=41))
    ci = bootstrap_confidence_intervals(
        r, method="stationary", samples=500, seed=7, block_size=20,
        percentiles=(5.0, 50.0, 95.0),
    )
    assert list(ci.index) == list(STATISTICS)
    assert {"point_estimate", "bootstrap_mean", "p5", "p50", "p95"}.issubset(ci.columns)
    # percentile bands are ordered
    assert (ci["p5"] <= ci["p95"]).all()


def test_wider_percentiles_are_not_narrower():
    r = pd.Series(_ar1(300, 0.5, seed=43))
    narrow = bootstrap_confidence_intervals(
        r, method="iid", samples=800, seed=1, percentiles=(25.0, 75.0)
    )
    wide = bootstrap_confidence_intervals(
        r, method="iid", samples=800, seed=1, percentiles=(2.5, 97.5)
    )
    assert wide.loc["total_return", "p2.5"] <= narrow.loc["total_return", "p25"]
    assert wide.loc["total_return", "p97.5"] >= narrow.loc["total_return", "p75"]


# --- error handling -------------------------------------------------------


def test_empty_input_raises():
    with pytest.raises(ValueError, match="at least"):
        iid_bootstrap(pd.Series([], dtype=float), samples=10, seed=1)


def test_too_short_input_raises():
    with pytest.raises(ValueError, match="at least"):
        iid_bootstrap(pd.Series([0.01]), samples=10, seed=1)


def test_nan_raises_by_default_and_drops_when_asked():
    r = pd.Series([0.01, np.nan, 0.02, 0.03])
    with pytest.raises(ValueError, match="NaN"):
        iid_bootstrap(r, samples=10, seed=1)
    draws = iid_bootstrap(r, samples=10, seed=1, nan_policy="drop")
    assert len(draws) == 10


def test_infinite_values_raise():
    r = pd.Series([0.01, np.inf, 0.02])
    with pytest.raises(ValueError, match="inf"):
        iid_bootstrap(r, samples=10, seed=1)


def test_invalid_samples_and_block_size():
    r = pd.Series(_ar1(50, 0.3, seed=1))
    with pytest.raises(ValueError, match="samples"):
        iid_bootstrap(r, samples=0, seed=1)
    with pytest.raises(ValueError, match="block_size"):
        moving_block_bootstrap(r, samples=10, seed=1, block_size=0)
    with pytest.raises(ValueError, match="exceeds sample length"):
        moving_block_bootstrap(r, samples=10, seed=1, block_size=999, wrap=False)


def test_unknown_method_raises():
    r = pd.Series(_ar1(50, 0.3, seed=1))
    with pytest.raises(ValueError, match="unknown bootstrap method"):
        bootstrap_confidence_intervals(r, method="magic", samples=10, seed=1)  # type: ignore[arg-type]
