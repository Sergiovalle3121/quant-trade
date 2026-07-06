"""Tests for the statistical validation layer (PSR, DSR, MinTRL)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.metrics.statistics import (
    _phi,
    _phi_inv,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    minimum_track_record_length,
    probabilistic_sharpe_ratio,
    sharpe_per_period,
    sharpe_variance_across_trials,
)


def _returns(mean: float, std: float, n: int, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mean, std, n))


def test_phi_and_inverse_are_consistent():
    for p in (0.01, 0.05, 0.5, 0.95, 0.99):
        assert _phi(_phi_inv(p)) == pytest.approx(p, abs=1e-6)
    assert _phi(0.0) == pytest.approx(0.5)
    assert _phi_inv(0.975) == pytest.approx(1.959964, abs=1e-4)


def test_psr_increases_with_skill_and_track_length():
    skilled = probabilistic_sharpe_ratio(_returns(0.004, 0.01, 500))
    unskilled = probabilistic_sharpe_ratio(_returns(0.0, 0.01, 500))
    assert skilled > 0.99
    assert unskilled < 0.6  # zero-mean sample must not look like skill
    short = probabilistic_sharpe_ratio(_returns(0.004, 0.01, 30))
    assert short < skilled  # same skill, less evidence


def test_psr_handles_degenerate_inputs():
    assert probabilistic_sharpe_ratio(pd.Series(dtype=float)) == 0.0
    assert probabilistic_sharpe_ratio(pd.Series([0.01, 0.01])) == 0.0
    assert probabilistic_sharpe_ratio(pd.Series([0.01] * 100)) == 0.0  # zero variance


def test_expected_max_sharpe_grows_with_trials():
    v = 0.01
    one = expected_max_sharpe(1, v)
    ten = expected_max_sharpe(10, v)
    hundred = expected_max_sharpe(100, v)
    assert one == 0.0
    assert 0 < ten < hundred


def test_dsr_penalizes_many_trials():
    returns = _returns(0.003, 0.01, 400)
    sr = sharpe_per_period(returns)
    assert sr > 0
    dsr_few = deflated_sharpe_ratio(returns, n_trials=2, sharpe_variance=sr**2)
    dsr_many = deflated_sharpe_ratio(returns, n_trials=500, sharpe_variance=sr**2)
    assert dsr_many < dsr_few
    # with a single trial DSR degrades to plain PSR
    assert deflated_sharpe_ratio(returns, 1, 0.0) == pytest.approx(
        probabilistic_sharpe_ratio(returns)
    )


def test_min_track_record_length_behaviour():
    good = _returns(0.002, 0.01, 500)
    assert minimum_track_record_length(good) < 500  # already enough evidence
    flat = _returns(0.0, 0.01, 500, seed=1)
    if sharpe_per_period(flat) <= 0:
        assert minimum_track_record_length(flat) == float("inf")
    weak = _returns(0.0002, 0.01, 500, seed=3)
    strong = _returns(0.003, 0.01, 500, seed=3)
    if sharpe_per_period(weak) > 0:
        assert minimum_track_record_length(weak) > minimum_track_record_length(strong)


def test_sharpe_variance_across_trials():
    assert sharpe_variance_across_trials([]) == 0.0
    assert sharpe_variance_across_trials([0.1]) == 0.0
    assert sharpe_variance_across_trials([0.1, 0.2, 0.3]) == pytest.approx(0.01)
