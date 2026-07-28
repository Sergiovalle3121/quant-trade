"""Read-only scanner for a hashrate marketplace (NiceHash-shaped).

Strictly a *scanner*. It has no buy, no bid, no deposit and no withdraw verb —
a test asserts the absence of those method names on the module — and it reads
only public, unauthenticated endpoints. Renting hashrate spends real money, so
the boundary is drawn at "observe and price", never "transact".

The status ladder is the V7 one, kept deliberately strict:

``BLOCKED_NETWORK``
    the marketplace could not be reached; the verbatim error is the evidence.
``DISCOVERY_ONLY``
    prices were captured, but no verifiable record of *delivered* hashrate
    and *received* payouts exists. Advertised speed is a claim; without a
    delivery history there is no basis for expecting to receive what you buy,
    so this is the ceiling no matter how good the arithmetic looks.
``MINING_PAPER_CANDIDATE``
    delivery history exists, evidence verifies, and the cash-flow engine
    clears the gates. Still nothing is bought.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes

#: Official, documented, unauthenticated NiceHash public endpoints.
NICEHASH_HOST = "https://api2.nicehash.com"
NICEHASH_ALGO_INFO_URL = f"{NICEHASH_HOST}/main/api/v2/public/simplemultialgo/info"
NICEHASH_ORDERBOOK_URL = f"{NICEHASH_HOST}/main/api/v2/hashpower/orderBook"
NICEHASH_BUY_INFO_URL = f"{NICEHASH_HOST}/main/api/v2/public/buy/info"

PROVIDERS = ("nicehash",)

STATUS_BLOCKED_NETWORK = "BLOCKED_NETWORK"
STATUS_DISCOVERY_ONLY = "DISCOVERY_ONLY"
STATUS_PAPER_CANDIDATE = "MINING_PAPER_CANDIDATE"
STATUS_REJECTED = "REJECTED_ECONOMICS"

#: Gates a marketplace opportunity must clear to become a paper candidate.
MINING_GATES = {
    "require_delivery_history": True,
    "require_positive_centre_profit": True,
    "require_positive_p05_profit": True,
    "max_loss_probability": 0.20,
    "require_beats_holding_coin": True,
    "require_beats_holding_cash": True,
    "require_payout_above_minimum": True,
}


@dataclass
class MarketplaceQuote:
    """One priced rung of the hashpower order book."""

    provider: str
    algorithm_id: str
    coin: str
    network: str
    native_unit: str
    price_usd_per_unit_day: float
    available_units: float
    min_order_units: float
    min_duration_hours: float
    buyer_fee_rate: float
    captured_at_utc: str
    raw_sha256: str
    evidence_class: str
    source_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketplaceScan:
    provider: str
    status: str
    scanned_at_utc: str
    quotes: list[MarketplaceQuote] = field(default_factory=list)
    delivery_history_available: bool = False
    blocked_hosts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "MINING_MARKETPLACE_SCAN",
            "schema_version": 1,
            "provider": self.provider,
            "status": self.status,
            "scanned_at_utc": self.scanned_at_utc,
            "quotes": [q.to_dict() for q in self.quotes],
            "quote_count": len(self.quotes),
            "delivery_history_available": self.delivery_history_available,
            "blocked_hosts": list(self.blocked_hosts),
            "errors": list(self.errors),
            "notes": list(self.notes),
            "purchase_authorized": False,
            "deposit_authorized": False,
            "withdrawal_authorized": False,
            "miners_started": 0,
        }


def parse_nicehash_algo_info(
    raw: bytes, *, captured_at_utc: str, evidence_class: str, btc_usd: float
) -> list[MarketplaceQuote]:
    """Parse ``/public/simplemultialgo/info`` into priced quotes.

    NiceHash quotes ``paying`` in BTC per unit per day, where the unit is the
    algorithm's own (TH/s for SHA-256). Converting to USD needs an explicit
    BTC/USD price, which is why the caller must supply one — silently
    inventing an exchange rate is how unit errors enter mining economics.
    """
    from quant_trade.cloud_rental.market import ALGORITHM_UNITS

    if btc_usd <= 0:
        raise ValueError("btc_usd must be > 0 to convert BTC-denominated prices")
    payload = json.loads(raw.decode("utf-8"))
    raw_sha = sha256_of_bytes(raw)
    by_name = {
        str(entry.get("name", "")).lower(): entry
        for entry in (payload.get("miningAlgorithms") or [])
    }
    quotes: list[MarketplaceQuote] = []
    for algorithm_id, definition in ALGORITHM_UNITS.items():
        entry = by_name.get(algorithm_id)
        if entry is None:
            continue
        paying_btc = float(entry.get("paying", 0.0) or 0.0)
        if paying_btc <= 0:
            continue
        quotes.append(
            MarketplaceQuote(
                provider="nicehash",
                algorithm_id=algorithm_id,
                coin=definition.coin,
                network=definition.network,
                native_unit=definition.native_unit,
                price_usd_per_unit_day=paying_btc * btc_usd,
                available_units=0.0,
                min_order_units=0.0,
                min_duration_hours=0.0,
                buyer_fee_rate=0.0,
                captured_at_utc=captured_at_utc,
                raw_sha256=raw_sha,
                evidence_class=evidence_class,
                source_url=NICEHASH_ALGO_INFO_URL,
            )
        )
    quotes.sort(key=lambda q: q.algorithm_id)
    return quotes


def parse_nicehash_orderbook(
    raw: bytes,
    *,
    algorithm_id: str,
    captured_at_utc: str,
    evidence_class: str,
    btc_usd: float,
    buyer_fee_rate: float,
    min_order_units: float,
    min_duration_hours: float,
) -> list[MarketplaceQuote]:
    """Parse ``/hashpower/orderBook`` rungs for one algorithm."""
    from quant_trade.cloud_rental.market import ALGORITHM_UNITS

    if btc_usd <= 0:
        raise ValueError("btc_usd must be > 0 to convert BTC-denominated prices")
    definition = ALGORITHM_UNITS.get(algorithm_id)
    if definition is None:
        raise ValueError(f"unknown algorithm {algorithm_id!r}; refusing to guess its unit")
    payload = json.loads(raw.decode("utf-8"))
    raw_sha = sha256_of_bytes(raw)
    quotes: list[MarketplaceQuote] = []
    for market in (payload.get("stats") or {}).values():
        for order in market.get("orders") or []:
            price = float(order.get("price", 0.0) or 0.0)
            limit = float(order.get("limit", 0.0) or 0.0)
            if price <= 0 or limit <= 0:
                continue
            quotes.append(
                MarketplaceQuote(
                    provider="nicehash",
                    algorithm_id=algorithm_id,
                    coin=definition.coin,
                    network=definition.network,
                    native_unit=definition.native_unit,
                    price_usd_per_unit_day=price * btc_usd,
                    available_units=limit,
                    min_order_units=min_order_units,
                    min_duration_hours=min_duration_hours,
                    buyer_fee_rate=buyer_fee_rate,
                    captured_at_utc=captured_at_utc,
                    raw_sha256=raw_sha,
                    evidence_class=evidence_class,
                    source_url=NICEHASH_ORDERBOOK_URL,
                )
            )
    quotes.sort(key=lambda q: (q.price_usd_per_unit_day, q.available_units))
    return quotes


def scan_marketplace(
    *,
    scanned_at_utc: str,
    btc_usd: float | None = None,
    fetcher: Any = None,
    evidence_dir: str | Path | None = None,
    provider: str = "nicehash",
) -> MarketplaceScan:
    """Capture public marketplace prices, or record exactly why it failed."""
    if provider not in PROVIDERS:
        raise ValueError(f"unsupported provider {provider!r}; supported: {PROVIDERS}")
    from quant_trade.v8.backfill import http_get

    scan = MarketplaceScan(
        provider=provider, status=STATUS_DISCOVERY_ONLY, scanned_at_utc=scanned_at_utc
    )
    active = fetcher or (lambda url: http_get(url, timeout_seconds=20.0))
    try:
        status, raw, _headers = active(NICEHASH_ALGO_INFO_URL)
        if status != 200:
            raise RuntimeError(f"HTTP {status}")
    except Exception as exc:  # noqa: BLE001 — the verbatim error IS the evidence
        scan.status = STATUS_BLOCKED_NETWORK
        scan.errors.append(f"{NICEHASH_ALGO_INFO_URL}: {type(exc).__name__}: {exc}")
        scan.blocked_hosts.append("api2.nicehash.com")
        scan.notes.append(
            "no marketplace prices were captured; hashrate economics cannot be "
            "evaluated on an unobserved market"
        )
        return scan

    if btc_usd is None:
        scan.status = STATUS_DISCOVERY_ONLY
        scan.errors.append(
            "marketplace prices are quoted in BTC; a BTC/USD rate from verified "
            "evidence is required before they can be converted"
        )
        return scan

    scan.quotes = parse_nicehash_algo_info(
        raw,
        captured_at_utc=scanned_at_utc,
        evidence_class="REAL" if fetcher is None else "RECORDED_RESPONSE",
        btc_usd=btc_usd,
    )
    if evidence_dir is not None:
        out = Path(evidence_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{sha256_of_bytes(raw)}.json").write_bytes(raw)
        (out / "scan.json").write_text(canonical_dumps(scan.to_dict()), encoding="utf-8")
    scan.notes.append(
        "prices captured; without a verifiable delivery and payout history the "
        "status cannot exceed DISCOVERY_ONLY"
    )
    return scan


@dataclass
class MiningOpportunity:
    """One priced, gated marketplace opportunity."""

    opportunity_id: str
    provider: str
    algorithm_id: str
    status: str
    economics: dict[str, Any] = field(default_factory=dict)
    gate_results: list[dict[str, Any]] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["purchase_authorized"] = False
        payload["deposit_authorized"] = False
        return payload


def evaluate_opportunity(
    quote: MarketplaceQuote,
    *,
    economics: Any,
    delivery_history_available: bool,
) -> MiningOpportunity:
    """Gate a priced opportunity. Without delivery history it caps out."""
    payload = economics.to_dict()
    checks = [
        {
            "gate": "delivery_history_available",
            "required": True,
            "observed": delivery_history_available,
            "passed": bool(delivery_history_available),
            "detail": (
                "advertised hashrate is a claim; without a record of what was "
                "delivered and paid out there is no basis for expecting either"
            ),
        },
        {
            "gate": "centre_profit_positive",
            "required": "> 0",
            "observed": payload["profit_usd"],
            "passed": float(payload["profit_usd"]) > 0,
        },
        {
            "gate": "p05_profit_positive",
            "required": "> 0",
            "observed": payload["scenarios"]["p05_profit_usd"],
            "passed": float(payload["scenarios"]["p05_profit_usd"]) > 0,
        },
        {
            "gate": "loss_probability",
            "required": f"<= {MINING_GATES['max_loss_probability']}",
            "observed": payload["loss_probability"],
            "passed": float(payload["loss_probability"])
            <= float(MINING_GATES["max_loss_probability"]),
        },
        {
            "gate": "payout_above_pool_minimum",
            "required": False,
            "observed": payload["stranded_below_minimum"],
            "passed": not payload["stranded_below_minimum"],
        },
        {
            "gate": "beats_holding_coin",
            "required": f"> {payload['versus_holding_coin_usd']}",
            "observed": payload["profit_usd"],
            "passed": float(payload["profit_usd"]) > float(payload["versus_holding_coin_usd"]),
        },
        {
            "gate": "beats_holding_cash",
            "required": f"> {payload['versus_holding_cash_usd']}",
            "observed": payload["profit_usd"],
            "passed": float(payload["profit_usd"]) > float(payload["versus_holding_cash_usd"]),
        },
    ]
    failed = [c for c in checks if not c["passed"]]
    if not delivery_history_available:
        status = STATUS_DISCOVERY_ONLY
    elif failed:
        status = STATUS_REJECTED
    else:
        status = STATUS_PAPER_CANDIDATE
    return MiningOpportunity(
        opportunity_id=f"{quote.provider}:{quote.algorithm_id}",
        provider=quote.provider,
        algorithm_id=quote.algorithm_id,
        status=status,
        economics=payload,
        gate_results=checks,
        blocking_reasons=[
            f"{c['gate']}: required {c['required']}, observed {c['observed']}" for c in failed
        ],
    )


def hashes_per_unit(algorithm_id: str) -> float:
    from quant_trade.cloud_rental.market import ALGORITHM_UNITS

    definition = ALGORITHM_UNITS.get(algorithm_id)
    if definition is None:
        raise ValueError(f"unknown algorithm {algorithm_id!r}")
    return float(Decimal(definition.hashes_per_unit))


__all__ = [
    "MINING_GATES",
    "NICEHASH_ALGO_INFO_URL",
    "NICEHASH_BUY_INFO_URL",
    "NICEHASH_HOST",
    "NICEHASH_ORDERBOOK_URL",
    "PROVIDERS",
    "STATUS_BLOCKED_NETWORK",
    "STATUS_DISCOVERY_ONLY",
    "STATUS_PAPER_CANDIDATE",
    "STATUS_REJECTED",
    "MarketplaceQuote",
    "MarketplaceScan",
    "MiningOpportunity",
    "evaluate_opportunity",
    "hashes_per_unit",
    "parse_nicehash_algo_info",
    "parse_nicehash_orderbook",
    "scan_marketplace",
]
