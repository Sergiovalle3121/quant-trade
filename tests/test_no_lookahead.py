"""Causality regression harness.

These tests institutionalize the platform's core philosophy: nothing the
engines report may depend on data that was not available at decision time.

Two invariants are enforced:
1. Truncation invariance — running on ``data[:t]`` must reproduce the first
   ``t`` bars of the full run's equity curve and every trade closed by ``t``.
2. Future-perturbation locality — changing bar ``t+k`` must not change any
   output before ``t+k``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.engine import BacktestEngine
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.metrics.performance import periods_per_year
from quant_trade.research.signals.momentum import time_series_momentum
from quant_trade.research.walk_forward import _stitch_oos_equity
from quant_trade.risk.risk_manager import RiskManager
from quant_trade.strategies.sma_crossover import SmaCrossoverStrategy


def _single_asset_data(n: int = 120, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    open_ = np.concatenate([[100.0], close[:-1] * (1 + rng.normal(0, 0.002, n - 1))])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1_000_000.0,
        }
    )


def _panel(n: int = 90, symbols: tuple[str, ...] = ("AAA", "BBB"), seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    dates = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    for sym in symbols:
        close = 100 * np.cumprod(1 + rng.normal(0.0004, 0.012, n))
        open_ = np.concatenate([[100.0], close[:-1]])
        for i, ts in enumerate(dates):
            o, c = open_[i], close[i]
            rows.append(
                {
                    "timestamp": ts,
                    "symbol": sym,
                    "open": o,
                    "high": max(o, c) * 1.001,
                    "low": min(o, c) * 0.999,
                    "close": c,
                    "volume": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def test_single_asset_truncation_invariance():
    data = _single_asset_data()
    strategy = SmaCrossoverStrategy(fast_window=5, slow_window=15)
    engine = BacktestEngine(initial_cash=10_000.0)
    full = engine.run(data, strategy)
    for cut in (40, 80, 100):
        partial = BacktestEngine(initial_cash=10_000.0).run(data.iloc[:cut].copy(), strategy)
        full_head = full.equity_curve.iloc[:cut].reset_index(drop=True)
        part_head = partial.equity_curve.reset_index(drop=True)
        pd.testing.assert_frame_equal(part_head, full_head)


def test_single_asset_future_perturbation_locality():
    data = _single_asset_data()
    strategy = SmaCrossoverStrategy(fast_window=5, slow_window=15)
    base = BacktestEngine(initial_cash=10_000.0).run(data, strategy)
    k = 90
    perturbed = data.copy()
    perturbed.loc[perturbed.index >= k, ["open", "high", "low", "close"]] *= 1.30
    other = BacktestEngine(initial_cash=10_000.0).run(perturbed, strategy)
    pd.testing.assert_frame_equal(
        other.equity_curve.iloc[:k].reset_index(drop=True),
        base.equity_curve.iloc[:k].reset_index(drop=True),
    )


def test_trades_never_exit_before_entry_and_stops_fill_at_stop_level():
    data = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC"),
            "open": [100.0, 100.0, 200.0, 95.0],
            "high": [100.0, 100.0, 210.0, 96.0],
            "low": [100.0, 100.0, 90.0, 94.0],
            "close": [100.0, 100.0, 95.0, 95.0],
            "volume": [1000.0] * 4,
        }
    )

    class _Sig:
        name = "sig"

        def generate_signals(self, frame: pd.DataFrame) -> pd.DataFrame:
            return pd.DataFrame({"timestamp": frame["timestamp"], "signal": [0, 1, 0, 0]})

    engine = BacktestEngine(
        initial_cash=10_000.0,
        transaction_cost_bps=0.0,
        slippage_bps=0.0,
        risk_manager=RiskManager(max_position_pct=1.0, max_trade_pct=1.0, stop_loss_pct=0.25),
    )
    result = engine.run(data, _Sig())
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_time >= trade.entry_time
    # entry fills at bar-3 open (200); stop level 150 is breached by the bar-3
    # low (90) and fills at the stop level, not at the close
    assert trade.entry_price == 200.0
    assert abs(trade.exit_price - 150.0) < 1e-9
    # the decision bar's snapshot must not contain the future fill
    assert result.equity_curve.iloc[1].position_quantity == 0


def test_multi_asset_all_flat_target_exits_to_cash():
    data = _panel()
    dates = sorted(data["timestamp"].unique())
    weights = pd.DataFrame(
        [
            {"timestamp": dates[0], "symbol": "AAA", "target_weight": 1.0},
            {"timestamp": dates[0], "symbol": "BBB", "target_weight": 0.0},
            {"timestamp": dates[10], "symbol": "AAA", "target_weight": 0.0},
            {"timestamp": dates[10], "symbol": "BBB", "target_weight": 0.0},
        ]
    )
    result = run_multi_asset_backtest(data, weights, 10_000.0, CostModel())
    after = result.equity_curve[result.equity_curve["timestamp"] > dates[11]]
    assert (after["number_of_positions"] == 0).all()
    assert (result.trades["side"] == "sell").sum() >= 1


def test_multi_asset_sizing_does_not_see_execution_bar_close():
    dates = pd.date_range("2024-02-01", periods=3, freq="D", tz="UTC")
    bars = [(100.0, 100.0), (100.0, 200.0), (200.0, 200.0)]
    data = pd.DataFrame(
        {
            "timestamp": dates,
            "symbol": "AAA",
            "open": [o for o, _ in bars],
            "high": [max(o, c) for o, c in bars],
            "low": [min(o, c) for o, c in bars],
            "close": [c for _, c in bars],
            "volume": 1000.0,
        }
    )
    weights = pd.DataFrame(
        [
            {"timestamp": dates[0], "symbol": "AAA", "target_weight": 1.0},
            {"timestamp": dates[1], "symbol": "AAA", "target_weight": 1.0},
        ]
    )
    result = run_multi_asset_backtest(data, weights, 10_000.0, CostModel())
    # rebalance at bar-3 open: valued at the open, the portfolio is already at
    # target, so knowing the doubled close must not produce an add-on trade
    day3 = result.trades[result.trades["timestamp"] == dates[2]]
    assert day3.empty


def test_multi_asset_truncation_invariance_through_signal_pipeline():
    data = _panel(n=120)
    params = {"lookback_days": 20, "rebalance_frequency": "weekly", "max_weight_per_asset": 0.6}
    dates = sorted(data["timestamp"].unique())
    full_weights = time_series_momentum(data, params)
    full = run_multi_asset_backtest(data, full_weights, 10_000.0, CostModel())
    cut_ts = dates[79]
    partial_data = data[data["timestamp"] <= cut_ts].copy()
    partial_weights = time_series_momentum(partial_data, params)
    partial = run_multi_asset_backtest(partial_data, partial_weights, 10_000.0, CostModel())
    full_head = full.equity_curve[full.equity_curve["timestamp"] <= cut_ts].reset_index(drop=True)
    pd.testing.assert_frame_equal(partial.equity_curve.reset_index(drop=True), full_head)


def test_walk_forward_stitching_has_no_seam_returns():
    ts1 = pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC")
    ts2 = pd.date_range("2024-01-04", periods=3, freq="D", tz="UTC")
    window1 = pd.DataFrame({"timestamp": ts1, "equity": [10_000.0, 10_500.0, 11_000.0]})
    window2 = pd.DataFrame({"timestamp": ts2, "equity": [10_000.0, 9_500.0, 9_000.0]})
    stitched = _stitch_oos_equity([window1, window2], 10_000.0)
    returns = stitched["equity"].pct_change().dropna()
    # the old concatenation manufactured a -9.09% "return" at the window seam
    # (11,000 -> 10,000); compounding window returns must not
    assert (returns > -0.06).all()
    expected_total = (11_000.0 / 10_000.0) * (9_000.0 / 10_000.0) - 1
    assert abs((stitched["equity"].iloc[-1] / 10_000.0 - 1) - expected_total) < 1e-9


def test_periods_per_year_inference():
    business_daily = pd.date_range("2020-01-01", periods=504, freq="B", tz="UTC")
    crypto_daily = pd.date_range("2020-01-01", periods=730, freq="D", tz="UTC")
    hourly = pd.date_range("2020-01-01", periods=24 * 90, freq="h", tz="UTC")
    assert abs(periods_per_year(business_daily) - 252) < 15
    assert abs(periods_per_year(crypto_daily) - 365) < 5
    assert abs(periods_per_year(hourly) - 8766) < 100
    # no timestamps -> defaults to the equity trading-day convention
    assert periods_per_year([]) == 252.0
