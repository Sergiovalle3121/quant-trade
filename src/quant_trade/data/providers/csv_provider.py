"""Local CSV provider."""

from __future__ import annotations

import pandas as pd

from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.schema import normalize_ohlcv
from quant_trade.data.validation import validate_ohlcv


class CSVProvider:
    name = "csv"

    def supports_interval(self, interval: str) -> bool:
        return interval in {"1d", "1h", "30m", "15m", "5m", "1m"}

    def fetch_ohlcv(self, request: HistoricalDataRequest) -> pd.DataFrame:
        if not request.path:
            raise ValueError("csv provider requires a path in config or request")
        data = pd.read_csv(request.path)
        symbol = request.symbols[0] if len(request.symbols) == 1 else None
        return validate_ohlcv(
            normalize_ohlcv(data, provider=self.name, interval=request.interval, symbol=symbol)
        )
