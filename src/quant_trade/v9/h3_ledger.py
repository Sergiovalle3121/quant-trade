"""H3 cross-venue funding dispersion, priced on two separate balance sheets.

V8's H3 borrowed the single-venue carry's cost stack, which meant it charged
Bybit's fees on the OKX leg and computed capacity from one venue while the
report claimed it was the minimum of two. Both are the same mistake: pretending
that operating on two venues is operating on one.

Here each venue gets its own books — cash, collateral, initial and maintenance
margin, its own fee schedule, its own funding — and the strategy's return is
``equity_t / equity_{t-1} - 1`` over the *combined* balance sheet after every
flow has been applied. Nothing is annualised, netted early, or computed from a
notional that was never posted.

Capital in transit is modelled explicitly. Moving collateral between venues
takes time, costs a fee, and leaves the position unhedged while it moves; a
model that teleports capital between exchanges is describing a strategy nobody
can run.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.v9.margin import InstrumentRisk, MarginState


class H3LedgerError(ValueError):
    """The dispersion account was given something it cannot price."""


@dataclass(frozen=True)
class VenueCosts:
    """One venue's own fee schedule. Never shared with the other venue."""

    venue: str
    perp_taker_bps: float
    half_spread_bps: float
    slippage_bps: float
    impact_bps: float
    transfer_out_fraction: float
    transfer_hours: float
    evidence_class: str = "ASSUMPTION"

    def per_fill_bps(self) -> float:
        return self.perp_taker_bps + self.half_spread_bps + self.slippage_bps + self.impact_bps

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["per_fill_bps"] = self.per_fill_bps()
        return payload


@dataclass
class VenueBook:
    """One venue's balance sheet."""

    venue: str
    costs: VenueCosts
    risk: InstrumentRisk
    cash_usd: float
    margin: MarginState = field(init=False)
    fees_usd: float = 0.0
    funding_usd: float = 0.0
    transfer_usd: float = 0.0
    in_transit_usd: float = 0.0
    in_transit_until_ms: int = 0

    def __post_init__(self) -> None:
        self.margin = MarginState(risk=self.risk)

    def equity_usd(self, mark: float) -> float:
        """Cash, posted collateral, variation margin and capital in transit."""
        return self.cash_usd + self.margin.equity_at(mark) + self.in_transit_usd

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "cash_usd": self.cash_usd,
            "fees_usd": self.fees_usd,
            "funding_usd": self.funding_usd,
            "transfer_usd": self.transfer_usd,
            "in_transit_usd": self.in_transit_usd,
            "margin": self.margin.to_dict(),
            "costs": self.costs.to_dict(),
        }


@dataclass(frozen=True)
class DispersionBar:
    """One aligned bar across both venues."""

    start_ms: int
    end_ms: int
    observed_at_ms: int
    mark_a: float
    high_a: float
    low_a: float
    mark_b: float
    high_b: float
    low_b: float
    settled_funding_a: float = 0.0
    settled_funding_b: float = 0.0
    quote_volume_a: float = 0.0
    quote_volume_b: float = 0.0

    def __post_init__(self) -> None:
        for name in ("mark_a", "mark_b", "high_a", "high_b", "low_a", "low_b"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise H3LedgerError(f"{name} must be finite and > 0")
        if self.low_a > self.high_a or self.low_b > self.high_b:
            raise H3LedgerError("low cannot exceed high")


@dataclass
class DispersionResult:
    initial_capital_usd: float
    final_equity_usd: float
    equity_curve: list[float] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)
    entries: int = 0
    switches: int = 0
    transfers: int = 0
    liquidations: int = 0
    totals: dict[str, float] = field(default_factory=dict)
    books: dict[str, Any] = field(default_factory=dict)
    reconciliation_error: float = 0.0
    reconciled: bool = True
    problems: list[str] = field(default_factory=list)
    capacity_usd: float | None = None
    capacity_detail: dict[str, Any] = field(default_factory=dict)

    @property
    def net_return(self) -> float:
        return (
            self.final_equity_usd / self.initial_capital_usd - 1.0
            if self.initial_capital_usd
            else 0.0
        )

    @property
    def max_drawdown(self) -> float:
        peak = -math.inf
        worst = 0.0
        for value in self.equity_curve:
            peak = max(peak, value)
            if peak > 0:
                worst = min(worst, value / peak - 1.0)
        return worst

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifact"] = "H3_LEDGER_RECONCILIATION"
        payload["schema_version"] = 1
        payload["net_return"] = self.net_return
        payload["max_drawdown"] = self.max_drawdown
        payload["observations"] = len(self.returns)
        payload["note"] = (
            "Returns are equity_t/equity_{t-1}-1 over the combined balance "
            "sheet after every flow. Each venue carries its own fee schedule; "
            "neither venue's costs are applied to the other's leg."
        )
        return payload


