"""Mining pool payout economics.

Different payout schemes split subsidy vs transaction-fee revenue differently and
carry different variance and counterparty risk. Modelling them separately keeps
"which pool" from being an invisible assumption.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class PayoutScheme(StrEnum):
    PPS = "PPS"      # pays subsidy only, no tx fees; low variance
    FPPS = "FPPS"    # full pay-per-share: subsidy + tx fees; low variance
    PPS_PLUS = "PPS+"  # PPS on subsidy + PPLNS-style tx-fee share
    PPLNS = "PPLNS"  # proportional to recent shares; higher variance


def _rate(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be in [0, 1]")


@dataclass(frozen=True)
class PoolModel:
    scheme: PayoutScheme
    pool_fee_rate: float = 0.01
    shares_tx_fees: bool = True  # whether the scheme passes through tx-fee revenue
    stale_reject_rate: float = 0.005
    payout_threshold_coin: float = 0.0
    counterparty_risk_score: float = 0.3  # 0 (none) .. 1 (severe), operator input

    def __post_init__(self) -> None:
        _rate("pool_fee_rate", self.pool_fee_rate)
        _rate("stale_reject_rate", self.stale_reject_rate)
        _rate("counterparty_risk_score", self.counterparty_risk_score)
        if self.payout_threshold_coin < 0:
            raise ValueError("payout_threshold_coin must be >= 0")

    @property
    def pays_tx_fees(self) -> bool:
        return self.scheme in (PayoutScheme.FPPS, PayoutScheme.PPS_PLUS) or (
            self.scheme == PayoutScheme.PPLNS and self.shares_tx_fees
        )

    @property
    def has_variance(self) -> bool:
        return self.scheme == PayoutScheme.PPLNS


@dataclass
class PoolPayout:
    scheme: str
    gross_subsidy_revenue_usd: float
    gross_tx_fee_revenue_usd: float
    tx_fees_paid: bool
    revenue_before_fee_usd: float
    pool_fee_usd: float
    net_revenue_usd: float
    effective_after_stale_usd: float
    counterparty_risk_score: float
    variance_note: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_pool_revenue(
    *,
    subsidy_revenue_usd: float,
    tx_fee_revenue_usd: float,
    model: PoolModel,
) -> PoolPayout:
    """Net expected pool revenue given a payout scheme (no variance draw)."""
    if subsidy_revenue_usd < 0 or tx_fee_revenue_usd < 0:
        raise ValueError("revenue inputs must be >= 0")
    tx_component = tx_fee_revenue_usd if model.pays_tx_fees else 0.0
    revenue_before_fee = subsidy_revenue_usd + tx_component
    pool_fee = revenue_before_fee * model.pool_fee_rate
    net = revenue_before_fee - pool_fee
    effective = net * (1.0 - model.stale_reject_rate)
    note = (
        "PPLNS payout varies with pool luck; the expected value shown omits the "
        "variance draw. Size buffers for multi-day payout swings."
        if model.has_variance
        else None
    )
    return PoolPayout(
        scheme=str(model.scheme),
        gross_subsidy_revenue_usd=subsidy_revenue_usd,
        gross_tx_fee_revenue_usd=tx_fee_revenue_usd,
        tx_fees_paid=model.pays_tx_fees,
        revenue_before_fee_usd=revenue_before_fee,
        pool_fee_usd=pool_fee,
        net_revenue_usd=net,
        effective_after_stale_usd=effective,
        counterparty_risk_score=model.counterparty_risk_score,
        variance_note=note,
    )
