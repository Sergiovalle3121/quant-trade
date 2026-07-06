"""Tests for gap/spike detection and dataset-hash binding."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_trade.data.quality.report import generate_quality_report


def _frame(timestamps: pd.DatetimeIndex, closes: list[float] | None = None) -> pd.DataFrame:
    n = len(timestamps)
    close = closes if closes is not None else [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": "BTC-USD",
            "open": close,
            "high": [c * 1.01 for c in close],
            "low": [c * 0.99 for c in close],
            "close": close,
            "volume": 1000.0,
        }
    )


def test_gap_detection_flags_missing_crypto_days():
    ts = pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC")
    holey = ts.delete([10, 11, 12])  # three consecutive missing days
    report = generate_quality_report(_frame(holey), expected_interval="1d", always_open=True)
    assert report.gap_count == 1
    assert report.max_gap_multiple == 4.0
    assert any("gap" in w for w in report.warnings)


def test_gap_detection_tolerates_equity_weekends():
    ts = pd.date_range("2024-01-01", periods=30, freq="B", tz="UTC")  # weekday calendar
    report = generate_quality_report(_frame(ts), expected_interval="1d", always_open=False)
    assert report.gap_count == 0


def test_spike_detection_flags_fat_finger_print():
    rng = np.random.default_rng(3)
    n = 200
    closes = list(100 * np.cumprod(1 + rng.normal(0, 0.01, n)))
    closes[100] = closes[99] * 5.0  # 5x bad print, reverts next bar
    closes[101] = closes[99]
    ts = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    report = generate_quality_report(_frame(ts, closes), expected_interval="1d", always_open=True)
    assert report.spike_count >= 2  # the spike up and the reversion down
    assert any("spike" in w for w in report.warnings)


def test_clean_data_produces_no_gap_or_spike_warnings():
    ts = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    report = generate_quality_report(_frame(ts), expected_interval="1d", always_open=True)
    assert report.gap_count == 0
    assert report.spike_count == 0


def test_research_run_records_dataset_hash(tmp_path):
    from quant_trade.data.manifest import file_sha256
    from quant_trade.research.multi_asset_runner import run_multi_asset_research_experiment

    config = {
        "mode": "multi_asset_research",
        "experiment_name": "hash_binding_test",
        "data_path": "examples/data/sample_multi_asset_ohlcv.csv",
        "strategy": "time_series_momentum",
        "strategy_params": {"lookback_days": 21, "rebalance_frequency": "weekly"},
        "initial_cash": 100000,
        "costs": {"percentage_commission": 0.0005},
        "output_dir": str(tmp_path),
    }
    result = run_multi_asset_research_experiment(config)
    from pathlib import Path

    expected = file_sha256(Path("examples/data/sample_multi_asset_ohlcv.csv"))
    assert result["dataset_binding"]["data_sha256"] == expected
    import yaml

    used = yaml.safe_load((Path(result["output_dir"]) / "config_used.yaml").read_text())
    assert used["dataset_binding"]["data_sha256"] == expected
