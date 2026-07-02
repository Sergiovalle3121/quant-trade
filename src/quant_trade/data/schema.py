"""Canonical OHLCV schema normalization."""

from __future__ import annotations

import pandas as pd

CANONICAL_COLUMNS = [
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "provider",
    "interval",
]
OPTIONAL_COLUMNS = ["adjusted_close"]
REQUIRED_BACKTEST_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

_COLUMN_ALIASES = {
    "date": "timestamp",
    "datetime": "timestamp",
    "time": "timestamp",
    "adj close": "adjusted_close",
    "adj_close": "adjusted_close",
    "adjusted close": "adjusted_close",
}


def normalize_ohlcv(
    data: pd.DataFrame,
    *,
    provider: str,
    interval: str,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Normalize provider output into the canonical research schema."""
    if data.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS + OPTIONAL_COLUMNS)
    frame = data.copy()
    frame.columns = [
        _COLUMN_ALIASES.get(str(c).strip().lower(), str(c).strip().lower().replace(" ", "_"))
        for c in frame.columns
    ]
    if "timestamp" not in frame.columns and frame.index.name:
        frame = frame.reset_index()
        frame.columns = [
            _COLUMN_ALIASES.get(str(c).strip().lower(), str(c).strip().lower().replace(" ", "_"))
            for c in frame.columns
        ]
    if "symbol" not in frame.columns:
        if symbol is None:
            raise ValueError("canonical data requires a symbol column or symbol argument")
        frame["symbol"] = symbol.upper()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "adjusted_close"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["provider"] = provider
    frame["interval"] = interval
    columns = CANONICAL_COLUMNS + [c for c in OPTIONAL_COLUMNS if c in frame.columns]
    return frame.loc[:, columns].sort_values(["symbol", "timestamp"]).reset_index(drop=True)
