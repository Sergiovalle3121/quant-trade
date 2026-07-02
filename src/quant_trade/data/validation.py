"""Data quality validation for canonical OHLCV datasets."""

from __future__ import annotations

import pandas as pd

from quant_trade.data.schema import REQUIRED_BACKTEST_COLUMNS


class MarketDataValidationError(ValueError):
    """Raised when market data fails quality checks."""


def validate_ohlcv(data: pd.DataFrame, *, allow_duplicates: bool = False) -> pd.DataFrame:
    missing = [c for c in REQUIRED_BACKTEST_COLUMNS if c not in data.columns]
    if missing:
        raise MarketDataValidationError(f"missing required columns: {', '.join(missing)}")
    if data.empty:
        raise MarketDataValidationError("market data is empty")
    frame = data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    numeric = ["open", "high", "low", "close", "volume"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[REQUIRED_BACKTEST_COLUMNS].isna().any().any():
        bad = (
            frame[REQUIRED_BACKTEST_COLUMNS]
            .columns[frame[REQUIRED_BACKTEST_COLUMNS].isna().any()]
            .tolist()
        )
        raise MarketDataValidationError(f"missing or invalid values in: {bad}")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise MarketDataValidationError("prices must be positive")
    if (frame["volume"] < 0).any():
        raise MarketDataValidationError("volume must be non-negative")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
        raise MarketDataValidationError("high must be >= open, close, and low")
    if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise MarketDataValidationError("low must be <= open, close, and high")
    keys = ["timestamp"] if "symbol" not in frame.columns else ["symbol", "timestamp"]
    if frame.duplicated(keys).any():
        if allow_duplicates:
            frame = frame.drop_duplicates(keys, keep="last")
        else:
            raise MarketDataValidationError("duplicate timestamp rows detected")
    return frame.sort_values(keys).reset_index(drop=True)
