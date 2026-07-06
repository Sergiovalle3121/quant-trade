"""ccxt-based crypto market data provider (research-only, public endpoints).

Fetches spot and linear-perpetual OHLCV plus funding-rate history from any
ccxt-supported exchange using only public market-data endpoints. No API keys,
order routing, or account access. Symbols use a path-safe dashed form:

- ``BTC-USD``        -> spot market ``BTC/USD``
- ``BTC-USDT-PERP``  -> linear perpetual ``BTC/USDT:USDT``

Pagination walks a ``since`` cursor until the requested end, with a
no-progress guard; transient network errors retry with bounded exponential
backoff; per-symbol failures are collected and reported loudly instead of
silently returning a partial panel.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.data.schema import normalize_ohlcv
from quant_trade.data.validation import MarketDataValidationError, validate_ohlcv

_INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
_PAGE_LIMIT = 720
_MAX_RETRIES = 4
_BACKOFF_BASE_SECONDS = 1.0

FUNDING_COLUMNS = ["timestamp", "symbol", "funding_rate", "provider"]


class CcxtProviderError(RuntimeError):
    """Raised when a ccxt fetch fails or returns incomplete data."""


def to_ccxt_symbol(symbol: str) -> str:
    """Map the path-safe dashed request symbol to a ccxt unified symbol."""
    parts = [p for p in symbol.strip().upper().split("-") if p]
    if len(parts) == 3 and parts[2] == "PERP":
        return f"{parts[0]}/{parts[1]}:{parts[1]}"
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    raise ValueError(
        f"invalid crypto symbol '{symbol}': use BASE-QUOTE (spot) or BASE-QUOTE-PERP (perpetual)"
    )


def _date_to_ms(value: date, *, end_of_day: bool = False) -> int:
    stamp = datetime(value.year, value.month, value.day, tzinfo=UTC)
    ms = int(stamp.timestamp() * 1000)
    return ms + 86_400_000 - 1 if end_of_day else ms


class CcxtProvider:
    """Research-only OHLCV + funding-rate provider over ccxt public endpoints."""

    def __init__(self, exchange_id: str = "kraken", client: Any | None = None):
        self.exchange_id = exchange_id.strip().lower()
        if not self.exchange_id:
            raise ValueError("exchange_id cannot be empty")
        self.name = f"ccxt-{self.exchange_id}"
        self._client = client

    def supports_interval(self, interval: str) -> bool:
        return interval in _INTERVAL_MS

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import ccxt
        except ImportError as exc:
            raise ImportError(
                'ccxt provider requires: python -m pip install -e ".[crypto]"'
            ) from exc
        if not hasattr(ccxt, self.exchange_id):
            raise CcxtProviderError(f"unknown ccxt exchange: {self.exchange_id}")
        self._client = getattr(ccxt, self.exchange_id)({"enableRateLimit": True})
        return self._client

    def _retryable_errors(self) -> tuple[type[Exception], ...]:
        base: tuple[type[Exception], ...] = (ConnectionError, TimeoutError)
        try:
            import ccxt

            return (ccxt.NetworkError, *base)
        except ImportError:
            return base

    def _call_with_retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        retryable = self._retryable_errors()
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except retryable as exc:
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_BACKOFF_BASE_SECONDS * (2**attempt))
        raise CcxtProviderError(
            f"{self.name}: request failed after {_MAX_RETRIES} attempts: {last_error}"
        ) from last_error

    def _paginate(
        self,
        fetch_page: Any,
        market: str,
        start_ms: int,
        end_ms: int,
        interval_ms: int,
    ) -> list[list[Any]]:
        rows: list[list[Any]] = []
        since = start_ms
        while since <= end_ms:
            batch = self._call_with_retry(fetch_page, market, since, _PAGE_LIMIT)
            if not batch:
                break
            rows.extend(row for row in batch if start_ms <= row[0] <= end_ms)
            cursor = int(batch[-1][0]) + interval_ms
            if cursor <= since:
                break
            # Exchanges cap page sizes below the requested limit, so a short
            # batch is not an end-of-data signal; only an empty batch or the
            # cursor passing the end terminates pagination.
            since = cursor
        return rows

    def fetch_ohlcv(self, request: HistoricalDataRequest) -> pd.DataFrame:
        if not self.supports_interval(request.interval):
            raise ValueError(
                f"{self.name} supports intervals: {', '.join(sorted(_INTERVAL_MS))}"
            )
        client = self._get_client()
        interval_ms = _INTERVAL_MS[request.interval]
        start_ms = _date_to_ms(request.start)
        end_ms = _date_to_ms(request.end, end_of_day=True)
        frames: list[pd.DataFrame] = []
        failures: dict[str, str] = {}
        for symbol in request.symbols:
            market = to_ccxt_symbol(symbol)

            def fetch_page(mkt: str, since: int, limit: int) -> list[list[Any]]:
                return client.fetch_ohlcv(mkt, request.interval, since=since, limit=limit)

            try:
                raw = self._paginate(fetch_page, market, start_ms, end_ms, interval_ms)
                if not raw:
                    raise CcxtProviderError(f"no bars returned for {market}")
                frame = pd.DataFrame(
                    raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
                ).drop_duplicates("timestamp")
                frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
                frames.append(
                    normalize_ohlcv(
                        frame, provider=self.name, interval=request.interval, symbol=symbol
                    )
                )
            except (CcxtProviderError, MarketDataValidationError, ValueError) as exc:
                failures[symbol] = str(exc)
        if failures:
            details = "; ".join(f"{sym}: {msg}" for sym, msg in sorted(failures.items()))
            raise CcxtProviderError(
                f"{self.name}: {len(failures)}/{len(request.symbols)} symbols failed - "
                f"refusing to return a partial panel. {details}"
            )
        return validate_ohlcv(pd.concat(frames, ignore_index=True))

    def fetch_funding_rates(
        self, symbols: list[str], start: date, end: date
    ) -> pd.DataFrame:
        """Fetch historical funding rates for perpetual symbols (BASE-QUOTE-PERP)."""
        client = self._get_client()
        if not getattr(client, "has", {}).get("fetchFundingRateHistory", False):
            raise CcxtProviderError(
                f"{self.name}: exchange does not expose funding-rate history"
            )
        start_ms = _date_to_ms(start)
        end_ms = _date_to_ms(end, end_of_day=True)
        rows: list[dict[str, Any]] = []
        failures: dict[str, str] = {}
        for symbol in symbols:
            cleaned = symbol.strip().upper()
            if not cleaned.endswith("-PERP"):
                raise ValueError(
                    f"funding rates apply to perpetuals only; got '{symbol}' "
                    "(expected BASE-QUOTE-PERP)"
                )
            market = to_ccxt_symbol(cleaned)

            def fetch_page(mkt: str, since: int, limit: int) -> list[dict[str, Any]]:
                return client.fetch_funding_rate_history(mkt, since=since, limit=limit)

            try:
                since = start_ms
                symbol_rows: list[dict[str, Any]] = []
                while since <= end_ms:
                    batch = self._call_with_retry(fetch_page, market, since, _PAGE_LIMIT)
                    if not batch:
                        break
                    for entry in batch:
                        stamp = int(entry["timestamp"])
                        if start_ms <= stamp <= end_ms:
                            symbol_rows.append(
                                {
                                    "timestamp": pd.Timestamp(stamp, unit="ms", tz="UTC"),
                                    "symbol": cleaned,
                                    "funding_rate": float(entry["fundingRate"]),
                                    "provider": self.name,
                                }
                            )
                    cursor = int(batch[-1]["timestamp"]) + 1
                    if cursor <= since:
                        break
                    since = cursor
                if not symbol_rows:
                    raise CcxtProviderError(f"no funding history returned for {market}")
                rows.extend(symbol_rows)
            except CcxtProviderError as exc:
                failures[cleaned] = str(exc)
        if failures:
            details = "; ".join(f"{sym}: {msg}" for sym, msg in sorted(failures.items()))
            raise CcxtProviderError(
                f"{self.name}: funding fetch failed for {len(failures)} symbols - {details}"
            )
        frame = pd.DataFrame(rows, columns=FUNDING_COLUMNS)
        frame = frame.drop_duplicates(["symbol", "timestamp"]).sort_values(
            ["symbol", "timestamp"]
        )
        return frame.reset_index(drop=True)
