"""Margin, risk tiers and liquidation along the intrabar path.

A backtest that checks margin only at bar closes cannot see the event that
ends the strategy. A short perp against a bar that spiked 12% and came back
never breached anything on the close, but the position was liquidated at the
high and the rest of the equity curve is fiction.

So the check here runs against the bar's **extremes**, and a breach is
terminal: the position is force-closed at the breach price plus a liquidation
penalty, and the count is reported separately from softer execution failures.
``aborted_entries == 0`` is not a substitute for ``liquidations == 0``: one
means the strategy could not get filled, the other means it was carried out.

Risk tiers are per venue and per instrument, because maintenance requirements
step up with notional and a flat rate flatters exactly the large positions
that most need the buffer.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


class MarginError(ValueError):
    """A margin configuration that would misprice the risk."""


@dataclass(frozen=True)
class RiskTier:
    """One step of a venue's tiered maintenance schedule."""

    max_notional_usd: float
    initial_margin_rate: float
    maintenance_margin_rate: float

    def __post_init__(self) -> None:
        if self.max_notional_usd <= 0:
            raise MarginError("tier max_notional_usd must be > 0")
        for name in ("initial_margin_rate", "maintenance_margin_rate"):
            value = float(getattr(self, name))
            if not 0 < value < 1:
                raise MarginError(f"{name} must be in (0, 1)")
        if self.maintenance_margin_rate > self.initial_margin_rate:
            raise MarginError(
                "maintenance margin cannot exceed initial margin: the position "
                "would be liquidatable the moment it opened"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstrumentRisk:
    """Contract terms and the tier ladder for one venue/instrument."""

    venue: str
    instrument: str
    tiers: tuple[RiskTier, ...]
    min_order_qty: float
    qty_step: float
    tick_size: float
    min_notional_usd: float
    contract_multiplier: float = 1.0
    liquidation_penalty_rate: float = 0.005
    evidence_class: str = "ASSUMPTION"

    def __post_init__(self) -> None:
        if not self.tiers:
            raise MarginError("an instrument needs at least one risk tier")
        ordered = sorted(self.tiers, key=lambda t: t.max_notional_usd)
        if list(ordered) != list(self.tiers):
            raise MarginError("risk tiers must be ordered by max_notional_usd")
        for name in ("min_order_qty", "qty_step", "tick_size", "min_notional_usd"):
            if float(getattr(self, name)) <= 0:
                raise MarginError(f"{name} must be > 0")

    def tier_for(self, notional_usd: float) -> RiskTier:
        """The tier that governs this notional; the top tier is the ceiling."""
        for tier in self.tiers:
            if notional_usd <= tier.max_notional_usd:
                return tier
        return self.tiers[-1]

    def initial_margin(self, notional_usd: float) -> float:
        return notional_usd * self.tier_for(notional_usd).initial_margin_rate

    def maintenance_margin(self, notional_usd: float) -> float:
        return notional_usd * self.tier_for(notional_usd).maintenance_margin_rate

    def round_quantity(self, quantity: float) -> float:
        """Snap to the venue's lot grid. Rounds DOWN: never over-order."""
        if quantity <= 0:
            return 0.0
        steps = math.floor(quantity / self.qty_step + 1e-12)
        return max(0.0, steps * self.qty_step)

    def is_tradeable(self, quantity: float, price: float) -> tuple[bool, str]:
        rounded = self.round_quantity(quantity)
        if rounded < self.min_order_qty:
            return False, (
                f"quantity {rounded:.10f} is below the venue minimum {self.min_order_qty:.10f}"
            )
        if rounded * price < self.min_notional_usd:
            return False, (
                f"notional {rounded * price:.4f} is below the venue minimum "
                f"{self.min_notional_usd:.4f}"
            )
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tiers"] = [t.to_dict() for t in self.tiers]
        return payload


#: Conservative published-retail ladders. These are ASSUMPTION-class until a
#: run captures the venue's own instrument metadata, and a campaign that rests
#: on them cannot promote.
DEFAULT_RISK_TIERS = (
    RiskTier(max_notional_usd=50_000.0, initial_margin_rate=0.10, maintenance_margin_rate=0.005),
    RiskTier(max_notional_usd=250_000.0, initial_margin_rate=0.15, maintenance_margin_rate=0.010),
    RiskTier(max_notional_usd=1_000_000.0, initial_margin_rate=0.25, maintenance_margin_rate=0.025),
)


def default_instrument_risk(venue: str, instrument: str = "BTCUSDT") -> InstrumentRisk:
    return InstrumentRisk(
        venue=venue,
        instrument=instrument,
        tiers=DEFAULT_RISK_TIERS,
        min_order_qty=0.001,
        qty_step=0.001,
        tick_size=0.10,
        min_notional_usd=5.0,
        evidence_class="ASSUMPTION",
    )


@dataclass
class MarginState:
    """The perp leg's margin account, marked along the bar's path."""

    risk: InstrumentRisk
    quantity: float = 0.0  # signed; negative is short
    entry_price: float = 0.0
    posted_margin_usd: float = 0.0
    emergency_reserve_usd: float = 0.0
    liquidations: int = 0
    forced_unwinds: list[dict[str, Any]] = field(default_factory=list)

    def open(self, *, quantity: float, price: float, reserve_rate: float = 0.5) -> float:
        """Post initial margin plus an emergency reserve. Returns cash used."""
        notional = abs(quantity) * price
        margin = self.risk.initial_margin(notional)
        reserve = margin * reserve_rate
        self.quantity = quantity
        self.entry_price = price
        self.posted_margin_usd = margin
        self.emergency_reserve_usd = reserve
        return margin + reserve

    def variation_margin(self, mark: float) -> float:
        """Unrealized P&L on the perp: positive means the position is winning."""
        if abs(self.quantity) < 1e-18:
            return 0.0
        return (mark - self.entry_price) * self.quantity

    def equity_at(self, mark: float) -> float:
        return self.posted_margin_usd + self.emergency_reserve_usd + self.variation_margin(mark)

    def maintenance_required(self, mark: float) -> float:
        return self.risk.maintenance_margin(abs(self.quantity) * mark)

    def distance_at(self, mark: float) -> float:
        """Fraction of the maintenance requirement still covered."""
        required = self.maintenance_required(mark)
        if required <= 0:
            return 1.0
        return (self.equity_at(mark) - required) / required

    def worst_mark(self, *, high: float, low: float) -> float:
        """The bar extreme that hurts this position.

        A short is hurt by the high, a long by the low. Checking only the close
        is how a liquidation disappears from a backtest.
        """
        if self.quantity < 0:
            return high
        return low

    def check_intrabar(self, *, high: float, low: float, at_ms: int) -> dict[str, Any] | None:
        """Liquidate if the bar's adverse extreme breached maintenance."""
        if abs(self.quantity) < 1e-18:
            return None
        mark = self.worst_mark(high=high, low=low)
        distance = self.distance_at(mark)
        if distance >= 0:
            return None
        notional = abs(self.quantity) * mark
        penalty = notional * self.risk.liquidation_penalty_rate
        loss = self.posted_margin_usd + self.emergency_reserve_usd + self.variation_margin(mark)
        event = {
            "at_ms": at_ms,
            "venue": self.risk.venue,
            "instrument": self.risk.instrument,
            "breach_mark": mark,
            "distance": distance,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "maintenance_required_usd": self.maintenance_required(mark),
            "penalty_usd": penalty,
            "returned_to_cash_usd": max(0.0, loss - penalty),
            "reason": (
                "maintenance margin breached at the bar's adverse extreme; the "
                "position was force-closed, not carried to the close"
            ),
        }
        self.liquidations += 1
        self.forced_unwinds.append(event)
        self.quantity = 0.0
        self.entry_price = 0.0
        self.posted_margin_usd = 0.0
        self.emergency_reserve_usd = 0.0
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.risk.venue,
            "instrument": self.risk.instrument,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "posted_margin_usd": self.posted_margin_usd,
            "emergency_reserve_usd": self.emergency_reserve_usd,
            "liquidations": self.liquidations,
            "forced_unwinds": list(self.forced_unwinds),
        }


