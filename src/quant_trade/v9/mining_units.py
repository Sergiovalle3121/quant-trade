"""Hashrate marketplace units, taken from the venue rather than assumed.

Three unit errors are easy to make here and each one moves the answer by
orders of magnitude:

1. **The speed unit is not TH/s.** NiceHash quotes SHA-256 in PH/s, and the
   price is BTC per *that* unit per day. Multiplying price by BTC/USD without
   dividing by the unit multiplier overstates the cost of hashrate by 1,000x.
2. **``limit`` is not supply.** It is the maximum *speed the buyer requests*.
   Reading it as available hashrate turns an order parameter into a market
   depth figure that does not exist.
3. **A cheap bid is not a fill.** Hashpower is allocated to the highest bids;
   an order priced below the market clears slowly or not at all. Modelling a
   purchase as "I paid X and received X worth of hashrate" assumes away the
   only real risk of the strategy.

So ``public/buy/info`` is the authority for every one of these, and a value
that is absent from the response is an error rather than a default.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any

#: Hashes per second in one unit of the venue's ``speedText``.
SPEED_UNIT_HASHES = {
    "H": 1.0,
    "KH": 1e3,
    "MH": 1e6,
    "GH": 1e9,
    "TH": 1e12,
    "PH": 1e15,
    "EH": 1e18,
}

#: Canonical unit for SHA-256 economics elsewhere in the codebase.
CANONICAL_SHA256_UNIT = "TH"


class MiningUnitError(ValueError):
    """A unit or market term that cannot be trusted to price hashrate."""


def unit_hashes(speed_text: str) -> float:
    """Hashes per second for one unit of ``speed_text``. No guessing."""
    key = speed_text.strip().upper().removesuffix("/S")
    if key not in SPEED_UNIT_HASHES:
        raise MiningUnitError(
            f"unknown speed unit {speed_text!r}; refusing to guess "
            f"(known: {sorted(SPEED_UNIT_HASHES)})"
        )
    return SPEED_UNIT_HASHES[key]


def convert_speed(amount: float, *, from_unit: str, to_unit: str) -> float:
    """Convert a hashrate between the venue's unit and ours."""
    return amount * unit_hashes(from_unit) / unit_hashes(to_unit)


