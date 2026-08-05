"""Order-book cost arithmetic: spread and walk-the-book slippage.

Pure functions over a parsed order book snapshot. Execution cost for a given
notional is computed by consuming visible levels and comparing the volume-
weighted fill price against the mid — so it *includes* the half-spread by
construction. A notional the visible book cannot fill returns ``None``:
"not executable at this size" is an answer, never an extrapolation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

BUY = "buy"
SELL = "sell"


@dataclass(frozen=True)
class OrderBook:
    """Snapshot of visible liquidity. Bids sorted descending, asks ascending."""

    symbol: str
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    timestamp_ms: int

    @property
    def best_bid(self) -> float:
        return self.bids[0][0]

    @property
    def best_ask(self) -> float:
        return self.asks[0][0]

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0


def parse_bybit_orderbook(raw: bytes) -> OrderBook:
    """Parse a Bybit v5 ``/market/orderbook`` response, rejecting malformed books.

    Rejections raise ``ValueError`` so callers record NOT_RUN_PARSE_REJECTED
    instead of computing costs from garbage.
    """
    payload = json.loads(raw)
    if payload.get("retCode") != 0:
        raise ValueError(f"bybit retCode {payload.get('retCode')}: {payload.get('retMsg')}")
    result = payload.get("result") or {}
    symbol = str(result.get("s", ""))
    raw_bids = result.get("b") or []
    raw_asks = result.get("a") or []
    if not raw_bids or not raw_asks:
        raise ValueError(f"{symbol}: empty side (bids={len(raw_bids)}, asks={len(raw_asks)})")
    bids = tuple((float(p), float(q)) for p, q in raw_bids)
    asks = tuple((float(p), float(q)) for p, q in raw_asks)
    for price, size in bids + asks:
        if price <= 0 or size <= 0:
            raise ValueError(f"{symbol}: non-positive level (price={price}, size={size})")
    if any(bids[i][0] <= bids[i + 1][0] for i in range(len(bids) - 1)):
        raise ValueError(f"{symbol}: bids not strictly descending")
    if any(asks[i][0] >= asks[i + 1][0] for i in range(len(asks) - 1)):
        raise ValueError(f"{symbol}: asks not strictly ascending")
    if bids[0][0] >= asks[0][0]:
        raise ValueError(f"{symbol}: crossed book (bid {bids[0][0]} >= ask {asks[0][0]})")
    return OrderBook(
        symbol=symbol,
        bids=bids,
        asks=asks,
        timestamp_ms=int(result.get("ts", 0)),
    )


def half_spread_bps(book: OrderBook) -> float:
    """Half the quoted spread, in basis points of mid."""
    return (book.best_ask - book.best_bid) / 2.0 / book.mid * 1e4


def walk_cost_bps(book: OrderBook, side: str, notional_usd: float) -> float | None:
    """Effective execution cost vs mid for a market order of ``notional_usd``.

    Walks the visible levels of the relevant side; returns the volume-weighted
    fill price's distance from mid in bps (includes the half-spread). Returns
    ``None`` when the visible book cannot fill the notional.
    """
    if side not in (BUY, SELL):
        raise ValueError(f"side must be {BUY!r} or {SELL!r}, got {side!r}")
    if notional_usd <= 0:
        raise ValueError("notional_usd must be positive")
    levels = book.asks if side == BUY else book.bids
    remaining = notional_usd
    cost = 0.0  # notional-weighted price accumulator
    filled = 0.0
    for price, size in levels:
        level_notional = price * size
        take = min(remaining, level_notional)
        cost += take * price
        filled += take
        remaining -= take
        if remaining <= 1e-9:
            break
    if remaining > 1e-9:
        return None
    vwap = cost / filled
    if side == BUY:
        return (vwap - book.mid) / book.mid * 1e4
    return (book.mid - vwap) / book.mid * 1e4


def round_trip_exec_cost_bps(book: OrderBook, notional_usd: float) -> float | None:
    """Buy walk + sell walk vs mid: the full in-and-out execution cost in bps.

    Fees are not included here; they live in the cost model, so the two
    components cannot be double-counted.
    """
    buy = walk_cost_bps(book, BUY, notional_usd)
    sell = walk_cost_bps(book, SELL, notional_usd)
    if buy is None or sell is None:
        return None
    return buy + sell


__all__ = [
    "BUY",
    "SELL",
    "OrderBook",
    "half_spread_bps",
    "parse_bybit_orderbook",
    "round_trip_exec_cost_bps",
    "walk_cost_bps",
]
