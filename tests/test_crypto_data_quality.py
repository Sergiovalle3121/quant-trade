"""Tests for the crypto-market quality checks and the honest gap check.

Every detector gets a positive case (the pathology is found), and the checks
that depend on optional inputs get a NOT_MEASURED case: a missing input must
produce a declared non-measurement, never a silent zero.
"""

from __future__ import annotations

import pandas as pd

from quant_trade.data.quality.crypto import (
    STATUS_MEASURED,
    STATUS_NOT_MEASURED,
    check_constant_price_runs,
    check_redenominations,
    check_spike_reversal_phantoms,
    check_stale_volume_runs,
    check_ticker_reuse,
    check_volume_range_incoherence,
    check_wash_turnover,
    check_zero_volume_price_moves,
    generate_crypto_quality_report,
)
from quant_trade.data.quality.report import generate_quality_report


def _frame(
    closes: list[float],
    volumes: list[float] | None = None,
    symbol: str = "ABC-USD",
    **extra_columns: list[float],
) -> pd.DataFrame:
    n = len(closes)
    volume = volumes if volumes is not None else [1000.0 + i for i in range(n)]
    base = {
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "symbol": symbol,
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": volume,
    }
    base.update(extra_columns)
    return pd.DataFrame(base)


# --- honest gap check (the (0, 0.0) bug must not survive) --------------------


def test_gap_check_without_interval_is_inferred_not_silently_zero():
    ts = pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC").delete([10, 11, 12])
    frame = _frame([100.0 + i for i in range(len(ts))])
    frame["timestamp"] = ts
    report = generate_quality_report(frame)  # no expected_interval declared
    assert report.gap_check_status == "MEASURED"
    assert report.expected_interval_used.startswith("inferred:")
    assert report.gap_count == 1
    assert any("gap" in w for w in report.warnings)


def test_gap_check_with_too_few_rows_is_not_measured():
    frame = _frame([100.0, 101.0])
    report = generate_quality_report(frame)
    assert report.gap_check_status.startswith("NOT_MEASURED")
    assert report.gap_count is None
    assert report.max_gap_multiple is None
    assert any("NOT_MEASURED" in w for w in report.warnings)


def test_gap_check_with_unknown_interval_label_is_not_measured():
    frame = _frame([100.0 + i for i in range(20)])
    report = generate_quality_report(frame, expected_interval="3d")
    assert report.gap_check_status.startswith("NOT_MEASURED")
    assert report.gap_count is None


def test_always_open_is_inferred_from_weekend_bars():
    frame = _frame([100.0 + i for i in range(30)])  # daily range includes weekends
    report = generate_quality_report(frame, expected_interval="1d")
    assert report.always_open_used is True


def test_weekday_only_data_infers_calendar_venue():
    ts = pd.date_range("2024-01-01", periods=30, freq="B", tz="UTC")
    frame = _frame([100.0 + i for i in range(30)])
    frame["timestamp"] = ts
    report = generate_quality_report(frame, expected_interval="1d")
    assert report.always_open_used is False
    assert report.gap_count == 0  # weekend holes tolerated on a calendar venue


# --- crypto detectors --------------------------------------------------------


def test_constant_price_run_flags_dead_but_listed_token():
    closes = [100.0, 101.0] + [50.0] * 10 + [51.0, 52.0]
    result = check_constant_price_runs(_frame(closes))
    assert result.status == STATUS_MEASURED
    assert result.finding_count == 1
    assert result.affected_symbols == ["ABC-USD"]


def test_constant_price_run_ignores_short_flat_stretches():
    closes = [100.0, 100.0, 100.0, 101.0, 101.0, 102.0]
    result = check_constant_price_runs(_frame(closes))
    assert result.finding_count == 0


def test_zero_volume_price_move_is_phantom():
    closes = [100.0, 105.0, 110.0, 115.0]
    volumes = [1000.0, 0.0, 1000.0, 1000.0]  # bar 1 moved the price on no volume
    result = check_zero_volume_price_moves(_frame(closes, volumes))
    assert result.finding_count == 1


def test_stale_volume_run_flags_quota_shaped_reporting():
    closes = [100.0 + i * 0.5 for i in range(12)]
    volumes = [1234.0] * 8 + [900.0, 950.0, 1000.0, 1050.0]
    result = check_stale_volume_runs(_frame(closes, volumes))
    assert result.finding_count == 1


def test_stale_zero_volume_run_is_not_wash():
    closes = [100.0 + i * 0.5 for i in range(12)]
    volumes = [0.0] * 8 + [900.0, 950.0, 1000.0, 1050.0]
    result = check_stale_volume_runs(_frame(closes, volumes))
    assert result.finding_count == 0  # a halted book is not fake volume


