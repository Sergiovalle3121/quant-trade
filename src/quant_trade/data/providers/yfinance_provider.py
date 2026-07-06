"""Optional yfinance provider for prototype research data."""

from __future__ import annotations

import pandas as pd

from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.schema import normalize_ohlcv
from quant_trade.data.validation import validate_ohlcv


class YFinanceProvider:
    name = "yfinance"

    def supports_interval(self, interval: str) -> bool:
        return interval in {"1d", "1h", "30m", "15m", "5m", "1m"}

    def fetch_ohlcv(self, request: HistoricalDataRequest) -> pd.DataFrame:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ImportError(
                'yfinance provider requires: python -m pip install -e ".[data]"'
            ) from exc
        raw = yf.download(
            request.symbols if len(request.symbols) > 1 else request.symbols[0],
            start=request.start.isoformat(),
            end=request.end.isoformat(),
            interval=request.interval,
            auto_adjust=request.adjusted,
            progress=False,
            group_by="ticker",
        )
        if raw.empty:
            raise ValueError("yfinance returned no rows")
        frames = []
        failures: dict[str, str] = {}
        if isinstance(raw.columns, pd.MultiIndex):
            # Isolate symbols: yfinance returns all-NaN columns for failed
            # tickers, which previously crashed or poisoned the whole batch.
            for symbol in request.symbols:
                try:
                    if symbol not in raw.columns.get_level_values(0):
                        raise ValueError("symbol missing from yfinance response")
                    part = raw[symbol].reset_index()
                    price_columns = [c for c in part.columns if c != "Date" and c != "Datetime"]
                    if part[price_columns].isna().all().all():
                        raise ValueError("yfinance returned only NaN rows (failed download)")
                    part = part.dropna(how="any")
                    if part.empty:
                        raise ValueError("no complete rows returned")
                    frames.append(
                        normalize_ohlcv(
                            part, provider=self.name, interval=request.interval, symbol=symbol
                        )
                    )
                except ValueError as exc:
                    failures[symbol] = str(exc)
        else:
            frames.append(
                normalize_ohlcv(
                    raw.reset_index(),
                    provider=self.name,
                    interval=request.interval,
                    symbol=request.symbols[0],
                )
            )
        if failures:
            details = "; ".join(f"{sym}: {msg}" for sym, msg in sorted(failures.items()))
            raise ValueError(
                f"yfinance: {len(failures)}/{len(request.symbols)} symbols failed - "
                f"refusing to return a partial panel. {details}"
            )
        return validate_ohlcv(pd.concat(frames, ignore_index=True))
