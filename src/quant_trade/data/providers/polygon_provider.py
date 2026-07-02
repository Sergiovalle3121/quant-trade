"""Polygon-style REST aggregate bars provider skeleton."""

from __future__ import annotations

import os

import pandas as pd

from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.schema import normalize_ohlcv
from quant_trade.data.validation import validate_ohlcv

_INTERVALS = {
    "1d": (1, "day"),
    "1h": (1, "hour"),
    "30m": (30, "minute"),
    "15m": (15, "minute"),
    "5m": (5, "minute"),
    "1m": (1, "minute"),
}


class PolygonProvider:
    name = "polygon"
    base_url = "https://api.polygon.io"

    def supports_interval(self, interval: str) -> bool:
        return interval in _INTERVALS

    def fetch_ohlcv(self, request: HistoricalDataRequest) -> pd.DataFrame:
        api_key = os.getenv("POLYGON_API_KEY")
        if not api_key:
            raise RuntimeError(
                "POLYGON_API_KEY is not set. Set it locally; never commit API keys or .env files."
            )
        try:
            import requests
        except ImportError as exc:
            raise ImportError(
                'polygon provider requires: python -m pip install -e ".[data]"'
            ) from exc
        mult, span = _INTERVALS[request.interval]
        frames = []
        for symbol in request.symbols:
            path = (
                f"/v2/aggs/ticker/{symbol}/range/{mult}/{span}/"
                f"{request.start.isoformat()}/{request.end.isoformat()}"
            )
            url = f"{self.base_url}{path}"
            payload = requests.get(
                url,
                params={"apiKey": api_key, "adjusted": str(request.adjusted).lower()},
                timeout=30,
            ).json()
            rows = payload.get("results", [])
            data = pd.DataFrame(
                {
                    "timestamp": pd.to_datetime([r["t"] for r in rows], unit="ms", utc=True),
                    "symbol": symbol,
                    "open": [r["o"] for r in rows],
                    "high": [r["h"] for r in rows],
                    "low": [r["l"] for r in rows],
                    "close": [r["c"] for r in rows],
                    "volume": [r.get("v", 0.0) for r in rows],
                }
            )
            frames.append(normalize_ohlcv(data, provider=self.name, interval=request.interval))
        return validate_ohlcv(pd.concat(frames, ignore_index=True))
