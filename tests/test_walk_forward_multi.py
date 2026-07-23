"""Tests for multi-asset walk-forward and full-panel signal slicing."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant_trade.research.ledger import read_trials
from quant_trade.research.multi_asset_runner import run_multi_asset_research_experiment
from quant_trade.research.walk_forward_multi import run_multi_asset_walk_forward


def _panel(n: int = 420, seed: int = 8) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC")
    rows = []
    for sym, drift in [("AAA", 0.0012), ("BBB", 0.0006)]:
        close = 100 * np.cumprod(1 + rng.normal(drift, 0.012, n))
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


def test_test_split_keeps_full_signal_coverage_with_long_lookbacks(tmp_path):
    """A lookback close to the test-window length must still trade OOS."""
    data_path = tmp_path / "panel.csv"
    _panel().to_csv(data_path, index=False)
    result = run_multi_asset_research_experiment(
        {
            "mode": "multi_asset_research",
            "experiment_name": "warmup_ctx",
            "data_path": str(data_path),
            "strategy": "time_series_momentum",
            # 100-bar lookback vs a ~126-bar test window: without full-panel
            # generation the test window had almost no live signal
            "strategy_params": {"lookback_days": 100, "rebalance_frequency": "weekly"},
            "initial_cash": 100_000,
            "costs": {"percentage_commission": 0.0005},
            "output_dir": str(tmp_path / "outputs"),
        }
    )
    # signal must be live in the test window, not burned by warmup
    assert result["test_metrics"]["total_turnover"] > 0
    assert result["test_metrics"]["average_positions"] > 0.5


def test_walk_forward_multi_windows_ledger_and_aggregate(tmp_path):
    data_path = tmp_path / "panel.csv"
    _panel().to_csv(data_path, index=False)
    config = {
        "mode": "multi_asset_walk_forward",
        "experiment_name": "wf_multi",
        "data_path": str(data_path),
        "strategy": "time_series_momentum",
        "strategy_params": {"rebalance_frequency": "weekly"},
        "parameter_grid": {"lookback_days": [21, 42]},
        "split": {"train_size": 168, "test_size": 63, "step_size": 63, "embargo_bars": 5},
        "initial_cash": 100_000,
        "costs": {"percentage_commission": 0.0005},
        "overfitting": {"max_walk_forward_pbo": 1.0, "min_windows": 2},
        "output_dir": str(tmp_path / "outputs"),
    }
    result = run_multi_asset_walk_forward(config)
    windows = result["windows"]
    assert len(windows) >= 2
    aggregate = result["aggregate_metrics"]
    assert aggregate["windows"] == len(windows)
    assert 0.0 <= aggregate["psr"] <= 1.0
    assert np.isfinite(aggregate["sharpe"])
    # every window trades OOS (full-panel generation: no warmup burn)
    assert (windows["test_trades"] > 0).all()
    # embargo: test starts strictly after train end with a gap
    gap = pd.Timestamp(windows.iloc[0]["test_start"]) - pd.Timestamp(windows.iloc[0]["train_end"])
    assert gap.days >= 6  # 5 embargoed bars + 1
    # Every evaluated parameter variant is recorded, not only the winner.
    trials = read_trials(tmp_path / "outputs")
    assert len(trials) == len(windows) * 2
    assert all(t["trials_in_window"] == 2 for t in trials)
    assert sum(bool(t["selected_on_train"]) for t in trials) == len(windows)
    for window in range(1, len(windows) + 1):
        assert len([t for t in trials if t["window"] == window]) == 2
    evidence = result["overfitting_evidence"]
    assert 0.0 <= evidence["walk_forward_pbo"] <= 1.0
    assert evidence["parameter_variants"] == 2
    assert evidence["authorized_for_live_trading"] is False
    # artifacts on disk
    from pathlib import Path

    out = Path(result["output_dir"])
    assert (out / "walk_forward_windows.csv").exists()
    assert (out / "aggregate_metrics.json").exists()
    assert (out / "overfitting_evidence.json").exists()
    assert (out / "oos_equity_curve.csv").exists()


def test_walk_forward_multi_rejects_bad_config(tmp_path):
    data_path = tmp_path / "panel.csv"
    _panel(n=100).to_csv(data_path, index=False)
    with pytest.raises(ValueError, match="mode"):
        run_multi_asset_walk_forward({"mode": "wrong", "data_path": str(data_path)})
    with pytest.raises(ValueError, match="insufficient data"):
        run_multi_asset_walk_forward(
            {
                "mode": "multi_asset_walk_forward",
                "data_path": str(data_path),
                "strategy": "time_series_momentum",
                "strategy_params": {"lookback_days": 10},
                "split": {"train_size": 200, "test_size": 63, "step_size": 63},
                "output_dir": str(tmp_path / "outputs"),
            }
        )
