"""Polygon-style REST aggregate bars provider skeleton."""

from __future__ import annotations

import os
import time

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
_MAX_RETRIES = 4
_BACKOFF_BASE_SECONDS = 2.0
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class PolygonProviderError(RuntimeError):
    """Raised when the Polygon API fails or returns incomplete data."""


class PolygonProvider:
    name = "polygon"
    base_url = "https://api.polygon.io"

    def supports_interval(self, interval: str) -> bool:
        return interval in _INTERVALS

    def _get_json(self, requests_mod, url: str, params: dict | None) -> dict:
        """GET with status checking and bounded retry on throttling/5xx.

        Silent failure modes are the enemy here: an unchecked 429 previously
        produced an empty result set that passed validation as a partial panel.
        """
        last_detail = ""
        for attempt in range(_MAX_RETRIES):
            response = requests_mod.get(url, params=params, timeout=30)
            if response.status_code == 200:
                return response.json()
            last_detail = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code not in _RETRYABLE_STATUS:
                raise PolygonProviderError(f"polygon request failed ({last_detail})")
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
        raise PolygonProviderError(
            f"polygon request failed after {_MAX_RETRIES} attempts ({last_detail})"
        )

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
        failures: dict[str, str] = {}
        for symbol in request.symbols:
            path = (
                f"/v2/aggs/ticker/{symbol}/range/{mult}/{span}/"
                f"{request.start.isoformat()}/{request.end.isoformat()}"
            )
            url: str | None = f"{self.base_url}{path}"
            params: dict | None = {
                "apiKey": api_key,
                "adjusted": str(request.adjusted).lower(),
                "limit": 50_000,
            }
            rows: list[dict] = []
            try:
                # Aggregates are capped at 50k results per response; follow
                # next_url so truncated ranges are never silently dropped.
                while url:
                    payload = self._get_json(requests, url, params)
                    rows.extend(payload.get("results", []) or [])
                    url = payload.get("next_url")
                    params = {"apiKey": api_key} if url else None
                if not rows:
                    raise PolygonProviderError(f"no bars returned for {symbol}")
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
            except PolygonProviderError as exc:
                failures[symbol] = str(exc)
        if failures:
            details = "; ".join(f"{sym}: {msg}" for sym, msg in sorted(failures.items()))
            raise PolygonProviderError(
                f"polygon: {len(failures)}/{len(request.symbols)} symbols failed - "
                f"refusing to return a partial panel. {details}"
            )
        return validate_ohlcv(pd.concat(frames, ignore_index=True))