@dataclass(frozen=True)
class MarketSpec:
    """One algorithm on one market, exactly as ``buy/info`` describes it."""

    algorithm: str
    market: str
    speed_text: str
    min_order_amount_btc: float
    min_speed_limit: float
    max_speed_limit: float
    min_price_btc: float
    max_price_btc: float
    enabled: bool
    down_step: float
    raw_sha256: str
    captured_at_utc: str
    evidence_class: str
    source_url: str

    def __post_init__(self) -> None:
        unit_hashes(self.speed_text)  # validates, raises on an unknown unit
        for name in (
            "min_order_amount_btc",
            "min_speed_limit",
            "max_speed_limit",
            "min_price_btc",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise MiningUnitError(f"{name} must be finite and > 0")
        if self.max_speed_limit < self.min_speed_limit:
            raise MiningUnitError("max_speed_limit cannot be below min_speed_limit")

    @property
    def speed_unit_hashes(self) -> float:
        return unit_hashes(self.speed_text)

    def price_usd_per_canonical_unit_day(
        self, price_btc_per_speed_unit_day: float, *, btc_usd: float
    ) -> float:
        """Convert the venue's quote into USD per TH/s per day.

        The venue quotes BTC per ``speed_text`` unit per day. Skipping the
        unit conversion — the single most common mistake in rented-hashrate
        arithmetic — misprices SHA-256 by a factor of 1,000.
        """
        if btc_usd <= 0:
            raise MiningUnitError("btc_usd must be > 0 to convert a BTC-denominated quote")
        per_speed_unit_usd = price_btc_per_speed_unit_day * btc_usd
        units_per_canonical = unit_hashes(CANONICAL_SHA256_UNIT) / self.speed_unit_hashes
        return per_speed_unit_usd * units_per_canonical

    def validate_order(
        self, *, amount_btc: float, speed_limit: float, price_btc: float
    ) -> list[str]:
        """Every venue rule this hypothetical order would break."""
        problems: list[str] = []
        if amount_btc < self.min_order_amount_btc:
            problems.append(
                f"amount {amount_btc:.8f} BTC is below the marketplace minimum "
                f"{self.min_order_amount_btc:.8f} BTC"
            )
        if speed_limit < self.min_speed_limit:
            problems.append(
                f"speed limit {speed_limit} {self.speed_text}/s is below the "
                f"minimum {self.min_speed_limit}"
            )
        if speed_limit > self.max_speed_limit:
            problems.append(
                f"speed limit {speed_limit} {self.speed_text}/s exceeds the "
                f"maximum {self.max_speed_limit}"
            )
        if price_btc < self.min_price_btc:
            problems.append(
                f"price {price_btc:.10f} is below the marketplace minimum {self.min_price_btc:.10f}"
            )
        if not self.enabled:
            problems.append(f"{self.algorithm} is not enabled on market {self.market}")
        return problems

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["speed_unit_hashes"] = self.speed_unit_hashes
        payload["limit_semantics"] = (
            "min/max speed LIMIT is the maximum speed the buyer requests, not "
            "the hashrate available on the market"
        )
        return payload


def parse_buy_info(
    raw: bytes,
    *,
    algorithm: str,
    market: str,
    captured_at_utc: str,
    evidence_class: str,
    source_url: str,
) -> MarketSpec:
    """Parse ``public/buy/info`` for one algorithm on one market.

    Every field is required. A marketplace term that is absent from the
    response cannot be defaulted: guessing a minimum order size or a price
    floor produces a number that looks like evidence and is not.
    """
    from quant_trade.evidence.canonical_json import sha256_of_bytes

    payload = json.loads(raw.decode("utf-8"))
    algorithms = payload.get("miningAlgorithms") or []
    entry = next(
        (a for a in algorithms if str(a.get("algorithm", "")).upper() == algorithm.upper()),
        None,
    )
    if entry is None:
        raise MiningUnitError(
            f"buy/info carries no entry for {algorithm!r}; available: "
            f"{sorted(str(a.get('algorithm', '')) for a in algorithms)}"
        )
    markets = {str(m.get("market", "")).upper() for m in (payload.get("markets") or [])}
    if markets and market.upper() not in markets:
        raise MiningUnitError(
            f"market {market!r} is not in buy/info's market list {sorted(markets)}"
        )

    required = (
        "speedText",
        "minimalOrderAmount",
        "minSpeedLimit",
        "maxSpeedLimit",
        "minimalPrice",
        "maximalPrice",
        "downStep",
    )
    missing = [name for name in required if entry.get(name) is None]
    if missing:
        raise MiningUnitError(
            f"buy/info entry for {algorithm} is missing {missing}; these are "
            "marketplace terms and cannot be defaulted"
        )
    return MarketSpec(
        algorithm=algorithm.upper(),
        market=market.upper(),
        speed_text=str(entry["speedText"]),
        min_order_amount_btc=float(entry["minimalOrderAmount"]),
        min_speed_limit=float(entry["minSpeedLimit"]),
        max_speed_limit=float(entry["maxSpeedLimit"]),
        min_price_btc=float(entry["minimalPrice"]),
        max_price_btc=float(entry["maximalPrice"]),
        enabled=bool(entry.get("enabled", False)),
        down_step=float(entry["downStep"]),
        raw_sha256=sha256_of_bytes(raw),
        captured_at_utc=captured_at_utc,
        evidence_class=evidence_class,
        source_url=source_url,
    )


@dataclass
class DeliveryEstimate:
    """How much of a bid is likely to be filled, and why."""

    bid_price_btc: float
    market_clearing_price_btc: float
    bids_above: int
    total_bids: int
    price_percentile: float
    expected_fill_ratio: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_delivery(bid_price_btc: float, orderbook_prices_btc: list[float]) -> DeliveryEstimate:
    """Estimate the fraction of requested speed a bid is likely to receive.

    Hashpower goes to the highest bidders. A bid at the top of the book fills;
    one below the market clears partially or not at all. This is a coarse
    model — the honest alternative to assuming a bid always fills, not a
    precise forecast — and it is monotone in price, which is the property that
    matters for ranking opportunities.
    """
    if not orderbook_prices_btc:
        return DeliveryEstimate(
            bid_price_btc=bid_price_btc,
            market_clearing_price_btc=0.0,
            bids_above=0,
            total_bids=0,
            price_percentile=0.0,
            expected_fill_ratio=0.0,
            reason="no order book observed; delivery cannot be estimated",
        )
    ordered = sorted(orderbook_prices_btc, reverse=True)
    above = sum(1 for price in ordered if price > bid_price_btc)
    percentile = 1.0 - above / len(ordered)
    median = ordered[len(ordered) // 2]
    # A bid at or above the median fills nearly fully; one far below barely at
    # all. Linear in percentile keeps the model honest about its own crudeness.
    ratio = max(0.0, min(1.0, percentile))
    return DeliveryEstimate(
        bid_price_btc=bid_price_btc,
        market_clearing_price_btc=median,
        bids_above=above,
        total_bids=len(ordered),
        price_percentile=percentile,
        expected_fill_ratio=ratio,
        reason=(
            f"{above} of {len(ordered)} standing bids price above this one; "
            "hashpower is allocated to the highest bids first"
        ),
    )


__all__ = [
    "CANONICAL_SHA256_UNIT",
    "SPEED_UNIT_HASHES",
    "DeliveryEstimate",
    "MarketSpec",
    "MiningUnitError",
    "convert_speed",
    "estimate_delivery",
    "parse_buy_info",
    "unit_hashes",
]
