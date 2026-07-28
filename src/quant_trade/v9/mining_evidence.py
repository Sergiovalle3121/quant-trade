"""What the mining route is allowed to claim, given what was actually observed.

The rented-hashrate story has a specific failure mode: marketplace prices are
easy to fetch, so the analysis looks well-evidenced while the half that decides
profitability — *did the hashrate arrive and did the pool pay* — is assumed.
Prices are a quote. Payouts are the product.

So the ceiling is set by the weakest leg, not the strongest:

``BLOCKED_EVIDENCE``
    the marketplace could not be read at all.
``SHADOW_MARKET_ONLY``
    prices exist; there is no pool-side record of delivered hashrate or
    received payouts. This is the ceiling no matter how attractive the
    arithmetic, because nothing here has been observed to be deliverable.
``SHADOW_COLLECTING``
    a pool adapter is attached and the shadow collector is running, but the
    observation window is not long enough to mean anything yet.
``SHADOW_CANDIDATE``
    enough real elapsed days and enough snapshots, quotes reconcile with
    economics, and the pool evidence is real rather than declared.

The pool adapter here is read-only in the strong sense: it parses responses
and has no client, no credentials, no endpoint and no verb that could move
money. A test asserts the absence of those names.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.v9.economic_status import EVIDENCE_CLASSES, MINING_STATES

STATUS_BLOCKED = "BLOCKED_EVIDENCE"
STATUS_MARKET_ONLY = "SHADOW_MARKET_ONLY"
STATUS_COLLECTING = "SHADOW_COLLECTING"
STATUS_CANDIDATE = "SHADOW_CANDIDATE"

#: Evidence classes that can support a mining promotion. A hand-typed number
#: and a recorded fixture are both useful; neither is an observation.
REAL_EVIDENCE_CLASSES = ("REAL_PUBLIC_RETAIL", "REAL_ACCOUNT_SPECIFIC")

#: How long a captured quote or payout record stays usable. Hashrate prices
#: move hourly; a day-old quote priced against today's difficulty is a
#: comparison between two different markets.
DEFAULT_MAX_EVIDENCE_AGE_SECONDS = 6 * 3600.0

#: Tolerance when checking that a quote and the cash-flow engine agree.
QUOTE_ECONOMICS_TOLERANCE = 1e-6


class MiningEvidenceError(ValueError):
    """Evidence that cannot support the claim being made from it."""


@dataclass(frozen=True)
class PoolPayoutRecord:
    """One payout the pool says it made, with the bytes it came from."""

    pool_name: str
    worker: str
    period_start_ms: int
    period_end_ms: int
    hashrate_accepted_hashes_per_second: float
    payout_btc: float
    raw_sha256: str
    captured_at_ms: int
    evidence_class: str
    source_url: str

    def __post_init__(self) -> None:
        if self.evidence_class not in EVIDENCE_CLASSES:
            raise MiningEvidenceError(
                f"{self.evidence_class!r} is not a known evidence class {EVIDENCE_CLASSES}"
            )
        if self.period_end_ms <= self.period_start_ms:
            raise MiningEvidenceError("payout period must have positive length")
        for name in ("hashrate_accepted_hashes_per_second", "payout_btc"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise MiningEvidenceError(f"{name} must be finite and >= 0")
        if self.evidence_class in REAL_EVIDENCE_CLASSES and not self.raw_sha256:
            raise MiningEvidenceError(
                f"a {self.evidence_class} payout record must carry the sha256 of the "
                "response it was parsed from; a real class without bytes is a claim"
            )

    @property
    def duration_days(self) -> float:
        return (self.period_end_ms - self.period_start_ms) / 86_400_000.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_pool_payouts(
    raw: bytes,
    *,
    pool_name: str,
    evidence_class: str,
    source_url: str,
    captured_at_ms: int,
) -> list[PoolPayoutRecord]:
    """Parse a pool's public payout history. Read-only, and total.

    A record missing its accepted-hashrate or its amount is dropped rather
    than defaulted: the whole purpose of pool evidence is to show that speed
    turned into coins, and a record that omits either half shows nothing.
    """
    from quant_trade.evidence.canonical_json import sha256_of_bytes

    digest = sha256_of_bytes(raw)
    payload = json.loads(raw.decode("utf-8"))
    rows = payload.get("payouts") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise MiningEvidenceError("pool response carries no payout list")

    records: list[PoolPayoutRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        required = ("periodStartMs", "periodEndMs", "acceptedHashesPerSecond", "payoutBtc")
        if any(row.get(name) is None for name in required):
            continue
        records.append(
            PoolPayoutRecord(
                pool_name=pool_name,
                worker=str(row.get("worker", "")),
                period_start_ms=int(row["periodStartMs"]),
                period_end_ms=int(row["periodEndMs"]),
                hashrate_accepted_hashes_per_second=float(row["acceptedHashesPerSecond"]),
                payout_btc=float(row["payoutBtc"]),
                raw_sha256=digest,
                captured_at_ms=captured_at_ms,
                evidence_class=evidence_class,
                source_url=source_url,
            )
        )
    return records


@dataclass
class PoolEvidence:
    """The pool side of the story: was speed delivered, was it paid for?"""

    records: list[PoolPayoutRecord] = field(default_factory=list)
    declared_delivery_ok: bool | None = None

    @property
    def real_records(self) -> list[PoolPayoutRecord]:
        return [r for r in self.records if r.evidence_class in REAL_EVIDENCE_CLASSES]

    @property
    def observed_days(self) -> float:
        return sum(r.duration_days for r in self.real_records)

    @property
    def total_payout_btc(self) -> float:
        return sum(r.payout_btc for r in self.real_records)

    @property
    def paid_records(self) -> int:
        return sum(1 for r in self.real_records if r.payout_btc > 0)

    def realized_btc_per_hash_second_day(self) -> float | None:
        """What the pool actually paid per unit of accepted hashrate.

        This is the number the whole route turns on, and it can only come from
        payout records. An engine estimate is what you compare *against* it.
        """
        weight = sum(
            r.hashrate_accepted_hashes_per_second * r.duration_days for r in self.real_records
        )
        if weight <= 0:
            return None
        return self.total_payout_btc / weight

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [r.to_dict() for r in self.records],
            "real_records": len(self.real_records),
            "observed_days": self.observed_days,
            "paid_records": self.paid_records,
            "total_payout_btc": self.total_payout_btc,
            "realized_btc_per_hash_second_day": self.realized_btc_per_hash_second_day(),
            "declared_delivery_ok": self.declared_delivery_ok,
            "declaration_note": (
                "A declared delivery flag is recorded and never counted. Only "
                "parsed payout records with their source bytes are evidence."
            ),
        }


@dataclass
class MiningEvidenceGate:
    """The ceiling the mining route may claim, and the reason for it."""

    status: str
    reasons: list[str] = field(default_factory=list)
    market_quotes: int = 0
    pool_observed_days: float = 0.0
    pool_paid_records: int = 0
    shadow_days: float = 0.0
    shadow_snapshots: int = 0
    quote_economics_agree: bool | None = None
    stale_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact"] = "MINING_EVIDENCE_GATE"
        payload["schema_version"] = 1
        payload["permitted_states"] = list(MINING_STATES)
        payload["purchase_authorized"] = False
        payload["deposit_authorized"] = False
        payload["withdrawal_authorized"] = False
        payload["ceiling_rule"] = (
            "without parsed pool payout records the route cannot exceed "
            "SHADOW_MARKET_ONLY, whatever the marketplace arithmetic says"
        )
        return payload


def evaluate_mining_evidence(
    *,
    market_quotes: int,
    market_blocked: bool,
    pool: PoolEvidence | None,
    shadow_days: float = 0.0,
    shadow_snapshots: int = 0,
    min_shadow_days: float = 14.0,
    min_shadow_snapshots: int = 2_000,
    quote_price_btc: float | None = None,
    economics_price_btc: float | None = None,
    evidence_ages_seconds: dict[str, float] | None = None,
    max_evidence_age_seconds: float = DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
) -> MiningEvidenceGate:
    """Cap the mining claim at whatever the weakest leg supports."""
    gate = MiningEvidenceGate(status=STATUS_BLOCKED, market_quotes=market_quotes)

    for name, age in (evidence_ages_seconds or {}).items():
        if age > max_evidence_age_seconds:
            gate.stale_evidence.append(
                f"{name} is {age / 3600.0:.1f}h old, past the "
                f"{max_evidence_age_seconds / 3600.0:.1f}h freshness window"
            )

    if market_blocked or market_quotes <= 0:
        gate.reasons.append(
            "the marketplace could not be read; no quote exists to price anything from"
        )
        return gate

    if quote_price_btc is not None and economics_price_btc is not None:
        agree = abs(quote_price_btc - economics_price_btc) <= QUOTE_ECONOMICS_TOLERANCE * max(
            1.0, abs(quote_price_btc)
        )
        gate.quote_economics_agree = agree
        if not agree:
            gate.reasons.append(
                f"the captured quote ({quote_price_btc:.10f} BTC) and the price the "
                f"cash-flow engine priced ({economics_price_btc:.10f} BTC) disagree; "
                "one of them is describing a different order"
            )
            gate.status = STATUS_MARKET_ONLY
            return gate

    gate.status = STATUS_MARKET_ONLY
    if pool is None or not pool.real_records:
        gate.reasons.append(
            "no parsed pool payout record: delivered hashrate and received coins "
            "are both unobserved, so the route stays market-only"
        )
        return gate

    gate.pool_observed_days = pool.observed_days
    gate.pool_paid_records = pool.paid_records
    gate.shadow_days = shadow_days
    gate.shadow_snapshots = shadow_snapshots

    if pool.paid_records <= 0:
        gate.reasons.append(
            "pool records exist but none carries a payout: hashrate was accepted "
            "and nothing was received"
        )
        return gate

    gate.status = STATUS_COLLECTING
    if gate.stale_evidence:
        gate.reasons.extend(gate.stale_evidence)
        return gate
    if shadow_days < min_shadow_days:
        gate.reasons.append(
            f"{shadow_days:.2f} real days observed of the {min_shadow_days:.0f} required"
        )
        return gate
    if shadow_snapshots < min_shadow_snapshots:
        gate.reasons.append(f"{shadow_snapshots} snapshots of the {min_shadow_snapshots} required")
        return gate

    gate.status = STATUS_CANDIDATE
    gate.reasons.append(
        "market quotes, pool payouts and a full shadow window all present; still "
        "nothing has been purchased"
    )
    return gate


def mining_canary_manifest(
    gate: MiningEvidenceGate, *, notes: list[str] | None = None
) -> dict[str, Any]:
    """What a human would need to authorise, stated as refusals.

    Every authorisation flag is false and stays false. The manifest exists so
    that the boundary is written down as data rather than implied by the
    absence of a code path.
    """
    return {
        "artifact": "MINING_CANARY_MANIFEST",
        "schema_version": 1,
        "status": gate.status,
        "purchase_authorized": False,
        "deposit_authorized": False,
        "withdrawal_authorized": False,
        "wallet_signing_authorized": False,
        "cloud_hashing_authorized": False,
        "aws_alibaba_hashing": "PROHIBITED",
        "orders_placed": 0,
        "btc_moved": 0.0,
        "requires_human_authorisation": True,
        "blocking_reasons": list(gate.reasons),
        "human_steps": [
            "Review MINING_EVIDENCE_GATE and the shadow journal independently.",
            "Fund and place any order manually on the venue's own interface.",
            "This repository has no purchase, deposit or withdrawal code path to enable.",
        ],
        "notes": list(notes or []),
    }


__all__ = [
    "DEFAULT_MAX_EVIDENCE_AGE_SECONDS",
    "QUOTE_ECONOMICS_TOLERANCE",
    "REAL_EVIDENCE_CLASSES",
    "STATUS_BLOCKED",
    "STATUS_CANDIDATE",
    "STATUS_COLLECTING",
    "STATUS_MARKET_ONLY",
    "MiningEvidenceError",
    "MiningEvidenceGate",
    "PoolEvidence",
    "PoolPayoutRecord",
    "evaluate_mining_evidence",
    "mining_canary_manifest",
    "parse_pool_payouts",
]
