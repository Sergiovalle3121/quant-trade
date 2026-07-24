"""Tests for the configurable annualization frequency of rolling_metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.research.robustness import rolling_metrics


def _equity(n: int = 300, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    equity = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return pd.DataFrame({"timestamp": ts, "equity": equity})


def test_default_is_252_backward_compatible():
    df = rolling_metrics(_equity(), windows=(63,))
    assert "rolling_63_volatility" in df.columns


def test_frequency_scales_volatility():
    equity = _equity()
    daily = rolling_metrics(equity, windows=(63,), periods_per_year=252.0)
    weekly = rolling_metrics(equity, windows=(63,), periods_per_year=52.0)
    # volatility scales with sqrt(periods_per_year)
    ratio = (daily["rolling_63_volatility"] / weekly["rolling_63_volatility"]).dropna()
    assert np.allclose(ratio, (252.0 / 52.0) ** 0.5)


def test_invalid_frequency_raises():
    with pytest.raises(ValueError, match="periods_per_year"):
        rolling_metrics(_equity(), periods_per_year=0.0)


def test_empty_returns_empty():
    assert rolling_metrics(pd.DataFrame()).empty
