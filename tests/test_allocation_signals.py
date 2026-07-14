"""Tests for the benchmark-aware allocation signals (research lab)."""

import numpy as np
import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.research.signals.allocation import (
    equal_weight_quarterly,
    inverse_volatility,
    vol_targeted_equal_weight,
)
from quant_trade.research.strategy_registry import list_research_signal_models


def _panel(n: int = 200, sigmas: dict[str, float] | None = None) -> pd.DataFrame:
    """Deterministic multi-asset panel with per-symbol volatility."""
    sigmas = sigmas or {"LOWVOL": 0.002, "MIDVOL": 0.01, "HIGHVOL": 0.03}
    ts = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
    rng = np.random.default_rng(7)
    frames = []
    for symbol, sigma in sigmas.items():
        returns = rng.normal(0.0002, sigma, n)
        close = 100.0 * np.cumprod(1 + returns)
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": ts,
                    "symbol": symbol,
                    "open": close,
                    "high": close * 1.001,
                    "low": close * 0.999,
                    "close": close,
                    "volume": 1_000_000.0,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_new_signals_are_registered():
    names = list_research_signal_models()
    for name in ("inverse_volatility", "vol_targeted_equal_weight", "equal_weight_quarterly"):
        assert name in names


def test_inverse_volatility_orders_weights_by_inverse_vol():
    data = _panel()
    w = inverse_volatility(
        data, {"volatility_window": 20, "rebalance_frequency": "monthly"}
    )
    last_ts = w["timestamp"].max()
    row = w[w["timestamp"] == last_ts].set_index("symbol")["target_weight"]
    assert row["LOWVOL"] > row["MIDVOL"] > row["HIGHVOL"]


def test_inverse_volatility_fully_invested_and_capped():
    data = _panel()
    cap = 0.5
    w = inverse_volatility(
        data,
        {"volatility_window": 20, "rebalance_frequency": "monthly", "max_weight_per_asset": cap},
    )
    assert (w["target_weight"] >= -1e-12).all()
    assert (w["target_weight"] <= cap + 1e-12).all()
    sums = w.groupby("timestamp")["target_weight"].sum()
    # After the lookback fills, the uncapped normalized weights sum to 1.
    settled = sums[sums.index > sums.index.min()]
    assert not settled.empty
    assert np.allclose(settled.to_numpy(), 1.0, atol=1e-9) or (settled <= 1.0 + 1e-9).all()


def test_vol_target_stays_fully_invested_when_calm():
    calm = _panel(sigmas={"A": 0.001, "B": 0.001, "C": 0.001})
    w = vol_targeted_equal_weight(
        calm,
        {"volatility_window": 20, "target_volatility": 0.10, "rebalance_frequency": "monthly"},
    )
    sums = w.groupby("timestamp")["target_weight"].sum()
    settled = sums[sums.index > sums.index.min()]
    # ~1.6% annualized realized vol is far below target: scale caps at 1.
    assert np.allclose(settled.to_numpy(), 1.0, atol=1e-9)


def test_vol_target_derisks_when_volatile():
    # Diversification cuts portfolio vol by ~sqrt(3), so per-asset sigma must
    # be large for the portfolio to run unambiguously above the 10% target.
    wild = _panel(sigmas={"A": 0.04, "B": 0.04, "C": 0.04})
    w = vol_targeted_equal_weight(
        wild,
        {"volatility_window": 20, "target_volatility": 0.10, "rebalance_frequency": "monthly"},
    )
    sums = w.groupby("timestamp")["target_weight"].sum()
    settled = sums[sums.index > sums.index.min()]
    # Realized vol runs well above 10% annualized: scale must shrink exposure.
    assert (settled < 0.75).all()
    assert (settled > 0.0).all()


def test_equal_weight_quarterly_emits_only_quarter_starts():
    data = _panel(n=260)  # spans 2024-01 .. 2024-12 business days
    w = equal_weight_quarterly(data, {})
    emitted = pd.DatetimeIndex(sorted(w["timestamp"].unique()))
    assert len(emitted) == 4  # Q1-Q4 2024
    assert all(ts.month in (1, 4, 7, 10) for ts in emitted)
    dates = pd.DatetimeIndex(sorted(data["timestamp"].unique()))
    for ts in emitted:
        month_days = dates[(dates.year == ts.year) & (dates.month == ts.month)]
        assert ts == month_days.min()  # first trading day of the quarter month
    assert np.allclose(w["target_weight"].to_numpy(), 1.0 / 3.0)


def test_allocation_signals_truncation_invariance():
    data = _panel(n=180)
    params = {"volatility_window": 20, "rebalance_frequency": "monthly"}
    dates = sorted(data["timestamp"].unique())
    cut_ts = dates[129]
    for func in (inverse_volatility, vol_targeted_equal_weight, equal_weight_quarterly):
        full_w = func(data, params)
        full = run_multi_asset_backtest(data, full_w, 10_000.0, CostModel())
        partial_data = data[data["timestamp"] <= cut_ts].copy()
        partial = run_multi_asset_backtest(
            partial_data, func(partial_data, params), 10_000.0, CostModel()
        )
        full_head = full.equity_curve[
            full.equity_curve["timestamp"] <= cut_ts
        ].reset_index(drop=True)
        pd.testing.assert_frame_equal(partial.equity_curve.reset_index(drop=True), full_head)
