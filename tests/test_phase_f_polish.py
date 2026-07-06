"""Fase F tests: cost calibration loop, benchmark leg in trials export,
ensemble signal, and correlation-regime de-risking."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_trade.ops.fill_analysis import FillAnalysis, analyze_fills, calibrate_cost_model
from quant_trade.research.signals.ensemble import ensemble_signal, signal_correlation_report
from quant_trade.research.signals.sizing import correlation_regime_scaler
from quant_trade.research.strategy_registry import get_research_signal_model


def _write_orders_and_fills(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    orders = [
        # buy filled 2 bps ABOVE plan: adverse (+2 bps)
        {"order_id": "o1", "side": "buy", "quantity": 10, "price": 100.0, "status": "filled"},
        # sell filled 4 bps BELOW plan: adverse (+4 bps) - the old netting
        # treated this as NEGATIVE slippage and cancelled the buy leg
        {"order_id": "o2", "side": "sell", "quantity": 10, "price": 100.0, "status": "filled"},
        # partially filled order (two partial fills totalling 6 of 10)
        {"order_id": "o3", "side": "buy", "quantity": 10, "price": 50.0, "status": "filled"},
        {"order_id": "o4", "side": "buy", "quantity": 1, "price": 10.0, "status": "rejected"},
    ]
    fills = [
        {"order_id": "o1", "quantity": 10, "price": 100.02, "cost": 0.5},
        {"order_id": "o2", "quantity": 10, "price": 99.96, "cost": 0.5},
        {"order_id": "o3", "quantity": 3, "price": 50.0, "cost": 0.1},
        {"order_id": "o3", "quantity": 3, "price": 50.0, "cost": 0.1},
    ]
    with (run_dir / "orders.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(orders[0]))
        w.writeheader()
        [w.writerow(o) for o in orders]
    with (run_dir / "fills.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fills[0]))
        w.writeheader()
        [w.writerow(x) for x in fills]


def test_fill_analysis_side_signs_units_and_partials(tmp_path):
    _write_orders_and_fills(tmp_path)
    analysis = analyze_fills(tmp_path)
    # both legs adverse: mean of (+2, +4, 0, 0) bps
    assert analysis.average_slippage_bps == pytest.approx((2 + 4) / 4, abs=0.01)
    assert analysis.partial_fill_count == 1
    # slippage cost in currency: 2bps*1000.2 + 4bps*999.6 ~ 0.60
    assert analysis.total_estimated_slippage_cost == pytest.approx(0.5998, abs=0.01)
    assert analysis.total_commissions_or_fees == pytest.approx(1.2)
    assert analysis.rejected_rate == pytest.approx(0.25)


def test_cost_calibration_suggests_conservative_parameters(tmp_path):
    _write_orders_and_fills(tmp_path)
    suggestion = calibrate_cost_model(analyze_fills(tmp_path))
    assert suggestion["status"] == "ok"
    assert suggestion["suggested_slippage_bps"] >= 2.0  # p75 of adverse slippage
    assert suggestion["suggested_percentage_commission"] > 0
    empty = calibrate_cost_model(FillAnalysis())
    assert empty["status"] == "insufficient_data"


def _panel(n: int = 200, seed: int = 4, sync_crash: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    common = rng.normal(0, 0.002, n)
    if sync_crash:
        common[120:150] = rng.normal(-0.01, 0.03, 30)  # correlated sell-off window
    rows = []
    for sym, drift in [("AAA", 0.001), ("BBB", 0.0008), ("CCC", 0.0005)]:
        idio = rng.normal(drift, 0.012, n)
        weight = 0.9 if sync_crash else 0.2  # crash regime: mostly common factor
        rets = weight * common + (1 - weight) * idio
        close = 100 * np.cumprod(1 + rets)
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
                    "volume": 1000.0,
                }
            )
    return pd.DataFrame(rows)


def test_ensemble_combines_components_and_respects_gross_cap():
    data = _panel()
    params = {
        "components": [
            {"name": "time_series_momentum", "params": {"lookback_days": 21}, "weight": 2.0},
            {"name": "moving_average_trend_filter", "params": {"sma_window": 30}, "weight": 1.0},
        ],
        "max_gross_exposure": 1.0,
    }
    frame = ensemble_signal(data, params)
    assert not frame.empty
    gross = frame.groupby("timestamp")["target_weight"].apply(lambda s: s.abs().sum())
    assert (gross <= 1.0 + 1e-9).all()
    # registered and reachable through the registry like any other signal
    model = get_research_signal_model("ensemble")
    assert not model.generate(data, params).empty
    with pytest.raises(ValueError, match="at least two|just that component"):
        ensemble_signal(data, {"components": [params["components"][0]]})


def test_signal_correlation_report_flags_duplicate_factors():
    data = _panel()
    report = signal_correlation_report(
        data,
        [
            {"name": "time_series_momentum", "params": {"lookback_days": 21}},
            {"name": "time_series_momentum", "params": {"lookback_days": 25}},
        ],
    )
    # near-identical lookbacks = one factor: correlation must be very high
    assert report.iloc[0, 1] > 0.8


def test_correlation_regime_scaler_derisks_synchronized_selloffs():
    calm = _panel(sync_crash=False)
    crash = _panel(sync_crash=True)
    from quant_trade.data.panel import pivot_close

    for panel, expect_derisked in [(calm, False), (crash, True)]:
        close = pivot_close(panel)
        idx = close.index[150:160]
        weights = pd.DataFrame(1.0 / 3.0, index=idx, columns=close.columns)
        scaled = correlation_regime_scaler(
            weights, close, correlation_window=42, correlation_threshold=0.6, derisk_factor=0.5
        )
        derisked = bool((scaled.abs().sum(axis=1) < 0.99).any())
        assert derisked == expect_derisked, f"expect_derisked={expect_derisked}"


def test_trials_export_joins_real_benchmark(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    days = pd.date_range("2026-01-01", periods=4, freq="D", tz="UTC")
    with (run / "account_snapshots.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "cash", "equity", "gross_exposure",
                                          "realized_pnl", "unrealized_pnl", "drawdown"])
        w.writeheader()
        for i, d in enumerate(days):
            w.writerow({"timestamp": str(d), "cash": 20000, "equity": 100000 * (1 + 0.001 * i),
                        "gross_exposure": 0.8, "realized_pnl": 0, "unrealized_pnl": 0,
                        "drawdown": 0})
    bench = tmp_path / "bench.csv"
    closes = [100.0, 102.0, 101.0, 103.0]
    pd.DataFrame(
        {
            "timestamp": days,
            "symbol": "BTC-USD",
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": 1,
        }
    ).to_csv(bench, index=False)
    from quant_trade.trials.export import export_daily_records_from_paper_run
    from quant_trade.trials.tracker import load_trial_timeseries

    out = export_daily_records_from_paper_run(
        run, "t1", "s1", tmp_path / "trials", benchmark_data=bench, benchmark_symbol="BTC-USD"
    )
    records = load_trial_timeseries("t1", out)
    assert records[1].benchmark_return == pytest.approx(0.02)
    assert records[1].excess_return == pytest.approx(records[1].daily_return - 0.02)
