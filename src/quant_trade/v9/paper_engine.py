"""An autonomous paper engine whose P&L is derived, never supplied.

V8's paper layer had a hole that made every number it produced meaningless: a
``paper_fill`` event carried a caller-supplied yield, and the session applied
it to equity directly. No order had to exist. No price, quantity, side or fee
was required. Equity moved because the caller said so.

The fix is structural rather than a validation rule. :meth:`PaperSession.advance`
accepts **market ticks only**. Orders are produced by the frozen strategy,
matched by the simulated broker, and turned into fills with a price, a
quantity, a side and a fee; equity is then recomputed from the balance sheet.
There is no code path by which a caller can move equity, because there is no
argument that carries one.

Everything else follows from taking the balance sheet seriously: a spot buy
spends cash and holds coin, a perp short posts margin and accrues variation,
funding settles against the position that existed at the settlement instant,
and :meth:`PaperSession.reconcile` recomputes equity from the journal and
halts the session if it disagrees with the running total.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

#: Reconciliation tolerance, as a fraction of initial capital.
RECONCILIATION_TOLERANCE = 1e-9

#: How stale market data may be before the breaker trips.
DEFAULT_STALE_TICK_SECONDS = 900.0

#: Clock provenance. Only a system clock supports an operational claim.
CLOCK_SYSTEM = "system"
CLOCK_INJECTED_TEST = "injected_test"

SIDE_BUY = "buy"
SIDE_SELL = "sell"
SIDES = (SIDE_BUY, SIDE_SELL)

ORDER_OPEN = "open"
ORDER_FILLED = "filled"
ORDER_PARTIAL = "partially_filled"
ORDER_CANCELLED = "cancelled"

SESSION_RUNNING = "PAPER_RUNNING"
SESSION_STOPPED = "PAPER_STOPPED"
SESSION_HALTED = "PAPER_HALTED"


class PaperEngineError(RuntimeError):
    """The session was asked to do something that would corrupt its books."""


class LeaseError(PaperEngineError):
    """Another writer holds the session lease."""


# --- market data ---------------------------------------------------------------


@dataclass(frozen=True)
class MarketTick:
    """One observable market state.

    The three timestamps are kept apart on purpose. ``bar_start_ms`` and
    ``bar_end_ms`` bound the interval the prices describe; ``observed_at_ms``
    is when the engine could first have known them. A close is not observable
    until the bar has ended, and the engine refuses a tick that claims
    otherwise.
    """

    venue: str
    instrument: str
    bar_start_ms: int
    bar_end_ms: int
    observed_at_ms: int
    spot_bid: float
    spot_ask: float
    perp_bid: float
    perp_ask: float
    perp_mark: float
    index: float
    settled_funding_rate: float | None = None
    spot_quote_volume: float = 0.0
    perp_quote_volume: float = 0.0

    def __post_init__(self) -> None:
        if self.bar_end_ms <= self.bar_start_ms:
            raise PaperEngineError("bar_end_ms must be after bar_start_ms")
        if self.observed_at_ms < self.bar_end_ms:
            raise PaperEngineError(
                f"tick claims it was observed at {self.observed_at_ms} but its bar "
                f"only closes at {self.bar_end_ms}: a close is not observable "
                "before the bar ends"
            )
        for name in ("spot_bid", "spot_ask", "perp_bid", "perp_ask", "perp_mark", "index"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise PaperEngineError(f"{name} must be finite and > 0")
        if self.spot_bid > self.spot_ask or self.perp_bid > self.perp_ask:
            raise PaperEngineError("bid cannot exceed ask")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- orders and fills ------------------------------------------------------------


@dataclass
class PaperOrder:
    client_order_id: str
    venue: str
    instrument: str
    leg: str  # "spot" | "perp"
    side: str
    quantity: float
    order_type: str
    created_at_ms: int
    eligible_at_ms: int
    status: str = ORDER_OPEN
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    limit_price: float | None = None

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise PaperEngineError(f"side must be one of {SIDES}")
        if self.leg not in ("spot", "perp"):
            raise PaperEngineError("leg must be 'spot' or 'perp'")
        if not math.isfinite(self.quantity) or self.quantity <= 0:
            raise PaperEngineError("order quantity must be finite and > 0")

    @property
    def remaining(self) -> float:
        return max(0.0, self.quantity - self.filled_quantity)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["remaining"] = self.remaining
        return payload


@dataclass
class PaperFill:
    client_order_id: str
    venue: str
    instrument: str
    leg: str
    side: str
    price: float
    quantity: float
    fee_usd: float
    at_ms: int
    sequence: int
    is_partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- balance sheet ----------------------------------------------------------------


@dataclass
class Position:
    leg: str
    quantity: float = 0.0  # signed: + long, - short
    average_price: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerTotals:
    realized_pnl_usd: float = 0.0
    fees_usd: float = 0.0
    funding_usd: float = 0.0
    conversion_usd: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class PositionLedger:
    """The books. Equity is computed from here and from nowhere else."""

    initial_capital_usd: float
    cash_usd: float = 0.0
    margin_posted_usd: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    totals: LedgerTotals = field(default_factory=LedgerTotals)
    perp_leverage: float = 3.0
    liquidations: int = 0

    def __post_init__(self) -> None:
        if self.initial_capital_usd <= 0:
            raise PaperEngineError("initial capital must be > 0")
        if not self.cash_usd:
            self.cash_usd = self.initial_capital_usd

    def position(self, leg: str) -> Position:
        return self.positions.setdefault(leg, Position(leg=leg))

    def apply_fill(self, fill: PaperFill) -> None:
        """Move cash, coin and margin. Nothing else may touch the books."""
        position = self.position(fill.leg)
        signed = fill.quantity if fill.side == SIDE_BUY else -fill.quantity
        notional = fill.price * fill.quantity
        self.cash_usd -= fill.fee_usd
        self.totals.fees_usd += fill.fee_usd

        if fill.leg == "spot":
            # A spot buy spends cash for coin; a sell returns cash and realizes.
            if signed > 0:
                self.cash_usd -= notional
            else:
                self.cash_usd += notional
                if position.quantity > 0:
                    closed = min(position.quantity, fill.quantity)
                    self.totals.realized_pnl_usd += (fill.price - position.average_price) * closed
        else:
            # A perp posts initial margin on the opening side and releases it
            # (plus the realized variation) on the closing side.
            opening = (position.quantity >= 0 and signed > 0) or (
                position.quantity <= 0 and signed < 0
            )
            if opening:
                margin = notional / self.perp_leverage
                self.cash_usd -= margin
                self.margin_posted_usd += margin
            else:
                closed = min(abs(position.quantity), fill.quantity)
                direction = 1.0 if position.quantity < 0 else -1.0
                self.totals.realized_pnl_usd += (
                    direction * (fill.price - position.average_price) * closed
                )
                released = position.average_price * closed / self.perp_leverage
                released = min(released, self.margin_posted_usd)
                self.margin_posted_usd -= released
                self.cash_usd += released + (
                    direction * (fill.price - position.average_price) * closed
                )

        new_quantity = position.quantity + signed
        if position.quantity == 0 or (position.quantity > 0) == (signed > 0):
            total = abs(position.quantity) + fill.quantity
            position.average_price = (
                (position.average_price * abs(position.quantity) + notional) / total
                if total
                else 0.0
            )
        elif abs(new_quantity) > 1e-18 and (new_quantity > 0) != (position.quantity > 0):
            position.average_price = fill.price  # flipped through zero
        position.quantity = 0.0 if abs(new_quantity) < 1e-18 else new_quantity

    def apply_funding(self, rate: float, mark: float) -> float:
        """Settle funding against the perp position that exists right now.

        A short perp *receives* funding when the rate is positive. The amount
        is charged on the position at the settlement instant — not on whatever
        the strategy holds later.
        """
        perp = self.position("perp")
        if abs(perp.quantity) < 1e-18:
            return 0.0
        amount = -perp.quantity * mark * rate
        self.cash_usd += amount
        self.totals.funding_usd += amount
        return amount

    def unrealized_usd(self, *, spot_mark: float, perp_mark: float) -> float:
        spot = self.position("spot")
        perp = self.position("perp")
        value = spot.quantity * spot_mark
        if abs(perp.quantity) > 1e-18:
            value += (perp.average_price - perp_mark) * -perp.quantity * -1.0
        return value

    def equity_usd(self, *, spot_mark: float, perp_mark: float) -> float:
        spot = self.position("spot")
        perp = self.position("perp")
        equity = self.cash_usd + self.margin_posted_usd
        equity += spot.quantity * spot_mark
        if abs(perp.quantity) > 1e-18:
            # A short perp gains when the mark falls: (entry - mark) * size.
            equity += (perp.average_price - perp_mark) * (-perp.quantity)
        return equity

    def maintenance_distance(self, *, perp_mark: float, maintenance_rate: float) -> float:
        """How far the perp is from its maintenance requirement, as a fraction."""
        perp = self.position("perp")
        if abs(perp.quantity) < 1e-18:
            return 1.0
        notional = abs(perp.quantity) * perp_mark
        required = notional * maintenance_rate
        variation = (perp.average_price - perp_mark) * (-perp.quantity)
        available = self.margin_posted_usd + variation
        if required <= 0:
            return 1.0
        return (available - required) / max(required, 1e-12)

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital_usd": self.initial_capital_usd,
            "cash_usd": self.cash_usd,
            "margin_posted_usd": self.margin_posted_usd,
            "positions": {k: v.to_dict() for k, v in sorted(self.positions.items())},
            "totals": self.totals.to_dict(),
            "perp_leverage": self.perp_leverage,
            "liquidations": self.liquidations,
        }


# --- broker -------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionModel:
    """How a simulated order becomes a fill. Every field costs the strategy."""

    latency_ms: int = 250
    slippage_bps: float = 1.0
    max_participation: float = 0.01
    spot_fee_bps: float = 10.0
    perp_fee_bps: float = 5.5
    partial_fill_enabled: bool = True

    def fee_bps(self, leg: str) -> float:
        return self.spot_fee_bps if leg == "spot" else self.perp_fee_bps


class SimulatedBroker:
    """Matches orders against observable quotes. Never reaches a venue."""

    def __init__(self, execution: ExecutionModel) -> None:
        self.execution = execution
        self.open_orders: dict[str, PaperOrder] = {}
        self._sequence = 0

    def submit(self, order: PaperOrder) -> PaperOrder:
        if order.client_order_id in self.open_orders:
            raise PaperEngineError(
                f"client_order_id {order.client_order_id!r} is already open; "
                "identifiers are idempotency keys and may not be reused"
            )
        self.open_orders[order.client_order_id] = order
        return order

    def cancel(self, client_order_id: str) -> PaperOrder:
        order = self.open_orders.pop(client_order_id, None)
        if order is None:
            raise PaperEngineError(f"no open order {client_order_id!r} to cancel")
        order.status = ORDER_CANCELLED
        return order

    def match(self, tick: MarketTick) -> list[PaperFill]:
        """Fill whatever is eligible at this tick, respecting liquidity."""
        fills: list[PaperFill] = []
        for order in list(self.open_orders.values()):
            if tick.observed_at_ms < order.eligible_at_ms:
                continue  # still in flight
            price = self._fill_price(order, tick)
            quantity = self._fill_quantity(order, tick, price)
            if quantity <= 0:
                continue
            fee = price * quantity * self.execution.fee_bps(order.leg) / 10_000.0
            self._sequence += 1
            partial = quantity + 1e-12 < order.remaining
            fills.append(
                PaperFill(
                    client_order_id=order.client_order_id,
                    venue=order.venue,
                    instrument=order.instrument,
                    leg=order.leg,
                    side=order.side,
                    price=price,
                    quantity=quantity,
                    fee_usd=fee,
                    at_ms=tick.observed_at_ms,
                    sequence=self._sequence,
                    is_partial=partial,
                )
            )
            filled_notional = order.average_fill_price * order.filled_quantity
            order.filled_quantity += quantity
            order.average_fill_price = (filled_notional + price * quantity) / order.filled_quantity
            if order.remaining <= 1e-12:
                order.status = ORDER_FILLED
                self.open_orders.pop(order.client_order_id, None)
            else:
                order.status = ORDER_PARTIAL
        return fills

    def _fill_price(self, order: PaperOrder, tick: MarketTick) -> float:
        bid, ask = (
            (tick.spot_bid, tick.spot_ask)
            if order.leg == "spot"
            else (tick.perp_bid, tick.perp_ask)
        )
        touch = ask if order.side == SIDE_BUY else bid
        drift = self.execution.slippage_bps / 10_000.0
        return touch * (1.0 + drift) if order.side == SIDE_BUY else touch * (1.0 - drift)

    def _fill_quantity(self, order: PaperOrder, tick: MarketTick, price: float) -> float:
        if not self.execution.partial_fill_enabled:
            return order.remaining
        volume = tick.spot_quote_volume if order.leg == "spot" else tick.perp_quote_volume
        if volume <= 0:
            return order.remaining
        allowed_notional = volume * self.execution.max_participation
        allowed_quantity = allowed_notional / max(price, 1e-12)
        return min(order.remaining, allowed_quantity)


# --- strategy ------------------------------------------------------------------------


@dataclass(frozen=True)
class FrozenCarryStrategy:
    """The pre-registered carry rule, frozen from a candidate manifest."""

    entry_threshold: float
    trailing_window: int
    target_notional_usd: float

    def __post_init__(self) -> None:
        if self.trailing_window < 1:
            raise PaperEngineError("trailing_window must be >= 1")
        if self.target_notional_usd <= 0:
            raise PaperEngineError("target_notional_usd must be > 0")

    def desired_position(self, settled_rates: list[float]) -> int:
        """1 to hold the carry, 0 to stand flat. Settled rates only."""
        if len(settled_rates) < self.trailing_window:
            return 0
        window = settled_rates[-self.trailing_window :]
        return 1 if sum(window) / len(window) > self.entry_threshold else 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "CLOCK_INJECTED_TEST",
    "CLOCK_SYSTEM",
    "DEFAULT_STALE_TICK_SECONDS",
    "ORDER_CANCELLED",
    "ORDER_FILLED",
    "ORDER_OPEN",
    "ORDER_PARTIAL",
    "RECONCILIATION_TOLERANCE",
    "SESSION_HALTED",
    "SESSION_RUNNING",
    "SESSION_STOPPED",
    "SIDES",
    "SIDE_BUY",
    "SIDE_SELL",
    "ExecutionModel",
    "FrozenCarryStrategy",
    "LeaseError",
    "LedgerTotals",
    "MarketTick",
    "PaperEngineError",
    "PaperFill",
    "PaperOrder",
    "Position",
    "PositionLedger",
    "SimulatedBroker",
]
