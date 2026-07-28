"""The full cost stack for a two-leg carry, and what it takes to break even.

Two ideas hold this module together.

**Every cost carries its evidence class.** A fee schedule read from the venue's
own API is `REAL`; a number typed in from documentation that could not be
re-fetched is `ASSUMPTION_UNVERIFIED`. The distinction is not cosmetic:
:func:`CostStack.promotable` is False whenever any component is unverified, so
a strategy can never be promoted on assumed costs. What an unverified stack
*can* do is bound the problem — which is why every assumption here is required
to be conservative, i.e. to overstate cost. An overstated cost can only make a
strategy look worse, so a strategy that fails on assumed costs would also have
failed on real ones.

**Break-even is computable without price history.** How much funding a carry
must earn to cover its own frictions is a property of the cost stack and the
holding period, not of what BTC did last year. So even with acquisition
blocked, the exact bar a strategy has to clear can be stated — and that number
is the most useful thing a rejected campaign can hand to the next attempt.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

#: Evidence classes a cost input can carry, worst to best.
COST_EVIDENCE_CLASSES = ("ASSUMPTION_UNVERIFIED", "RECORDED_RESPONSE", "REAL")

#: Only this class may support a promotion decision.
PROMOTABLE_COST_EVIDENCE = "REAL"

#: Units a cost component may be expressed in.
COST_UNITS = ("bps_per_fill", "annual_fraction", "one_off_fraction", "usd_flat")


@dataclass(frozen=True)
class CostComponent:
    """One priced friction, with where the number came from."""

    name: str
    value: float
    unit: str
    evidence_class: str
    source: str
    note: str = ""

    def __post_init__(self) -> None:
        if self.unit not in COST_UNITS:
            raise ValueError(f"unit must be one of {COST_UNITS}")
        if self.evidence_class not in COST_EVIDENCE_CLASSES:
            raise ValueError(f"evidence_class must be one of {COST_EVIDENCE_CLASSES}")
        if not math.isfinite(self.value) or self.value < 0:
            raise ValueError(f"{self.name}: cost must be finite and >= 0")
        if not self.source.strip():
            raise ValueError(f"{self.name}: every cost needs a source")

    @property
    def promotable(self) -> bool:
        return self.evidence_class == PROMOTABLE_COST_EVIDENCE

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["promotable"] = self.promotable
        return payload


@dataclass(frozen=True)
class CostStack:
    """Every friction a delta-neutral spot/perp carry pays, priced.

    The four fills of a round trip are: buy spot, sell perp (entry), sell
    spot, buy perp (exit). Per-fill frictions are charged on each of them.
    """

    venue: str
    components: tuple[CostComponent, ...]
    multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.multiplier < 1.0:
            raise ValueError("cost multiplier must be >= 1.0 — stress only adds cost")
        names = [c.name for c in self.components]
        if len(names) != len(set(names)):
            raise ValueError("duplicate cost component names")

    def scaled(self, multiplier: float) -> CostStack:
        """The same stack under a 1x/2x/3x stress. Nothing else changes."""
        return CostStack(venue=self.venue, components=self.components, multiplier=multiplier)

    def _sum(self, unit: str) -> float:
        return sum(c.value for c in self.components if c.unit == unit) * self.multiplier

    @property
    def per_fill_bps(self) -> float:
        return self._sum("bps_per_fill")

    @property
    def round_trip_fraction(self) -> float:
        """Four fills plus one-off frictions, as a fraction of notional."""
        return self.per_fill_bps / 10_000.0 * 4.0 + self._sum("one_off_fraction")

    @property
    def annual_carrying_fraction(self) -> float:
        return self._sum("annual_fraction")

    @property
    def promotable(self) -> bool:
        return all(c.promotable for c in self.components)

    @property
    def weakest_evidence_class(self) -> str:
        return min(
            (c.evidence_class for c in self.components),
            key=COST_EVIDENCE_CLASSES.index,
            default=PROMOTABLE_COST_EVIDENCE,
        )

    def by_category(self) -> dict[str, float]:
        """Per-component contribution to one round trip, as a fraction."""
        out: dict[str, float] = {}
        for component in self.components:
            if component.unit == "bps_per_fill":
                out[component.name] = component.value / 10_000.0 * 4.0 * self.multiplier
            elif component.unit == "one_off_fraction":
                out[component.name] = component.value * self.multiplier
            elif component.unit == "annual_fraction":
                out[component.name] = component.value * self.multiplier  # per year
            else:
                out[component.name] = component.value * self.multiplier
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "multiplier": self.multiplier,
            "per_fill_bps": self.per_fill_bps,
            "round_trip_fraction": self.round_trip_fraction,
            "annual_carrying_fraction": self.annual_carrying_fraction,
            "promotable": self.promotable,
            "weakest_evidence_class": self.weakest_evidence_class,
            "components": [c.to_dict() for c in self.components],
            "by_category": self.by_category(),
        }


def _bps(name: str, value: float, source: str, *, evidence: str, note: str = "") -> CostComponent:
    return CostComponent(
        name=name,
        value=value,
        unit="bps_per_fill",
        evidence_class=evidence,
        source=source,
        note=note,
    )


#: Documented public fee pages. Recorded here so a future run with network
#: access knows exactly what to fetch to upgrade these to REAL.
FEE_SCHEDULE_SOURCES = {
    "bybit": "https://api.bybit.com/v5/market/instruments-info (+ published fee schedule)",
    "okx": "https://www.okx.com/api/v5/public/instruments (+ published fee schedule)",
}


def conservative_cost_stack(
    venue: str,
    *,
    evidence_class: str = "ASSUMPTION_UNVERIFIED",
    cross_venue: bool = False,
) -> CostStack:
    """A deliberately pessimistic stack for one venue.

    Every number is chosen at or above the venue's published *retail* rate. A
    real desk pays less (VIP tiers, maker rebates, better spreads), so this
    stack overstates cost — which is the only safe direction for an
    unverified input: it can reject a strategy that would have worked, but it
    can never promote one that would not.
    """
    source = FEE_SCHEDULE_SOURCES[venue]
    # Published retail taker fees: Bybit linear perp 0.055%, OKX perp 0.050%;
    # spot taker 0.100% on both. Applied as taker on every fill because a
    # carry that must be delta-neutral cannot rely on resting maker fills.
    perp_taker_bps = {"bybit": 5.5, "okx": 5.0}[venue]
    components = [
        _bps(
            "spot_taker_fee",
            10.0,
            source,
            evidence=evidence_class,
            note="published retail spot taker rate; VIP tiers are cheaper",
        ),
        _bps(
            "perp_taker_fee",
            perp_taker_bps,
            source,
            evidence=evidence_class,
            note="published retail linear-perp taker rate",
        ),
        _bps(
            "half_spread",
            1.0,
            "conservative desk assumption for BTC top-of-book",
            evidence=evidence_class,
            note="BTC/USDT is among the deepest books; 1bp is pessimistic",
        ),
        _bps(
            "slippage",
            1.0,
            "conservative desk assumption",
            evidence=evidence_class,
            note="beyond the touch, at research size",
        ),
        _bps(
            "market_impact",
            1.0,
            "conservative desk assumption",
            evidence=evidence_class,
            note="temporary impact at research size",
        ),
        _bps(
            "latency_and_partial_fill",
            0.5,
            "conservative desk assumption",
            evidence=evidence_class,
            note="adverse selection between the two legs of the hedge",
        ),
        CostComponent(
            name="collateral_opportunity_cost",
            value=0.04,
            unit="annual_fraction",
            evidence_class=evidence_class,
            source="cash baseline yield (configs/opportunities/cash_baseline_v7.json)",
            note="margin and spot inventory are immobilised and earn nothing",
        ),
        CostComponent(
            name="perp_margin_maintenance_drag",
            value=0.005,
            unit="annual_fraction",
            evidence_class=evidence_class,
            source="conservative desk assumption",
            note="buffer capital held against variation margin calls",
        ),
        CostComponent(
            name="conversion_and_withdrawal",
            value=0.0005,
            unit="one_off_fraction",
            evidence_class=evidence_class,
            source="conservative desk assumption",
            note="fiat/stable conversion in and out of the position",
        ),
        CostComponent(
            name="emergency_unwind_reserve",
            value=0.0010,
            unit="one_off_fraction",
            evidence_class=evidence_class,
            source="conservative desk assumption",
            note="priced allowance for unwinding both legs into a stressed book",
        ),
    ]
    if cross_venue:
        components.append(
            CostComponent(
                name="cross_venue_transfer",
                value=0.0015,
                unit="one_off_fraction",
                evidence_class=evidence_class,
                source="conservative desk assumption",
                note=(
                    "on-chain/internal transfer, confirmation delay and the "
                    "unhedged window while capital moves between venues"
                ),
            )
        )
    return CostStack(venue=venue, components=tuple(components))


@dataclass
class BreakEven:
    """What the strategy must earn to cover its own frictions."""

    venue: str
    holding_days: float
    funding_interval_hours: float
    multiplier: float
    round_trip_fraction: float
    annual_carrying_fraction: float
    total_cost_over_holding: float
    required_total_funding_fraction: float
    required_funding_rate_per_interval: float
    required_annualized_funding: float
    settlements_over_holding: float
    components: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def break_even_funding(
    stack: CostStack,
    *,
    holding_days: float,
    funding_interval_hours: float = 8.0,
    multiplier: float = 1.0,
) -> BreakEven:
    """The average settled funding rate that exactly covers all costs.

    A carry held for ``holding_days`` pays its round trip once and its
    carrying costs continuously. Break-even is therefore::

        settlements x rate  =  round_trip + annual_carry x (days / 365)

    Solving for ``rate`` gives the *average settled funding per interval* the
    position must receive, which is directly comparable to what a venue
    publishes — no annualisation sleight of hand.
    """
    if holding_days <= 0:
        raise ValueError("holding_days must be > 0")
    if funding_interval_hours <= 0:
        raise ValueError("funding_interval_hours must be > 0")
    scaled = stack.scaled(multiplier)
    years = holding_days / 365.0
    settlements = holding_days * 24.0 / funding_interval_hours
    total_cost = scaled.round_trip_fraction + scaled.annual_carrying_fraction * years
    required_rate = total_cost / settlements
    intervals_per_year = 365.0 * 24.0 / funding_interval_hours
    return BreakEven(
        venue=stack.venue,
        holding_days=holding_days,
        funding_interval_hours=funding_interval_hours,
        multiplier=multiplier,
        round_trip_fraction=scaled.round_trip_fraction,
        annual_carrying_fraction=scaled.annual_carrying_fraction,
        total_cost_over_holding=total_cost,
        required_total_funding_fraction=total_cost,
        required_funding_rate_per_interval=required_rate,
        required_annualized_funding=required_rate * intervals_per_year,
        settlements_over_holding=settlements,
        components=scaled.by_category(),
    )


def capital_requirement(
    *, notional_usd: float, perp_leverage: float, maintenance_buffer: float = 2.0
) -> dict[str, float]:
    """Capital actually immobilised by a carry of ``notional_usd``.

    The spot leg is fully funded — a delta-neutral carry owns the coin. The
    perp leg posts initial margin plus a buffer, because a short perp against
    a rising spot bleeds variation margin exactly when the position is
    working. Ignoring that buffer is how backtests invent leverage they could
    not have survived.
    """
    if notional_usd <= 0:
        raise ValueError("notional_usd must be > 0")
    if perp_leverage <= 0:
        raise ValueError("perp_leverage must be > 0")
    if maintenance_buffer < 1.0:
        raise ValueError("maintenance_buffer must be >= 1.0")
    spot_capital = notional_usd
    perp_margin = notional_usd / perp_leverage
    buffer = perp_margin * (maintenance_buffer - 1.0)
    total = spot_capital + perp_margin + buffer
    return {
        "spot_capital_usd": spot_capital,
        "perp_initial_margin_usd": perp_margin,
        "perp_buffer_usd": buffer,
        "total_capital_usd": total,
        "capital_efficiency": notional_usd / total,
    }


__all__ = [
    "COST_EVIDENCE_CLASSES",
    "COST_UNITS",
    "FEE_SCHEDULE_SOURCES",
    "PROMOTABLE_COST_EVIDENCE",
    "BreakEven",
    "CostComponent",
    "CostStack",
    "break_even_funding",
    "capital_requirement",
    "conservative_cost_stack",
]
