"""TEST-ONLY recorded-response builders for Bybit and OKX shapes.

These payloads are **synthetic**. They reproduce the documented JSON shape of
each venue's public endpoints so the parse/pagination/resume paths can be
exercised without a network, and nothing more. They are not market data, they
are not a capture, and every receipt written from them carries
``source_kind="recorded_test_response"`` — a provenance class that
:mod:`quant_trade.evidence.receipts` can never resolve to REAL, so no strategy
can be promoted from them.

The price path is a deterministic function of the timestamp: no randomness, so
a replayed run produces byte-identical evidence.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

HOUR_MS = 3_600_000


def _price(ts_ms: int, *, base: float, amplitude: float, period_hours: float) -> float:
    hours = ts_ms / HOUR_MS
    return round(base * (1.0 + amplitude * math.sin(2 * math.pi * hours / period_hours)), 2)


@dataclass
class FakeVenue:
    """A deterministic stand-in for one venue's public market-data API."""

    venue: str
    symbol: str = "BTC"
    start_ms: int = 0
    end_ms: int = 0
    interval_minutes: int = 60
    funding_interval_hours: float = 8.0
    #: Optional second funding regime: settlements at or after this stamp use
    #: ``funding_interval_hours_after``. Exercises interval-change detection.
    interval_change_at_ms: int | None = None
    funding_interval_hours_after: float = 4.0
    funding_rate_base: float = 0.00005
    #: Injected faults, consumed in order: "transport", "429", "500".
    faults: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    _fault_index: int = 0

    # --- series generation -------------------------------------------------

    def bar_stamps(self) -> list[int]:
        step = self.interval_minutes * 60_000
        first = self.start_ms - (self.start_ms % step)
        if first < self.start_ms:
            first += step
        return list(range(first, self.end_ms + 1, step))

    def settlement_stamps(self) -> list[int]:
        stamps: list[int] = []
        step = int(self.funding_interval_hours * HOUR_MS)
        cursor = self.start_ms - (self.start_ms % step)
        if cursor < self.start_ms:
            cursor += step
        while cursor <= self.end_ms:
            stamps.append(cursor)
            if self.interval_change_at_ms is not None and cursor >= self.interval_change_at_ms:
                step = int(self.funding_interval_hours_after * HOUR_MS)
            cursor += step
        return stamps

    def funding_rate(self, ts_ms: int) -> float:
        wave = math.sin(2 * math.pi * (ts_ms / HOUR_MS) / (24 * 30))
        return round(self.funding_rate_base + 0.00004 * wave, 8)

    def _ohlc(self, ts_ms: int, kind: str) -> tuple[float, float, float, float]:
        base = {"spot": 64000.0, "perp": 64010.0, "mark": 64008.0, "index": 63999.0}[kind]
        close = _price(ts_ms, base=base, amplitude=0.02, period_hours=24 * 14)
        open_ = _price(
            ts_ms - self.interval_minutes * 60_000, base=base, amplitude=0.02, period_hours=24 * 14
        )
        high = round(max(open_, close) * 1.0008, 2)
        low = round(min(open_, close) * 0.9992, 2)
        return open_, high, low, close

    # --- fault injection ---------------------------------------------------

    def _next_fault(self) -> str | None:
        if self._fault_index < len(self.faults):
            fault = self.faults[self._fault_index]
            self._fault_index += 1
            return fault
        return None

    # --- transport ---------------------------------------------------------

    def fetch(self, url: str) -> tuple[int, bytes, dict[str, str]]:
        self.calls.append(url)
        fault = self._next_fault()
        if fault == "transport":
            raise OSError("simulated transport failure")
        if fault in ("429", "500"):
            return int(fault), b'{"retCode":10006,"retMsg":"rate limit"}', {}
        parts = urlsplit(url)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        path = parts.path
        if self.venue == "bybit":
            return 200, self._bybit(path, query), {}
        return 200, self._okx(path, query), {}

    # --- bybit shapes ------------------------------------------------------

    def _bybit(self, path: str, query: dict[str, str]) -> bytes:
        native = f"{self.symbol}USDT"
        if path.endswith("/market/time"):
            return json.dumps(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "timeSecond": str(self.end_ms // 1000),
                        "timeNano": str(self.end_ms * 1_000_000),
                    },
                }
            ).encode()
        if path.endswith("/market/instruments-info"):
            return json.dumps(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "category": "linear",
                        "list": [
                            {
                                "symbol": native,
                                "status": "Trading",
                                "contractType": "LinearPerpetual",
                                "quoteCoin": "USDT",
                                "settleCoin": "USDT",
                                "launchTime": "1584230400000",
                                "fundingInterval": int(self.funding_interval_hours * 60),
                                "lotSizeFilter": {"minOrderQty": "0.001", "qtyStep": "0.001"},
                                "priceFilter": {"tickSize": "0.10"},
                            }
                        ],
                    },
                }
            ).encode()
        if path.endswith("/market/funding/history"):
            end = int(query.get("endTime", self.end_ms))
            limit = int(query.get("limit", 200))
            stamps = [s for s in self.settlement_stamps() if s <= end]
            page = sorted(stamps, reverse=True)[:limit]
            return json.dumps(
                {
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "category": "linear",
                        "list": [
                            {
                                "symbol": native,
                                "fundingRate": f"{self.funding_rate(s):.8f}",
                                "fundingRateTimestamp": str(s),
                            }
                            for s in page
                        ],
                    },
                }
            ).encode()
        kind = {
            "/v5/market/kline": "spot" if query.get("category") == "spot" else "perp",
            "/v5/market/mark-price-kline": "mark",
            "/v5/market/index-price-kline": "index",
        }[path]
        end = int(query.get("end", self.end_ms))
        limit = int(query.get("limit", 1000))
        stamps = sorted((s for s in self.bar_stamps() if s <= end), reverse=True)[:limit]
        rows = []
        for stamp in stamps:
            open_, high, low, close = self._ohlc(stamp, kind)
            entry = [str(stamp), f"{open_:.2f}", f"{high:.2f}", f"{low:.2f}", f"{close:.2f}"]
            if kind in ("spot", "perp"):
                entry += ["120.5", "7700000.0"]
            rows.append(entry)
        return json.dumps(
            {
                "retCode": 0,
                "retMsg": "OK",
                "result": {
                    "category": query.get("category", "linear"),
                    "symbol": native,
                    "list": rows,
                },
            }
        ).encode()

    # --- okx shapes --------------------------------------------------------

    def _okx(self, path: str, query: dict[str, str]) -> bytes:
        if path.endswith("/public/time"):
            return json.dumps({"code": "0", "msg": "", "data": [{"ts": str(self.end_ms)}]}).encode()
        if path.endswith("/public/instruments"):
            return json.dumps(
                {
                    "code": "0",
                    "msg": "",
                    "data": [
                        {
                            "instId": f"{self.symbol}-USDT-SWAP",
                            "instType": "SWAP",
                            "state": "live",
                            "ctType": "linear",
                            "quoteCcy": "USDT",
                            "settleCcy": "USDT",
                            "listTime": "1573553400000",
                            "ctVal": "0.01",
                            "ctValCcy": "BTC",
                            "minSz": "1",
                            "tickSz": "0.1",
                            "lotSz": "1",
                        }
                    ],
                }
            ).encode()
        if path.endswith("/public/funding-rate-history"):
            after = int(query.get("after", self.end_ms + 1))
            limit = int(query.get("limit", 100))
            stamps = sorted((s for s in self.settlement_stamps() if s < after), reverse=True)
            return json.dumps(
                {
                    "code": "0",
                    "msg": "",
                    "data": [
                        {
                            "instType": "SWAP",
                            "instId": f"{self.symbol}-USDT-SWAP",
                            "fundingRate": f"{self.funding_rate(s) + 0.000005:.8f}",
                            "realizedRate": f"{self.funding_rate(s):.8f}",
                            "fundingTime": str(s),
                            "method": "current_period",
                        }
                        for s in stamps[:limit]
                    ],
                }
            ).encode()
        kind = {
            "/api/v5/market/history-candles": (
                "spot" if query.get("instId", "").count("-") == 1 else "perp"
            ),
            "/api/v5/market/history-mark-price-candles": "mark",
            "/api/v5/market/history-index-candles": "index",
        }[path]
        after = int(query.get("after", self.end_ms + 1))
        limit = int(query.get("limit", 100))
        stamps = sorted((s for s in self.bar_stamps() if s < after), reverse=True)[:limit]
        rows = []
        for stamp in stamps:
            open_, high, low, close = self._ohlc(stamp, kind)
            prices = [f"{open_:.2f}", f"{high:.2f}", f"{low:.2f}", f"{close:.2f}"]
            if kind in ("spot", "perp"):
                rows.append([str(stamp), *prices, "120.5", "7700000.0", "7700000.0", "1"])
            else:
                rows.append([str(stamp), *prices, "1"])
        return json.dumps({"code": "0", "msg": "", "data": rows}).encode()


def counting_fetcher(venue: FakeVenue) -> Any:
    """Return a fetcher closure suitable for :func:`run_backfill`."""

    def _fetch(url: str) -> tuple[int, bytes, dict[str, str]]:
        return venue.fetch(url)

    return _fetch


def no_sleep(_seconds: float) -> None:
    """Sleeper stub: tests never actually wait."""
    return None


__all__ = ["HOUR_MS", "FakeVenue", "counting_fetcher", "no_sleep"]