def test_volume_range_incoherence_flags_heavy_flat_bars():
    closes = [100.0, 100.0] + [101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0]
    volumes = [50_000.0, 50_000.0] + [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0]
    frame = _frame(closes, volumes)
    frame.loc[:1, "high"] = 100.0
    frame.loc[:1, "low"] = 100.0
    result = check_volume_range_incoherence(frame)
    assert result.finding_count == 2  # heavy volume, zero range


def test_single_trade_flat_bar_is_tolerated():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    frame = _frame(closes, [1000.0, 1000.0, 5.0, 1000.0, 1000.0, 1000.0])
    frame.loc[2, "high"] = frame.loc[2, "close"]
    frame.loc[2, "low"] = frame.loc[2, "close"]
    result = check_volume_range_incoherence(frame)
    assert result.finding_count == 0


def test_spike_reversal_on_low_volume_is_phantom():
    closes = [100.0] * 10 + [200.0, 100.5] + [100.0] * 8
    volumes = [1000.0] * 10 + [1.0, 1000.0] + [1000.0] * 8
    result = check_spike_reversal_phantoms(_frame(closes, volumes))
    assert result.finding_count >= 1


def test_high_volume_spike_is_not_a_phantom():
    closes = [100.0] * 10 + [200.0, 100.5] + [100.0] * 8
    volumes = [1000.0] * 10 + [50000.0, 1000.0] + [1000.0] * 8
    result = check_spike_reversal_phantoms(_frame(closes, volumes))
    assert result.finding_count == 0


def test_redenomination_is_supply_change_not_crash():
    closes = [100.0] * 5 + [9.0] + [9.1] * 4
    supply = [1_000_000.0] * 5 + [11_100_000.0] + [11_100_000.0] * 4
    frame = _frame(closes, circulating_supply=supply)
    result = check_redenominations(frame)
    assert result.status == STATUS_MEASURED
    assert result.finding_count == 1


def test_redenomination_without_supply_is_not_measured():
    result = check_redenominations(_frame([100.0, 10.0, 10.1]))
    assert result.status == STATUS_NOT_MEASURED
    assert "circulating_supply" in result.reason
    assert result.finding_count == 0


def test_wash_turnover_flags_sustained_excess():
    closes = [1.0] * 12
    volumes = [5_000_000.0] * 8 + [1000.0] * 4  # notional 5x mcap for 8 bars
    mcap = [1_000_000.0] * 12
    frame = _frame(closes, volumes, market_cap=mcap)
    result = check_wash_turnover(frame)
    assert result.finding_count == 8


def test_wash_turnover_without_market_cap_is_not_measured():
    result = check_wash_turnover(_frame([1.0, 1.0, 1.0]))
    assert result.status == STATUS_NOT_MEASURED
    assert "market_cap" in result.reason


def test_ticker_reuse_detects_identity_welds():
    universe = pd.DataFrame(
        {
            "coin_id": [1, 1, 2, 3, 3],
            "symbol": ["OLD", "NEW", "NEW", "SOLO", "SOLO"],
        }
    )
    result = check_ticker_reuse(universe)
    # NEW maps to ids 1 and 2 (reuse); id 1 traded as OLD then NEW (rename).
    assert result.finding_count == 2
    assert "NEW" in result.affected_symbols
    assert "id:1" in result.affected_symbols


def test_ticker_reuse_without_universe_is_not_measured():
    result = check_ticker_reuse(None)
    assert result.status == STATUS_NOT_MEASURED


# --- assembled report --------------------------------------------------------


def test_clean_frame_yields_no_findings_and_declares_non_measurements():
    closes = [100.0 * (1.01 ** i) for i in range(40)]
    report = generate_crypto_quality_report(_frame(closes))
    measured = [c for c in report.checks if c.status == STATUS_MEASURED]
    not_measured = [c for c in report.checks if c.status == STATUS_NOT_MEASURED]
    assert all(c.finding_count == 0 for c in measured)
    # redenominations, wash_turnover and ticker_reuse lack their inputs here
    assert {c.name for c in not_measured} == {
        "redenominations",
        "wash_turnover",
        "ticker_reuse",
    }
    assert all("NOT_MEASURED" in w for w in report.warnings)


def test_report_serializes_to_dict():
    report = generate_crypto_quality_report(_frame([100.0, 101.0, 102.0]))
    payload = report.to_dict()
    assert {c["name"] for c in payload["checks"]} >= {
        "constant_price_runs",
        "zero_volume_price_moves",
    }
