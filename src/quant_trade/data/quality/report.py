"""Data quality report generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

_INTERVAL_TO_TIMEDELTA = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}
# 24/7 venues (crypto) must not skip bars; exchange-calendar venues legitimately
# gap over weekends/holidays, so only multi-day holes are suspicious there.
_GAP_MULTIPLE_ALWAYS_OPEN = 1.5
_GAP_MULTIPLE_CALENDAR = 3.5
_SPIKE_ROBUST_Z = 10.0
_SPIKE_MIN_ABS_RETURN = 0.15


@dataclass
class DataQualityReport:
    row_count: int
    symbol_count: int
    min_timestamp: str
    max_timestamp: str
    missing_values_by_column: dict[str, int]
    duplicate_timestamps_by_symbol: int
    non_monotonic_timestamps: bool
    invalid_ohlc_rows: int
    zero_volume_rows: int
    gap_count: int
    max_gap_multiple: float
    spike_count: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_gaps(
    frame: pd.DataFrame, expected_interval: str | None, always_open: bool
) -> tuple[int, float]:
    """Count bar gaps larger than a tolerance multiple of the expected spacing."""
    expected = _INTERVAL_TO_TIMEDELTA.get(expected_interval or "")
    if expected is None:
        return 0, 0.0
    tolerance = _GAP_MULTIPLE_ALWAYS_OPEN if always_open else _GAP_MULTIPLE_CALENDAR
    groups = frame.groupby("symbol") if "symbol" in frame.columns else [(None, frame)]
    gap_count = 0
    max_multiple = 0.0
    for _, group in groups:
        diffs = group["timestamp"].sort_values().diff().dropna()
        if diffs.empty:
            continue
        multiples = diffs / expected
        max_multiple = max(max_multiple, float(multiples.max()))
        gap_count += int((multiples > tolerance).sum())
    return gap_count, max_multiple


def _detect_spikes(frame: pd.DataFrame) -> int:
    """Count close-to-close moves that are extreme outliers vs the symbol's own
    return distribution (robust MAD z-score), the classic fat-finger signature."""
    groups = frame.groupby("symbol") if "symbol" in frame.columns else [(None, frame)]
    spikes = 0
    for _, group in groups:
        closes = group.sort_values("timestamp")["close"].astype(float)
        returns = closes.pct_change().dropna()
        if len(returns) < 10:
            continue
        median = returns.median()
        mad = (returns - median).abs().median()
        if mad <= 0:
            big = returns.abs() > _SPIKE_MIN_ABS_RETURN
            spikes += int(big.sum())
            continue
        robust_z = (returns - median).abs() / (1.4826 * mad)
        extreme = (robust_z > _SPIKE_ROBUST_Z) & (returns.abs() > _SPIKE_MIN_ABS_RETURN)
        spikes += int(extreme.sum())
    return spikes


def generate_quality_report(
    data: pd.DataFrame,
    expected_interval: str | None = None,
    always_open: bool = False,
) -> DataQualityReport:
    frame = data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    warnings: list[str] = []
    keys = ["symbol", "timestamp"] if "symbol" in frame.columns else ["timestamp"]
    duplicates = int(frame.duplicated(keys).sum())
    invalid = int(
        (
            (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        ).sum()
    )
    zero_volume = int((frame["volume"] == 0).sum())
    non_mono = (
        bool(any(not g["timestamp"].is_monotonic_increasing for _, g in frame.groupby("symbol")))
        if "symbol" in frame.columns
        else not frame["timestamp"].is_monotonic_increasing
    )
    gap_count, max_gap_multiple = _detect_gaps(frame, expected_interval, always_open)
    spike_count = _detect_spikes(frame)
    if duplicates:
        warnings.append("duplicate timestamp rows detected")
    if invalid:
        warnings.append("invalid OHLC rows detected")
    if zero_volume:
        warnings.append("zero-volume rows detected")
    if gap_count:
        warnings.append(
            f"{gap_count} bar gap(s) exceed tolerance "
            f"(max gap = {max_gap_multiple:.1f}x expected {expected_interval} spacing)"
        )
    if spike_count:
        warnings.append(
            f"{spike_count} extreme return spike(s) detected (possible bad prints); "
            "inspect before using this dataset for research"
        )
    return DataQualityReport(
        len(frame),
        int(frame["symbol"].nunique()) if "symbol" in frame.columns else 1,
        str(frame["timestamp"].min()),
        str(frame["timestamp"].max()),
        {str(k): int(v) for k, v in frame.isna().sum().items()},
        duplicates,
        non_mono,
        invalid,
        zero_volume,
        gap_count,
        max_gap_multiple,
        spike_count,
        warnings,
    )
