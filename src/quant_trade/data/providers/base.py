"""Market data provider interface and registry."""

from __future__ import annotations

from typing import Protocol

import pandas as pd

from quant_trade.data.requests import HistoricalDataRequest


class MarketDataProvider(Protocol):
    name: str

    def fetch_ohlcv(self, request: HistoricalDataRequest) -> pd.DataFrame: ...
    def supports_interval(self, interval: str) -> bool: ...


def get_data_provider(name: str) -> MarketDataProvider:
    key = name.lower()
    if key == "csv":
        from quant_trade.data.providers.csv_provider import CSVProvider

        return CSVProvider()
    if key == "synthetic":
        from quant_trade.data.providers.synthetic_provider import SyntheticProvider

        return SyntheticProvider()
    if key == "yfinance":
        from quant_trade.data.providers.yfinance_provider import YFinanceProvider

        return YFinanceProvider()
    if key == "polygon":
        from quant_trade.data.providers.polygon_provider import PolygonProvider

        return PolygonProvider()
    raise ValueError(
        f"unknown data provider '{name}'. Valid providers: csv, polygon, synthetic, yfinance"
    )