@dataclass
class CapitalRequirement:
    """What a position immobilises. Shares its denominator with the ledger."""

    notional_usd: float
    spot_capital_usd: float
    initial_margin_usd: float
    emergency_reserve_usd: float
    fee_reserve_usd: float
    transfer_reserve_usd: float

    @property
    def total_capital_usd(self) -> float:
        return (
            self.spot_capital_usd
            + self.initial_margin_usd
            + self.emergency_reserve_usd
            + self.fee_reserve_usd
            + self.transfer_reserve_usd
        )

    @property
    def capital_efficiency(self) -> float:
        return self.notional_usd / self.total_capital_usd if self.total_capital_usd else 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["total_capital_usd"] = self.total_capital_usd
        payload["capital_efficiency"] = self.capital_efficiency
        return payload


def capital_requirement(
    *,
    notional_usd: float,
    risk: InstrumentRisk,
    round_trip_cost_fraction: float,
    reserve_rate: float = 0.5,
    transfer_reserve_fraction: float = 0.0,
    spot_leg: bool = True,
) -> CapitalRequirement:
    """Every dollar the position ties up, using the ledger's own definitions.

    This is the same arithmetic the ledger applies when it opens a position —
    deliberately, because a capital figure computed from a different formula
    than the one the simulation uses is how a strategy ends up reporting a
    return on capital it never actually posted.
    """
    if notional_usd <= 0:
        raise MarginError("notional_usd must be > 0")
    initial = risk.initial_margin(notional_usd)
    return CapitalRequirement(
        notional_usd=notional_usd,
        spot_capital_usd=notional_usd if spot_leg else 0.0,
        initial_margin_usd=initial,
        emergency_reserve_usd=initial * reserve_rate,
        fee_reserve_usd=notional_usd * round_trip_cost_fraction,
        transfer_reserve_usd=notional_usd * transfer_reserve_fraction,
    )


__all__ = [
    "DEFAULT_RISK_TIERS",
    "CapitalRequirement",
    "InstrumentRisk",
    "MarginError",
    "MarginState",
    "RiskTier",
    "capital_requirement",
    "default_instrument_risk",
]
