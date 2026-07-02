"""CSV loading and validation for OHLCV research data."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class CsvValidationError(ValueError):
    """Raised when OHLCV CSV data is missing or invalid."""


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    """Load and validate an OHLCV CSV file sorted by timestamp."""

    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"OHLCV CSV not found: {csv_path}")

    data = pd.read_csv(csv_path)
    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise CsvValidationError(f"Missing required OHLCV columns: {', '.join(missing)}")
    if data.empty:
        raise CsvValidationError("OHLCV CSV contains no rows")

    data = data.loc[:, REQUIRED_COLUMNS].copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=False, errors="coerce")
    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    if data.isna().any().any():
        bad_columns = data.columns[data.isna().any()].tolist()
        raise CsvValidationError(f"OHLCV CSV contains missing or invalid values in: {bad_columns}")
    if (data[numeric_columns] < 0).any().any() or (
        data[["open", "high", "low", "close"]] <= 0
    ).any().any():
        raise CsvValidationError("OHLC prices must be positive and volume must be non-negative")
    if (
        (data["high"] < data[["open", "close", "low"]].max(axis=1))
        | (data["low"] > data[["open", "close", "high"]].min(axis=1))
    ).any():
        raise CsvValidationError("OHLC rows contain impossible high/low relationships")

    return data.sort_values("timestamp").reset_index(drop=True)
