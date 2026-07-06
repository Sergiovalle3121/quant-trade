"""Tests for Fase C alpha components: multi-horizon TSMOM, Donchian breakout,
funding carry, vol targeting, shorts, rebalance bands, and funding accrual."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.panel import attach_funding_rates, pivot_close
from quant_trade.research.signals.base import weights_to_long
from quant_trade.research.signals.breakout import donchian_breakout
from quant_trade.research.signals.carry import funding_carry
from quant_trade.research.signals.sizing import scale_to_portfolio_vol_target
from quant_trade.research.signals.tsmom import multi_horizon_tsmom
from quant_trade.research.strategy_registry import get_research_signal_model


def _panel(n: int = 260, symbols: tuple[str, ...] = ("AAA", "BBB", "CCC"), seed: int = 9):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    rows = []
    drifts = {"AAA": 0.0015, "BBB": -0.0012, "CCC": 0.0002}
    for sym in symbols:
        close = 100 * np.cumprod(1 + rng.normal(drifts[sym], 0.015, n))
        open_ = np.concatenate([[100.0], close[:-1]])
        for i, ts in enumerate(dates):
            o, c = open_[i], close[i]
            rows.append(
                {
                    "timestamp": ts,
                    "symbol": sym,
                    "open": o,
                    "high": max(o, c) * 1.002,
                    "low": min(o, c) * 0.998,
                    "close": c,
                    "volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def test_weights_to_long_shorts_require_explicit_flag():
    idx = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    weights = pd.DataFrame({"AAA": [0.5, -0.5]}, index=idx)
    with pytest.raises(ValueError, match="allow_short"):
        weights_to_long(weights)
    frame = weights_to_long(weights, allow_short=True)
    assert (frame["target_weight"] < 0).any()


def test_vol_target_scales_gross_down_in_high_vol():
    data = _panel()
    close = pivot_close(data)
    idx = close.index
    weights = pd.DataFrame(1.0 / 3.0, index=idx[100:], columns=close.columns)
    scaled = scale_to_portfolio_vol_target(weights, close, target_volatility=0.05)
    gross = scaled.abs().sum(axis=1)
    assert (gross <= 1.0 + 1e-9).all()
    # 1.5%-daily-vol synthetic assets -> full investment far exceeds 5% target
    assert gross.iloc[-1] < 0.6
    # rows without enough history stay flat instead of trading unsized risk
    early = scale_to_portfolio_vol_target(
        pd.DataFrame(1.0 / 3.0, index=idx[:10], columns=close.columns), close, 0.05
    )
    assert float(early.abs().sum(axis=1).max()) == 0.0


def test_multi_horizon_tsmom_long_only_and_short_modes():
    data = _panel()
    params = {
        "lookbacks": [21, 63],
        "volatility_window": 42,
        "portfolio_volatility_target": 0.15,
        "max_weight_per_asset": 0.5,
        "rebalance_frequency": "weekly",
    }
    long_only = multi_horizon_tsmom(data, params)
    assert not long_only.empty
    assert (long_only["target_weight"] >= 0).all()
    both = multi_horizon_tsmom(data, {**params, "allow_short": True})
    # the engineered downtrend asset should be shorted at some point
    assert (both["target_weight"] < 0).any()
    # weights survive the engine's own validations
    res = run_multi_asset_backtest(data, both, 100_000, CostModel(), allow_short=True)
    assert not res.equity_curve.empty


def test_multi_horizon_tsmom_registered():
    model = get_research_signal_model("multi_horizon_tsmom")
    frame = model.generate(_panel(), {"lookbacks": [21, 63]})
    assert set(frame.columns) == {"timestamp", "symbol", "target_weight"}


def test_donchian_breakout_enters_after_breakout_and_exits_on_stop():
    n = 120
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    # flat, then strong breakout up, then crash through the trailing stop
    close = np.concatenate(
        [np.full(60, 100.0), np.linspace(101, 130, 30), np.linspace(112, 95, 30)]
    )
    rows = [
        {
            "timestamp": ts,
            "symbol": "AAA",
            "open": c,
            "high": c * 1.005,
            "low": c * 0.995,
            "close": c,
            "volume": 1000.0,
        }
        for ts, c in zip(dates, close, strict=True)
    ]
    frame = donchian_breakout(pd.DataFrame(rows), {"entry_window": 20, "atr_window": 10})
    wide = frame.pivot(index="timestamp", columns="symbol", values="target_weight")
    held = wide["AAA"] > 0
    assert not held.iloc[:60].any()  # no position during the flat channel
    assert held.iloc[65:85].any()  # holds during the breakout run
    assert not held.iloc[-5:].any()  # stopped out after the crash


def test_funding_carry_prefers_negative_funding_and_shorts_positive():
    data = _panel(n=120)
    dates = sorted(data["timestamp"].unique())
    funding_rows = []
    rates = {"AAA": -0.0005, "BBB": 0.0008, "CCC": 0.0001}
    for ts in dates:
        for sym, rate in rates.items():
            funding_rows.append({"timestamp": ts, "symbol": sym, "funding_rate": rate})
    panel = attach_funding_rates(data, pd.DataFrame(funding_rows))
    params = {"funding_window": 10, "quantile": 0.34, "rebalance_frequency": "weekly"}
    long_only = funding_carry(panel, params)
    held = long_only[long_only["target_weight"] > 0]["symbol"].unique()
    assert list(held) == ["AAA"]  # cheapest funding gets the long
    both = funding_carry(panel, {**params, "allow_short": True})
    shorts = both[both["target_weight"] < 0]["symbol"].unique()
    assert list(shorts) == ["BBB"]  # most expensive funding gets shorted
    with pytest.raises(ValueError, match="funding_rate"):
        funding_carry(data, params)


def test_engine_accrues_funding_costs():
    data = _panel(n=60, symbols=("AAA", "BBB", "CCC"))
    dates = sorted(data["timestamp"].unique())
    funding = pd.DataFrame(
        [
            {"timestamp": ts, "symbol": sym, "funding_rate": 0.001}
            for ts in dates
            for sym in ("AAA", "BBB", "CCC")
        ]
    )
    panel = attach_funding_rates(data, funding)
    weights = pd.DataFrame(
        [{"timestamp": dates[0], "symbol": "AAA", "target_weight": 1.0}]
    )
    with_funding = run_multi_asset_backtest(panel, weights, 10_000, CostModel())
    without = run_multi_asset_backtest(data, weights, 10_000, CostModel())
    # a long paying 10 bps/bar for ~60 bars must end meaningfully lower
    assert (
        with_funding.equity_curve.equity.iloc[-1]
        < without.equity_curve.equity.iloc[-1] * 0.97
    )


def test_rebalance_band_cuts_turnover_but_never_blocks_exits():
    data = _panel(n=140)
    model = get_research_signal_model("time_series_momentum")
    weights = model.generate(data, {"lookback_days": 21, "rebalance_frequency": "weekly"})
    no_band = run_multi_asset_backtest(data, weights, 100_000, CostModel())
    banded = run_multi_asset_backtest(
        data, weights, 100_000, CostModel(), rebalance_band=0.05
    )
    assert (
        banded.metrics["total_turnover"] < no_band.metrics["total_turnover"]
    )
    # full exits (target 0) always execute regardless of the band
    dates = sorted(data["timestamp"].unique())
    w = pd.DataFrame(
        [
            {"timestamp": dates[0], "symbol": "AAA", "target_weight": 0.04},
            {"timestamp": dates[10], "symbol": "AAA", "target_weight": 0.0},
        ]
    )
    res = run_multi_asset_backtest(data, w, 100_000, CostModel(), rebalance_band=0.05)
    after = res.equity_curve[res.equity_curve["timestamp"] > dates[11]]
    assert (after["number_of_positions"] == 0).all()
