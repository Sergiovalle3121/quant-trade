"""The stationary bootstrap's block length is measured on each file.

Politis and White (2004) with the Patton, Politis and White (2009)
correction. The resampled drawdown and challenge simulator take the larger
of the fixed 5-period block and the measured one when returns cluster, so
losing runs stay together; alternating returns keep the fixed block.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from quant_trade.audit import analytics
from quant_trade.audit.analytics import (
    DEFAULT_BLOCK_SIZE,
    MAX_BLOCK_SHARE,
    block_length,
    drawdown_risk,
    resample_block,
)


def _ar1(phi: float, n: int, seed: int, scale: float = 0.01) -> np.ndarray:
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal(n + 200) * scale
    out = np.zeros_like(shocks)
    for t in range(1, len(shocks)):
        out[t] = phi * out[t - 1] + shocks[t]
    return out[200:]


def _theory(phi: float, n: int) -> float:
    # For AR(1): G / g = 2 phi / (1 - phi^2); b = (G / g)^(2/3) n^(1/3).
    return abs(2 * phi / (1 - phi**2)) ** (2 / 3) * n ** (1 / 3)


@pytest.mark.parametrize("phi", [0.5, 0.8])
def test_the_measured_block_tracks_the_ar1_optimum(phi: float) -> None:
    n = 2000
    blocks = [block_length(_ar1(phi, n, seed)) for seed in range(20)]
    ratio = float(np.median(blocks)) / _theory(phi, n)
    assert 0.7 <= ratio <= 1.3


def test_independent_returns_measure_a_block_near_one() -> None:
    blocks = [block_length(_ar1(0.0, 1000, seed)) for seed in range(20)]
    assert float(np.median(blocks)) < 2.0


def test_independent_returns_keep_the_fixed_block() -> None:
    values = _ar1(0.0, 1000, 3)
    assert resample_block(values, None) == DEFAULT_BLOCK_SIZE


def test_alternating_returns_keep_the_fixed_block() -> None:
    values = _ar1(-0.6, 2000, 4)
    assert block_length(values) > DEFAULT_BLOCK_SIZE
    assert resample_block(values, None) == DEFAULT_BLOCK_SIZE


def test_clustered_returns_lengthen_the_block() -> None:
    values = _ar1(0.6, 2000, 5)
    block = resample_block(values, None)
    assert block > DEFAULT_BLOCK_SIZE
    assert block == pytest.approx(block_length(values))


def test_the_block_never_covers_more_than_a_quarter_of_the_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _ar1(0.9, 200, 6)
    monkeypatch.setattr(analytics, "_block_parts", lambda _values: (500.0, 3.0))
    assert resample_block(values, None) == pytest.approx(MAX_BLOCK_SHARE * 200)


def test_a_short_history_never_goes_below_the_fixed_block() -> None:
    values = _ar1(0.97, 12, 7)
    assert resample_block(values, None) == DEFAULT_BLOCK_SIZE


def test_an_explicit_block_is_kept() -> None:
    values = _ar1(0.8, 500, 8)
    assert resample_block(values, 3.0) == 3.0
    assert resample_block(values, 10_000) == 500.0
    assert resample_block(values, 0.2) == 1.0


@pytest.mark.parametrize(
    "values",
    [
        [0.01] * 50,
        [0.01, -0.01] * 4,
        [1e300, -1e300] * 30,
        [float("inf"), float("nan")] + [0.01, -0.02] * 20,
    ],
)
def test_degenerate_input_gives_a_finite_block_and_no_warning(values: list[float]) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        block = block_length(values)
        chosen = resample_block(np.asarray(values, dtype=float), None)
    assert math.isfinite(block) and block >= 1.0
    assert math.isfinite(chosen) and chosen >= 1.0


def test_clustered_losses_widen_the_resampled_drawdown() -> None:
    values = _ar1(0.6, 1500, 9, scale=0.004)
    auto = drawdown_risk(values, periods_per_year=252, samples=1500, seed=1)
    fixed = drawdown_risk(
        values, periods_per_year=252, samples=1500, seed=1, block_size=DEFAULT_BLOCK_SIZE
    )
    assert auto["method"]["expected_block_size"] > DEFAULT_BLOCK_SIZE
    assert auto["max_drawdown"]["p95"]["value"] > fixed["max_drawdown"]["p95"]["value"]


def test_independent_returns_keep_todays_drawdown_numbers() -> None:
    values = _ar1(0.0, 800, 10, scale=0.01)
    auto = drawdown_risk(values, periods_per_year=252, samples=500, seed=2)
    fixed = drawdown_risk(
        values, periods_per_year=252, samples=500, seed=2, block_size=DEFAULT_BLOCK_SIZE
    )
    assert auto == fixed


def test_the_challenge_simulator_records_the_block_it_used() -> None:
    from quant_trade.audit.prop_presets import get_preset

    rules = get_preset("generic-2step-phase1")
    values = _ar1(0.6, 600, 11, scale=0.005)
    result = analytics.simulate_challenge(values, rules, samples=300, seed=0)
    assert result["method"]["expected_block_size"] == pytest.approx(resample_block(values, None))
    assert result["method"]["expected_block_size"] > DEFAULT_BLOCK_SIZE
