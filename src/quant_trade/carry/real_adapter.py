"""Read-only ccxt carry adapter. Public market data only — never trades.

This adapter is intentionally minimal and is NOT exercised by the test suite
(it would require network access and the ``crypto`` extra). It exists so the
research pipeline has a concrete, auditable path to real data with a timeout,
bounded retries, staleness accounting, and attribution. It uses only public
read endpoints (tickers, funding rate) and defines no order-placing methods.
"""

from __future__ import annotations

import time
from typing import Any

from quant_trade.carry.models import CarrySnapshot


class CcxtReadOnlyCarryAdapter:
    """Fetch spot/perp/funding snapshots via ccxt public endpoints only."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.exchange_id = str(config.get("exchange", "binanceusdm"))
        self.timeout_ms = int(config.get("timeout_ms", 10_000))
        self.max_retries = int(config.get("max_retries", 3))
        self.max_staleness_seconds = float(config.get("max_staleness_seconds", 120.0))
        # No API keys are read or required: public market data only.

    def _client(self) -> Any:
        import ccxt  # lazy import; requires the `crypto` extra

        cls = getattr(ccxt, self.exchange_id)
        # enableRateLimit + a timeout keep us polite and bounded.
        return cls({"enableRateLimit": True, "timeout": self.timeout_ms})

    def _with_retries(self, fn: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - bounded retry on any client error
                last_exc = exc
                time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"read failed after {self.max_retries} retries: {last_exc}")

    def fetch_snapshots(self, symbol: str, exchange: str) -> list[CarrySnapshot]:
        client = self._client()
        perp_symbol = f"{symbol}/USDT:USDT"
        spot_symbol = f"{symbol}/USDT"
        ticker = self._with_retries(lambda: client.fetch_ticker(perp_symbol))
        spot = self._with_retries(lambda: client.fetch_ticker(spot_symbol))
        funding = self._with_retries(lambda: client.fetch_funding_rate(perp_symbol))
        captured = time.time()
        age = max(0.0, captured - float(funding.get("timestamp", captured * 1000)) / 1000.0)
        return [
            CarrySnapshot(
                symbol=symbol,
                exchange=exchange or self.exchange_id,
                captured_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(captured)),
                spot_price=float(spot["last"]),
                perp_mark_price=float(ticker["last"]),
                perp_index_price=float(funding.get("indexPrice") or spot["last"]),
                realized_funding_rate=float(funding["fundingRate"]),
                data_source="real",
                staleness_seconds=age,
                source_name=f"ccxt:{self.exchange_id}",
            )
        ]