def run_dispersion(
    bars: list[DispersionBar],
    *,
    book_a: VenueBook,
    book_b: VenueBook,
    entry_threshold: float,
    trailing_window: int,
    target_notional_usd: float,
    transfer_reserve_fraction: float = 0.0,
) -> DispersionResult:
    """Simulate the two-venue dispersion account, bar by bar.

    Direction ``+1`` shorts venue A's perp and longs venue B's, collecting
    ``funding_a - funding_b``; ``-1`` is the mirror. A switch closes four legs
    and pays two entries plus a transfer.
    """
    if len(bars) < trailing_window + 2:
        raise H3LedgerError(
            f"{len(bars)} aligned bars is too few for a trailing window of "
            f"{trailing_window}; dispersion needs history on BOTH venues"
        )
    initial = book_a.cash_usd + book_b.cash_usd
    if initial <= 0:
        raise H3LedgerError("dispersion needs positive starting capital")

    result = DispersionResult(initial_capital_usd=initial, final_equity_usd=initial)
    totals = {
        "funding_spread_usd": 0.0,
        "mark_divergence_usd": 0.0,
        "fees_usd": 0.0,
        "transfer_usd": 0.0,
        "liquidation_penalty_usd": 0.0,
    }
    spreads: list[float] = []
    direction = 0
    previous_equity = initial
    result.equity_curve.append(initial)

    for bar in bars:
        # 1. Funding settles per venue, on that venue's own position.
        for book, rate, mark in (
            (book_a, bar.settled_funding_a, bar.mark_a),
            (book_b, bar.settled_funding_b, bar.mark_b),
        ):
            if rate and abs(book.margin.quantity) > 1e-18:
                amount = -book.margin.quantity * mark * rate
                book.cash_usd += amount
                book.funding_usd += amount
                totals["funding_spread_usd"] += amount

        # 2. Capital in transit lands once its clock has run out.
        for book in (book_a, book_b):
            if book.in_transit_usd > 0 and bar.observed_at_ms >= book.in_transit_until_ms:
                book.cash_usd += book.in_transit_usd
                book.in_transit_usd = 0.0

        # 3. Liquidation on the adverse extreme, per venue, before anything else.
        for book, high, low in (
            (book_a, bar.high_a, bar.low_a),
            (book_b, bar.high_b, bar.low_b),
        ):
            event = book.margin.check_intrabar(high=high, low=low, at_ms=bar.observed_at_ms)
            if event is not None:
                book.cash_usd += float(event["returned_to_cash_usd"])
                totals["liquidation_penalty_usd"] += float(event["penalty_usd"])
                result.liquidations += 1
                direction = 0
                result.problems.append(f"liquidation on {book.venue} at {event['breach_mark']}")

        # 4. Signal from the settled spread only.
        spread = bar.settled_funding_a - bar.settled_funding_b
        spreads.append(spread)
        if len(spreads) >= trailing_window:
            trailing = sum(spreads[-trailing_window:]) / trailing_window
            wanted = 1 if trailing > entry_threshold else (-1 if trailing < -entry_threshold else 0)
        else:
            wanted = 0

        if wanted != direction:
            closing = direction != 0
            opening = wanted != 0
            for book, mark in ((book_a, bar.mark_a), (book_b, bar.mark_b)):
                if closing and abs(book.margin.quantity) > 1e-18:
                    notional = abs(book.margin.quantity) * mark
                    fee = notional * book.costs.per_fill_bps() / 10_000.0
                    variation = book.margin.variation_margin(mark)
                    book.cash_usd += (
                        book.margin.posted_margin_usd
                        + book.margin.emergency_reserve_usd
                        + variation
                        - fee
                    )
                    book.fees_usd += fee
                    totals["fees_usd"] += fee
                    totals["mark_divergence_usd"] += variation
                    book.margin.quantity = 0.0
                    book.margin.posted_margin_usd = 0.0
                    book.margin.emergency_reserve_usd = 0.0
            if opening:
                # +1 shorts A and longs B; -1 mirrors.
                for book, mark, sign in (
                    (book_a, bar.mark_a, -wanted),
                    (book_b, bar.mark_b, wanted),
                ):
                    quantity = sign * target_notional_usd / mark
                    rounded = book.risk.round_quantity(abs(quantity))
                    tradeable, why = book.risk.is_tradeable(rounded, mark)
                    if not tradeable:
                        result.problems.append(f"{book.venue}: {why}")
                        wanted = 0
                        break
                    signed = math.copysign(rounded, quantity)
                    posted = book.margin.open(quantity=signed, price=mark)
                    fee = rounded * mark * book.costs.per_fill_bps() / 10_000.0
                    book.cash_usd -= posted + fee
                    book.fees_usd += fee
                    totals["fees_usd"] += fee
                if wanted != 0:
                    transfer = (
                        target_notional_usd
                        * book_a.costs.transfer_out_fraction
                        * transfer_reserve_fraction
                    )
                    if transfer > 0:
                        book_a.cash_usd -= transfer
                        book_a.transfer_usd += transfer
                        totals["transfer_usd"] += transfer
                        result.transfers += 1
                    if direction == 0:
                        result.entries += 1
                    else:
                        result.switches += 1
            direction = wanted

        # 5. Mark the combined balance sheet and take the period return.
        equity = book_a.equity_usd(bar.mark_a) + book_b.equity_usd(bar.mark_b)
        result.equity_curve.append(equity)
        result.returns.append(equity / previous_equity - 1.0 if previous_equity else 0.0)
        previous_equity = equity

    # Terminal close: an open position at the end of the sample is not free.
    for book, mark in ((book_a, bars[-1].mark_a), (book_b, bars[-1].mark_b)):
        if abs(book.margin.quantity) > 1e-18:
            notional = abs(book.margin.quantity) * mark
            fee = notional * book.costs.per_fill_bps() / 10_000.0
            variation = book.margin.variation_margin(mark)
            book.cash_usd += (
                book.margin.posted_margin_usd + book.margin.emergency_reserve_usd + variation - fee
            )
            book.fees_usd += fee
            totals["fees_usd"] += fee
            totals["mark_divergence_usd"] += variation
            book.margin.quantity = 0.0
            book.margin.posted_margin_usd = 0.0
            book.margin.emergency_reserve_usd = 0.0

    final = book_a.equity_usd(bars[-1].mark_a) + book_b.equity_usd(bars[-1].mark_b)
    result.final_equity_usd = final
    result.totals = totals
    result.books = {"a": book_a.to_dict(), "b": book_b.to_dict()}

    # Reconciliation: the change in equity must equal the sum of the flows.
    accounted = (
        totals["funding_spread_usd"]
        + totals["mark_divergence_usd"]
        - totals["fees_usd"]
        - totals["transfer_usd"]
        - totals["liquidation_penalty_usd"]
    )
    result.reconciliation_error = abs((final - initial) - accounted)
    tolerance = 1e-6 * max(1.0, initial)
    result.reconciled = result.reconciliation_error <= tolerance
    if not result.reconciled:
        result.problems.append(
            f"equity moved {final - initial:.10f} but the flow journal accounts "
            f"for {accounted:.10f} (error {result.reconciliation_error:.10f})"
        )
    return result


