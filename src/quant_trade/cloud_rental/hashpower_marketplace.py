"""Provider-agnostic, read-only hashpower-marketplace evidence importer.

The importer validates recorded orderbook and delivery-contract responses.
It deliberately has no purchase/deposit/order method. Without byte-verified
delivery history the strongest possible verdict is ``DISCOVERY_ONLY``.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from quant_trade.cloud_rental.market import algorithm_unit
from quant_trade.evidence.canonical_json import sha256_of_file


@dataclass(frozen=True)
class MarketplaceOrderbookEvidence:
    provider_name: str
    algorithm_id: str
    coin: str
    network: str
    native_unit: str
    price_usd_per_unit_day: float
    min_amount_units: float
    max_amount_units: float
    min_duration_hours: float
    service_fee_rate: float
    visible_liquidity_units: float
    jurisdiction: str
    kyc_required: bool
    terms_url: str
    captured_at_utc: str
    raw_sha256: str
    evidence_class: str

    def __post_init__(self) -> None:
        contract = algorithm_unit(self.algorithm_id)
        if self.coin.upper() != str(contract["coin"]).upper():
            raise ValueError("marketplace coin is incompatible with algorithm")
        if self.network != contract["network"]:
            raise ValueError("marketplace network is incompatible with algorithm")
        if self.native_unit != contract["native_unit"]:
            raise ValueError("marketplace unit is incompatible with algorithm")
        positive = (
            self.price_usd_per_unit_day,
            self.min_amount_units,
            self.max_amount_units,
            self.min_duration_hours,
            self.visible_liquidity_units,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise ValueError("marketplace numeric terms must be finite and positive")
        if self.max_amount_units < self.min_amount_units:
            raise ValueError("marketplace max amount must cover its minimum")
        if not 0 <= self.service_fee_rate < 1:
            raise ValueError("service_fee_rate must be in [0, 1)")
        if not self.terms_url or not self.jurisdiction:
            raise ValueError("terms URL and jurisdiction are required")


@dataclass(frozen=True)
class MarketplaceDeliveryEvidence:
    provider_name: str
    algorithm_id: str
    purchased_units: float
    delivered_units: float
    duration_hours: float
    reject_rate: float
    stale_rate: float
    pool_name: str
    payout_scheme: str
    minimum_payout_coin: float
    cancellation_refund_usd: float
    captured_at_utc: str
    raw_sha256: str
    evidence_class: str

    def __post_init__(self) -> None:
        if self.purchased_units <= 0 or self.delivered_units < 0:
            raise ValueError("delivery capacity must be non-negative with purchase > 0")
        if self.duration_hours <= 0:
            raise ValueError("delivery duration must be positive")
        if not 0 <= self.reject_rate < 1 or not 0 <= self.stale_rate < 1:
            raise ValueError("reject and stale rates must be in [0, 1)")


def _load(path: str | Path, cls: Any) -> Any:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return cls(**payload)


def load_marketplace_orderbook(path: str | Path) -> MarketplaceOrderbookEvidence:
    return _load(path, MarketplaceOrderbookEvidence)


def load_marketplace_delivery(path: str | Path) -> MarketplaceDeliveryEvidence:
    return _load(path, MarketplaceDeliveryEvidence)


def evaluate_marketplace_evidence(
    orderbook: MarketplaceOrderbookEvidence,
    *,
    orderbook_raw_path: str | Path | None,
    delivery: MarketplaceDeliveryEvidence | None = None,
    delivery_raw_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate evidence without contacting a provider or authorizing an order."""
    problems: list[str] = []

    def verify(label: str, path_value: str | Path | None, claimed: str) -> None:
        if path_value is None or not Path(path_value).is_file():
            problems.append(f"{label} raw bytes unavailable")
        elif sha256_of_file(path_value) != claimed:
            problems.append(f"{label} raw bytes do not match raw_sha256")

    verify("orderbook", orderbook_raw_path, orderbook.raw_sha256)
    if delivery is not None:
        verify("delivery", delivery_raw_path, delivery.raw_sha256)
        if delivery.provider_name != orderbook.provider_name:
            problems.append("delivery provider does not match orderbook")
        if delivery.algorithm_id != orderbook.algorithm_id:
            problems.append("delivery algorithm does not match orderbook")

    if problems:
        status = "REJECTED_EVIDENCE"
    elif delivery is None:
        status = "DISCOVERY_ONLY"
    elif orderbook.evidence_class != "REAL" or delivery.evidence_class not in {
        "REAL",
        "RECORDED_REAL",
    }:
        status = "VALID_TEST_ONLY"
    else:
        status = "ELIGIBLE_FOR_OFFLINE_ECONOMIC_EVALUATION"
    return {
        "rental_type": "HASHPOWER_MARKETPLACE",
        "status": status,
        "problems": problems,
        "orderbook": asdict(orderbook),
        "delivery": asdict(delivery) if delivery is not None else None,
        "purchase_authorized": False,
        "deposit_authorized": False,
    }
