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
        if isinstance(raw.columns, pd.MultiIndex):
            for symbol in request.symbols:
                part = raw[symbol].reset_index()
                frames.append(
                    normalize_ohlcv(
                        part, provider=self.name, interval=request.interval, symbol=symbol
                    )
                )
        else:
            frames.append(
                normalize_ohlcv(
                    raw.reset_index(),
                    provider=self.name,
                    interval=request.interval,
                    symbol=request.symbols[0],
                )
            )
        return validate_ohlcv(pd.concat(frames, ignore_index=True))