def dispersion_capacity(
    bars: list[DispersionBar], *, participation_rate: float = 0.01
) -> dict[str, Any]:
    """Capacity is the MINIMUM of the two venues, computed from both.

    Writing "min(Bybit, OKX)" while measuring one venue is the specific claim
    V8 made and could not support, so both are measured here and the smaller
    one is the answer.
    """
    volumes_a = sorted(b.quote_volume_a for b in bars if b.quote_volume_a > 0)
    volumes_b = sorted(b.quote_volume_b for b in bars if b.quote_volume_b > 0)
    if not volumes_a or not volumes_b:
        return {
            "available": False,
            "reason": "one or both venues carry no volume; capacity is unknown",
        }

    def p05(values: list[float]) -> float:
        return values[max(0, int(len(values) * 0.05) - 1)]

    capacity_a = p05(volumes_a) * participation_rate
    capacity_b = p05(volumes_b) * participation_rate
    return {
        "available": True,
        "participation_rate": participation_rate,
        "venue_a_capacity_usd": capacity_a,
        "venue_b_capacity_usd": capacity_b,
        "capacity_usd": min(capacity_a, capacity_b),
        "binding_venue": "a" if capacity_a <= capacity_b else "b",
        "basis": (
            "5th-percentile aligned-bar quote volume x participation rate, "
            "computed independently on each venue; the minimum binds"
        ),
    }


__all__ = [
    "DispersionBar",
    "DispersionResult",
    "H3LedgerError",
    "VenueBook",
    "VenueCosts",
    "dispersion_capacity",
    "run_dispersion",
]
