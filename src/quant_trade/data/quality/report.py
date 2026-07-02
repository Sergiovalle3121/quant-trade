"""Data quality report generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


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
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_quality_report(data: pd.DataFrame) -> DataQualityReport:
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
    if duplicates:
        warnings.append("duplicate timestamp rows detected")
    if invalid:
        warnings.append("invalid OHLC rows detected")
    if zero_volume:
        warnings.append("zero-volume rows detected")
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
        warnings,
    )
