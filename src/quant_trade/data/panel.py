"""Multi-symbol canonical OHLCV panel utilities."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_trade.data.validation import MarketDataValidationError

REQUIRED_PANEL_COLUMNS = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]


def validate_panel_schema(data: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_PANEL_COLUMNS if c not in data.columns]
    if missing:
        raise MarketDataValidationError(f"missing required panel columns: {', '.join(missing)}")
    if data.empty:
        raise MarketDataValidationError("panel data is empty")
    f = data.copy()
    # Expand only bare dates like "2020-01-02Z"; a broader suffix match would
    # corrupt standard ISO timestamps ("...T00:00:00Z") into invalid strings.
    raw_ts = f["timestamp"].astype(str).str.replace(
        r"^(\d{4}-\d{2}-\d{2})Z$", r"\1T00:00:00Z", regex=True
    )
    f["timestamp"] = pd.to_datetime(raw_ts, utc=True, errors="coerce")
    f["symbol"] = f["symbol"].astype(str).str.upper().str.strip()
    for c in ["open", "high", "low", "close", "volume"]:
        f[c] = pd.to_numeric(f[c], errors="coerce")
    if f[REQUIRED_PANEL_COLUMNS].isna().any().any():
        raise MarketDataValidationError("panel contains missing or invalid required values")
    if (f["symbol"] == "").any():
        raise MarketDataValidationError("symbol cannot be empty")
    if f.duplicated(["timestamp", "symbol"]).any():
        raise MarketDataValidationError("duplicate timestamp/symbol rows detected")
    if (f[["open", "high", "low", "close"]] <= 0).any().any():
        raise MarketDataValidationError("prices must be positive")
    if (f["volume"] < 0).any():
        raise MarketDataValidationError("volume must be non-negative")
    if (f["high"] < f[["open", "close", "low"]].max(axis=1)).any():
        raise MarketDataValidationError("high must be >= open, close, and low")
    if (f["low"] > f[["open", "close", "high"]].min(axis=1)).any():
        raise MarketDataValidationError("low must be <= open, close, and high")
    return f.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def pivot_close(data: pd.DataFrame) -> pd.DataFrame:
    return (
        validate_panel_schema(data)
        .pivot(index="timestamp", columns="symbol", values="close")
        .sort_index()
    )


def pivot_open(data: pd.DataFrame) -> pd.DataFrame:
    return (
        validate_panel_schema(data)
        .pivot(index="timestamp", columns="symbol", values="open")
        .sort_index()
    )


def calculate_returns(close_prices: pd.DataFrame) -> pd.DataFrame:
    """Simple returns.

    Missing prices produce missing returns; no aggressive forward fill is used.
    """
    return close_prices.sort_index().pct_change(fill_method=None)


def align_universe(data: pd.DataFrame, min_history_bars: int | None = None) -> pd.DataFrame:
    """Filter symbols with insufficient full-sample history.

    Use only for fixed-universe studies to avoid lookahead bias.
    """
    f = validate_panel_schema(data)
    if min_history_bars is None:
        return f
    counts = f.groupby("symbol").size()
    keep = counts[counts >= min_history_bars].index
    return f[f["symbol"].isin(keep)].reset_index(drop=True)


def load_canonical_dataset(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Canonical dataset not found: {p}. Run quant-trade data fetch ... first."
        )
    return validate_panel_schema(pd.read_csv(p))
