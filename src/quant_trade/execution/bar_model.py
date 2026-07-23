"""Pure, deterministic bar-based market-order execution model."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionStatus(StrEnum):
    SUBMITTED = "submitted"
    DEFERRED = "deferred"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_EXECUTION_STATUSES = {
    ExecutionStatus.FILLED,
    ExecutionStatus.REJECTED,
    ExecutionStatus.CANCELLED,
    ExecutionStatus.EXPIRED,
}


@dataclass(frozen=True)
class BarExecutionPolicy:
    """Execution realism controls applied after the mandatory next-bar delay."""

    additional_latency_bars: int = 0
    max_volume_participation_rate: float | None = None
    lot_size: float | None = None
    max_order_age_bars: int = 0
    market_impact_bps_at_full_participation: float = 0.0

    def __post_init__(self) -> None:
        if self.additional_latency_bars < 0:
            raise ValueError("additional_latency_bars must be >= 0")
        if self.max_order_age_bars < 0:
            raise ValueError("max_order_age_bars must be >= 0")
        if self.max_volume_participation_rate is not None and (
            not math.isfinite(self.max_volume_participation_rate)
            or self.max_volume_participation_rate <= 0
            or self.max_volume_participation_rate > 1
        ):
            raise ValueError("max_volume_participation_rate must be in (0, 1]")
        if self.lot_size is not None and (
            not math.isfinite(self.lot_size) or self.lot_size <= 0
        ):
            raise ValueError("lot_size must be finite and > 0")
        if (
            not math.isfinite(self.market_impact_bps_at_full_participation)
            or self.market_impact_bps_at_full_participation < 0
        ):
            raise ValueError(
                "market_impact_bps_at_full_participation must be finite and >= 0"
            )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any] | None) -> BarExecutionPolicy:
        raw = values or {}
        known = {
            "additional_latency_bars",
            "max_volume_participation_rate",
            "lot_size",
            "max_order_age_bars",
            "market_impact_bps_at_full_participation",
        }
        return cls(**{key: raw[key] for key in known if key in raw})


@dataclass
class BarOrderState:
    """Mutable state for one signed-quantity market order."""

    order_id: str
    symbol: str
    signed_quantity: float
    submitted_bar_index: int
    eligible_bar_index: int
    remaining_quantity: float | None = None
    cumulative_filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    fill_count: int = 0
    status: ExecutionStatus = ExecutionStatus.SUBMITTED
    reason: str = ""
    last_attempt_bar_index: int | None = None

    def __post_init__(self) -> None:
        if not self.order_id.strip() or not self.symbol.strip():
            raise ValueError("order_id and symbol must be non-empty")
        if not math.isfinite(self.signed_quantity) or abs(self.signed_quantity) <= 0:
            raise ValueError("signed_quantity must be finite and non-zero")
        if self.submitted_bar_index < 0:
            raise ValueError("submitted_bar_index must be >= 0")
        if self.eligible_bar_index < self.submitted_bar_index:
            raise ValueError("eligible_bar_index cannot precede submission")
        if self.remaining_quantity is None:
            self.remaining_quantity = self.signed_quantity
        elif (
            not math.isfinite(self.remaining_quantity)
            or self.remaining_quantity * self.signed_quantity < 0
            or abs(self.remaining_quantity) > abs(self.signed_quantity) + 1e-12
        ):
            raise ValueError("remaining_quantity is inconsistent with signed_quantity")

    @property
    def side(self) -> str:
        return "buy" if self.signed_quantity > 0 else "sell"

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_EXECUTION_STATUSES


@dataclass(frozen=True)
class BarFillDecision:
    fill_id: str
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    participation_rate: float
    price_impact_bps: float
    bar_index: int


def _round_down_to_lot(quantity: float, lot_size: float | None) -> float:
    if lot_size is None:
        return quantity
    lots = math.floor((quantity + 1e-12) / lot_size)
    return lots * lot_size


def _expire_or_defer(
    order: BarOrderState,
    bar_index: int,
    policy: BarExecutionPolicy,
    reason: str,
) -> None:
    age = bar_index - order.eligible_bar_index
    if age >= policy.max_order_age_bars:
        order.status = ExecutionStatus.EXPIRED
        order.reason = reason
    else:
        order.status = ExecutionStatus.DEFERRED
        order.reason = reason


def execute_market_order_on_bar(
    order: BarOrderState,
    *,
    bar_index: int,
    open_price: float | None,
    volume: float | None,
    policy: BarExecutionPolicy,
) -> BarFillDecision | None:
    """Mutate order state and return at most one fill for the supplied bar."""
    if order.is_terminal:
        return None
    if bar_index < order.eligible_bar_index:
        order.status = ExecutionStatus.DEFERRED
        order.reason = "additional latency has not elapsed"
        return None
    order.last_attempt_bar_index = bar_index
    if open_price is None or not math.isfinite(open_price) or open_price <= 0:
        _expire_or_defer(order, bar_index, policy, "missing or invalid execution open")
        return None

    remaining = abs(float(order.remaining_quantity or 0.0))
    if remaining <= 1e-12:
        order.status = ExecutionStatus.FILLED
        order.reason = ""
        return None

    if policy.max_volume_participation_rate is None:
        maximum_fill = remaining
        participation = 0.0
    else:
        if volume is None or not math.isfinite(volume) or volume < 0:
            _expire_or_defer(order, bar_index, policy, "missing or invalid bar volume")
            return None
        maximum_fill = min(
            remaining,
            volume * policy.max_volume_participation_rate,
        )
        participation = maximum_fill / volume if volume > 0 else 0.0
    fill_quantity = _round_down_to_lot(maximum_fill, policy.lot_size)
    if fill_quantity <= 1e-12:
        _expire_or_defer(order, bar_index, policy, "insufficient executable bar liquidity")
        return None

    direction = 1.0 if order.signed_quantity > 0 else -1.0
    impact_bps = policy.market_impact_bps_at_full_participation * participation
    fill_price = open_price * (1 + direction * impact_bps / 10_000)
    prior_filled = order.cumulative_filled_quantity
    new_filled = prior_filled + fill_quantity
    order.average_fill_price = (
        order.average_fill_price * prior_filled + fill_price * fill_quantity
    ) / new_filled
    order.cumulative_filled_quantity = new_filled
    order.fill_count += 1
    signed_fill = direction * fill_quantity
    order.remaining_quantity = float(order.remaining_quantity or 0.0) - signed_fill

    if abs(order.remaining_quantity) <= 1e-12:
        order.remaining_quantity = 0.0
        order.status = ExecutionStatus.FILLED
        order.reason = ""
    elif bar_index - order.eligible_bar_index >= policy.max_order_age_bars:
        order.status = ExecutionStatus.EXPIRED
        order.reason = "partially filled; unfilled remainder expired"
    else:
        order.status = ExecutionStatus.PARTIALLY_FILLED
        order.reason = "unfilled remainder carried forward"

    return BarFillDecision(
        fill_id=f"{order.order_id}:{order.fill_count}",
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        quantity=fill_quantity,
        price=fill_price,
        participation_rate=participation,
        price_impact_bps=impact_bps,
        bar_index=bar_index,
    )


def cancel_order(order: BarOrderState, reason: str) -> None:
    if not order.is_terminal:
        order.status = ExecutionStatus.CANCELLED
        order.reason = reason

