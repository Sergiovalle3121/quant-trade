"""Rented-hashrate cash flow, kept in the currency the marketplace bills in.

V8 priced a purchase in USD as ``units x price x days``, which is the shape of
a mining calculator rather than the shape of a marketplace order. A NiceHash
order is funded in BTC, spends its balance as hashrate is *delivered*, charges
several fees at different triggers, and refunds whatever it never spent. Every
one of those steps moves the answer, and most of them move it against the
buyer.

The corrections this module encodes, each of which was wrong or missing in the
V8 engine, are listed in :data:`B4_CORRECTIONS` and asserted individually by
the tests. The three with the largest effect:

* **Spend follows delivery, not the order.** A 100 PH/s order that receives
  60 PH/s spends 60% of the money and mines 60% of the coins. Charging the
  full amount and crediting partial hashrate — or the reverse — breaks the
  only invariant that makes the result checkable.
* **Fees fire at different triggers.** Order creation is a fixed amount per
  order, the buyer fee is proportional to BTC *spent*, deposits are charged on
  the way in, and the withdrawal fee is charged once per payout — not once per
  day and not once per order.
* **The ledger is BTC.** Mining income and marketplace spend are both
  denominated in BTC, so a purchase is largely a bet on hashrate versus
  difficulty, not on price. Converting each leg to USD at a different moment
  invents a currency P&L that the buyer never took; USD is carried as a
  parallel view of the same BTC ledger.

Nothing here buys anything. The module has no client, no credentials and no
endpoint: it prices orders that a human might later place by hand.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from quant_trade.v8.hashrate_cashflow import (
    HASHES_PER_DIFFICULTY,
    NETWORK_BLOCK_SECONDS,
)
from quant_trade.v9.mining_units import MarketSpec, unit_hashes

#: The V8 cash-flow defects this module exists to fix. Emitted into the
#: artifact so a reader can check each one against the code and the tests.
B4_CORRECTIONS = (
    "withdrawal fee is charged once per payout, not per order or per day",
    "buyer fee is proportional to BTC spent, never to BTC deposited",
    "spend is proportional to hashrate actually accepted, not to speed ordered",
    "order creation costs a fixed fee per order, independent of size",
    "deposits are charged a fee on the way in",
    "unspent order balance is refunded, not consumed",
    "cancellation refunds the unspent balance minus the cancellation fee",
    "price, amount and speed limit are three independent order parameters",
    "the minimum order amount is denominated in BTC, not in hashrate",
    "orders have a maximum duration the venue enforces",
    "a bid below the market price stops receiving hashrate until repriced",
    "the pool fee is taken from mined coins before anything reaches the buyer",
    "a balance below the pool's payout minimum is not spendable",
    "balances accumulate across orders instead of resetting each time",
    "the ledger is kept in BTC with USD as a parallel view of the same rows",
    "the benchmark is holding BTC and holding cash, not zero",
)

#: Marketplace orders are billed per day of delivered speed.
HOURS_PER_DAY = 24.0

#: Opportunity cost charged against capital sitting in the marketplace wallet.
DEFAULT_CASH_RATE_ANNUAL = 0.04


class MiningCashFlowError(ValueError):
    """An order or fee arrangement that cannot be priced honestly."""


def _rate(name: str, value: float, *, high: float = 1.0) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= high:
        raise MiningCashFlowError(f"{name} must be in [0, {high}]")


@dataclass(frozen=True)
class MarketplaceFees:
    """Every fee the venue charges, each attached to the event that triggers it.

    Collapsing these into a single "3% fee" is the mistake this class exists to
    prevent: the fixed order fee dominates small orders, the deposit fee is
    paid whether or not the order ever fills, and the withdrawal fee is paid
    once regardless of how many orders funded the balance.
    """

    order_creation_fee_btc: float = 0.0
    buyer_fee_rate_on_spend: float = 0.03
    deposit_fee_btc: float = 0.0
    withdrawal_fee_btc: float = 0.0
    cancellation_fee_btc: float = 0.0
    refund_rate_on_cancellation: float = 1.0

    def __post_init__(self) -> None:
        for name in (
            "order_creation_fee_btc",
            "deposit_fee_btc",
            "withdrawal_fee_btc",
            "cancellation_fee_btc",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise MiningCashFlowError(f"{name} must be finite and >= 0")
        _rate("buyer_fee_rate_on_spend", self.buyer_fee_rate_on_spend)
        _rate("refund_rate_on_cancellation", self.refund_rate_on_cancellation)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["triggers"] = {
            "order_creation_fee_btc": "once, when an order is created",
            "buyer_fee_rate_on_spend": "proportional to BTC spent on delivered speed",
            "deposit_fee_btc": "once, per deposit into the marketplace wallet",
            "withdrawal_fee_btc": "once, per payout out of the pool",
            "cancellation_fee_btc": "once, only if the order is cancelled early",
        }
        return payload


@dataclass(frozen=True)
class PoolTerms:
    """Where the hashrate is pointed, and what the pool keeps."""

    pool_name: str
    payout_scheme: str
    pool_fee_rate: float
    minimum_payout_btc: float
    payout_evidence_class: str = "ASSUMPTION"

    def __post_init__(self) -> None:
        _rate("pool_fee_rate", self.pool_fee_rate, high=0.999)
        if not math.isfinite(self.minimum_payout_btc) or self.minimum_payout_btc < 0:
            raise MiningCashFlowError("minimum_payout_btc must be finite and >= 0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NetworkState:
    """Difficulty and reward, which together set what a hash is worth."""

    network: str
    difficulty: float
    block_reward_btc: float
    difficulty_drift_per_day: float = 0.0015

    def __post_init__(self) -> None:
        for name in ("difficulty", "block_reward_btc"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise MiningCashFlowError(f"{name} must be finite and > 0")
        if self.network not in NETWORK_BLOCK_SECONDS:
            raise MiningCashFlowError(
                f"no block interval on record for {self.network!r}; refusing to guess "
                f"(known: {sorted(NETWORK_BLOCK_SECONDS)})"
            )

    def btc_per_hash_second_day(self, *, day_index: float = 0.0) -> float:
        """BTC earned per day by one hash/s, at the difficulty on that day."""
        block_seconds = NETWORK_BLOCK_SECONDS[self.network]
        difficulty = self.difficulty * (1.0 + self.difficulty_drift_per_day) ** day_index
        network_hashrate = difficulty * HASHES_PER_DIFFICULTY / block_seconds
        blocks_per_day = 86_400.0 / block_seconds
        return blocks_per_day * self.block_reward_btc / network_hashrate


@dataclass(frozen=True)
class HashrateOrder:
    """One marketplace order: price, amount and limit are three variables.

    They are routinely conflated. ``price_btc`` is a bid per speed-unit per
    day, ``amount_btc`` is the budget escrowed into the order, and
    ``speed_limit`` is the maximum speed the order will accept. The order ends
    when the budget runs out or the duration expires, whichever comes first —
    and a bid below the market clears slowly, so the two are not equivalent.
    """

    spec: MarketSpec
    price_btc_per_speed_unit_day: float
    amount_btc: float
    speed_limit: float
    duration_hours: float
    max_duration_hours: float = 24.0 * 30.0

    def __post_init__(self) -> None:
        problems = self.spec.validate_order(
            amount_btc=self.amount_btc,
            speed_limit=self.speed_limit,
            price_btc=self.price_btc_per_speed_unit_day,
        )
        if self.duration_hours <= 0:
            problems.append("duration_hours must be > 0")
        if self.duration_hours > self.max_duration_hours:
            problems.append(
                f"duration {self.duration_hours}h exceeds the venue maximum "
                f"{self.max_duration_hours}h"
            )
        if problems:
            raise MiningCashFlowError("; ".join(problems))

    @property
    def duration_days(self) -> float:
        return self.duration_hours / HOURS_PER_DAY

    @property
    def budgeted_spend_rate_btc_per_day(self) -> float:
        """What the order costs per day if it receives its full speed limit."""
        return self.speed_limit * self.price_btc_per_speed_unit_day

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.spec.algorithm,
            "market": self.spec.market,
            "speed_unit": self.spec.speed_text,
            "price_btc_per_speed_unit_day": self.price_btc_per_speed_unit_day,
            "amount_btc": self.amount_btc,
            "speed_limit": self.speed_limit,
            "duration_hours": self.duration_hours,
            "parameter_semantics": (
                "price is a bid, amount is an escrowed budget, speed limit is "
                "the maximum speed requested; none of the three implies the others"
            ),
        }


@dataclass(frozen=True)
class DeliveryProfile:
    """What the order receives, hour by hour, and what the pool accepts.

    ``market_price_path`` is the competing bid over the order's life. When it
    rises above the order's price the order is outbid and receives nothing —
    the repricing risk that makes a cheap bid different from a cheap purchase.
    """

    fill_ratio_at_price: float = 1.0
    stale_share_rate: float = 0.005
    reject_share_rate: float = 0.005
    market_price_path: tuple[float, ...] = ()
    reprice_up_to_btc: float | None = None

    def __post_init__(self) -> None:
        _rate("fill_ratio_at_price", self.fill_ratio_at_price)
        _rate("stale_share_rate", self.stale_share_rate, high=0.999)
        _rate("reject_share_rate", self.reject_share_rate, high=0.999)
        if self.stale_share_rate + self.reject_share_rate >= 1.0:
            raise MiningCashFlowError("stale + reject shares must leave something accepted")

    @property
    def accepted_share(self) -> float:
        return 1.0 - self.stale_share_rate - self.reject_share_rate

    def price_at(self, hour: int) -> float | None:
        if not self.market_price_path:
            return None
        index = min(hour, len(self.market_price_path) - 1)
        return self.market_price_path[index]


@dataclass
class OrderOutcome:
    """One order's life, in BTC, with the reason it ended."""

    order: HashrateOrder
    hours_run: float = 0.0
    hours_delivering: float = 0.0
    speed_unit_hours_delivered: float = 0.0
    spent_btc: float = 0.0
    buyer_fee_btc: float = 0.0
    creation_fee_btc: float = 0.0
    cancellation_fee_btc: float = 0.0
    refunded_btc: float = 0.0
    gross_mined_btc: float = 0.0
    pool_fee_btc: float = 0.0
    net_mined_btc: float = 0.0
    repriced_to_btc: float | None = None
    hours_outbid: float = 0.0
    ended_because: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def delivered_ratio(self) -> float:
        """Speed-unit-hours received over speed-unit-hours requested."""
        requested = self.order.speed_limit * self.hours_run
        return self.speed_unit_hours_delivered / requested if requested else 0.0

    @property
    def total_cost_btc(self) -> float:
        return (
            self.spent_btc + self.buyer_fee_btc + self.creation_fee_btc + self.cancellation_fee_btc
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "order": self.order.to_dict(),
            "hours_run": self.hours_run,
            "hours_delivering": self.hours_delivering,
            "hours_outbid": self.hours_outbid,
            "delivered_ratio": self.delivered_ratio,
            "spent_btc": self.spent_btc,
            "buyer_fee_btc": self.buyer_fee_btc,
            "creation_fee_btc": self.creation_fee_btc,
            "cancellation_fee_btc": self.cancellation_fee_btc,
            "refunded_btc": self.refunded_btc,
            "total_cost_btc": self.total_cost_btc,
            "gross_mined_btc": self.gross_mined_btc,
            "pool_fee_btc": self.pool_fee_btc,
            "net_mined_btc": self.net_mined_btc,
            "repriced_to_btc": self.repriced_to_btc,
            "ended_because": self.ended_because,
            "notes": list(self.notes),
        }
        return payload


def run_order(
    order: HashrateOrder,
    *,
    delivery: DeliveryProfile,
    pool: PoolTerms,
    network: NetworkState,
    fees: MarketplaceFees,
    cancel_after_hours: float | None = None,
    step_hours: float = 1.0,
) -> OrderOutcome:
    """Walk one order hour by hour, spending only for hashrate it receives.

    The loop is the point. Spend, buyer fee and mined coins all derive from the
    same ``accepted`` figure in the same step, so a delivery shortfall reduces
    income and outlay together — the invariant that a per-order lump sum
    silently breaks.
    """
    if step_hours <= 0:
        raise MiningCashFlowError("step_hours must be > 0")

    outcome = OrderOutcome(order=order, creation_fee_btc=fees.order_creation_fee_btc)
    remaining = order.amount_btc - fees.order_creation_fee_btc
    if remaining <= 0:
        outcome.ended_because = "amount_below_creation_fee"
        outcome.notes.append(
            f"the fixed {fees.order_creation_fee_btc:.8f} BTC order fee consumes the "
            f"whole {order.amount_btc:.8f} BTC budget"
        )
        return outcome

    hashes_per_speed_unit = unit_hashes(order.spec.speed_text)
    price = order.price_btc_per_speed_unit_day
    horizon = order.duration_hours
    if cancel_after_hours is not None:
        horizon = min(horizon, max(0.0, cancel_after_hours))

    elapsed = 0.0
    hour = 0
    while elapsed < horizon - 1e-12:
        slice_hours = min(step_hours, horizon - elapsed)
        market_price = delivery.price_at(hour)

        if market_price is not None and market_price > price:
            ceiling = delivery.reprice_up_to_btc
            if ceiling is not None and market_price <= min(ceiling, order.spec.max_price_btc):
                price = market_price
                outcome.repriced_to_btc = price
                outcome.notes.append(
                    f"repriced to {price:.10f} BTC at hour {hour} to stay in the book"
                )
            else:
                outcome.hours_outbid += slice_hours
                outcome.hours_run += slice_hours
                elapsed += slice_hours
                hour += 1
                continue

        delivered_speed = order.speed_limit * delivery.fill_ratio_at_price
        days = slice_hours / HOURS_PER_DAY
        gross_spend = delivered_speed * price * days
        # The buyer fee rides on spend, so budget must cover both together.
        needed = gross_spend * (1.0 + fees.buyer_fee_rate_on_spend)
        if needed > remaining:
            # The budget buys a fraction of this slice's speed and stops. Both
            # the spend and the hashrate scale by the same factor, so the order
            # never mines coins it did not pay for.
            scale = remaining / needed if needed else 0.0
            gross_spend *= scale
            delivered_speed *= scale
            outcome.ended_because = "budget_exhausted"

        fee = gross_spend * fees.buyer_fee_rate_on_spend
        remaining -= gross_spend + fee
        outcome.spent_btc += gross_spend
        outcome.buyer_fee_btc += fee

        delivered_unit_hours = delivered_speed * slice_hours
        outcome.speed_unit_hours_delivered += delivered_unit_hours
        outcome.hours_delivering += slice_hours if delivered_speed > 0 else 0.0

        accepted_hashes = delivered_speed * hashes_per_speed_unit * delivery.accepted_share
        day_index = elapsed / HOURS_PER_DAY
        outcome.gross_mined_btc += (
            accepted_hashes * network.btc_per_hash_second_day(day_index=day_index) * days
        )

        outcome.hours_run += slice_hours
        elapsed += slice_hours
        hour += 1
        if outcome.ended_because == "budget_exhausted":
            break

    if not outcome.ended_because:
        outcome.ended_because = (
            "cancelled"
            if cancel_after_hours is not None and horizon < order.duration_hours
            else "duration_elapsed"
        )

    outcome.pool_fee_btc = outcome.gross_mined_btc * pool.pool_fee_rate
    outcome.net_mined_btc = outcome.gross_mined_btc - outcome.pool_fee_btc

    if outcome.ended_because == "cancelled":
        outcome.cancellation_fee_btc = min(remaining, fees.cancellation_fee_btc)
        remaining -= outcome.cancellation_fee_btc
        outcome.refunded_btc = max(0.0, remaining * fees.refund_rate_on_cancellation)
        forfeited = max(0.0, remaining - outcome.refunded_btc)
        if forfeited > 0:
            outcome.notes.append(
                f"{forfeited:.8f} BTC of the unspent budget is not refunded at "
                f"a {fees.refund_rate_on_cancellation:.0%} refund rate"
            )
    else:
        outcome.refunded_btc = max(0.0, remaining)

    if outcome.hours_outbid > 0:
        outcome.notes.append(
            f"outbid for {outcome.hours_outbid:.1f}h of {outcome.hours_run:.1f}h: a bid "
            "below the market receives no hashpower and mines nothing"
        )
    return outcome


@dataclass
class LedgerRow:
    """One movement, in BTC, with its USD view at the rate of the moment."""

    event: str
    btc: float
    usd: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MiningLedger:
    """A BTC ledger for a campaign of orders, with USD carried alongside.

    Balances accumulate: two orders that each mine half the pool minimum reach
    it together, and the withdrawal fee is paid once when they do. Resetting
    per order both strands coins that were not stranded and charges a payout
    fee that was never paid.
    """

    btc_usd: float
    fees: MarketplaceFees
    pool: PoolTerms
    rows: list[LedgerRow] = field(default_factory=list)
    wallet_btc: float = 0.0
    pool_balance_btc: float = 0.0
    withdrawn_btc: float = 0.0
    withdrawals: int = 0
    deposited_btc: float = 0.0
    problems: list[str] = field(default_factory=list)

    def _row(self, event: str, btc: float, note: str = "") -> None:
        self.rows.append(LedgerRow(event=event, btc=btc, usd=btc * self.btc_usd, note=note))

    def deposit(self, btc: float) -> None:
        """Fund the marketplace wallet. The venue charges on the way in."""
        if btc <= 0:
            raise MiningCashFlowError("deposit must be > 0")
        fee = self.fees.deposit_fee_btc
        if fee >= btc:
            raise MiningCashFlowError(
                f"deposit fee {fee:.8f} BTC consumes the whole {btc:.8f} BTC deposit"
            )
        self.deposited_btc += btc
        self.wallet_btc += btc - fee
        self._row("deposit", -btc, "capital moved into the marketplace wallet")
        self._row("deposit_fee", -fee, "charged once per deposit")

    def apply_order(self, outcome: OrderOutcome) -> None:
        """Book one order's spend, fees, refund and mined coins."""
        committed = outcome.order.amount_btc
        if committed > self.wallet_btc + 1e-12:
            self.problems.append(
                f"order needs {committed:.8f} BTC but the wallet holds {self.wallet_btc:.8f} BTC"
            )
            return
        self.wallet_btc -= committed
        self.wallet_btc += outcome.refunded_btc

        self._row("order_creation_fee", -outcome.creation_fee_btc, "fixed, per order")
        self._row(
            "hashrate_spend",
            -outcome.spent_btc,
            f"{outcome.delivered_ratio:.1%} of requested speed-hours delivered",
        )
        self._row(
            "buyer_fee",
            -outcome.buyer_fee_btc,
            f"{self.fees.buyer_fee_rate_on_spend:.2%} of BTC spent, not of BTC deposited",
        )
        if outcome.cancellation_fee_btc:
            self._row("cancellation_fee", -outcome.cancellation_fee_btc, "early cancellation")
        self._row("refund_unspent", outcome.refunded_btc, "budget the order never spent")
        self._row("mined_gross", outcome.gross_mined_btc, "before the pool's cut")
        self._row(
            "pool_fee",
            -outcome.pool_fee_btc,
            f"{self.pool.pool_fee_rate:.2%}, {self.pool.payout_scheme}",
        )
        self.pool_balance_btc += outcome.net_mined_btc

    def withdraw(self) -> float:
        """Pay out the pool balance, once, if it clears the minimum."""
        if self.pool_balance_btc < self.pool.minimum_payout_btc:
            self.problems.append(
                f"pool balance {self.pool_balance_btc:.8f} BTC is below the "
                f"{self.pool.minimum_payout_btc:.8f} BTC payout minimum: the coins "
                "are mined but not spendable"
            )
            return 0.0
        fee = self.fees.withdrawal_fee_btc
        net = max(0.0, self.pool_balance_btc - fee)
        self._row("withdrawal_fee", -fee, "charged once per payout, not per order")
        self._row("payout", net, f"{self.pool.pool_name} -> wallet")
        self.wallet_btc += net
        self.withdrawn_btc += net
        self.withdrawals += 1
        self.pool_balance_btc = 0.0
        return net

    @property
    def stranded_btc(self) -> float:
        """Mined, credited by the pool, and not withdrawable."""
        if self.pool_balance_btc < self.pool.minimum_payout_btc:
            return self.pool_balance_btc
        return 0.0

    @property
    def net_btc(self) -> float:
        """End-to-end BTC change: what is in the wallet minus what went in.

        Coins still sitting in the pool count as zero, whether they are below
        the payout minimum or simply not yet withdrawn. They exist in the
        pool's database and not in the buyer's wallet, and treating a pool
        balance as income is how a losing rental reads as a win.
        """
        return self.wallet_btc - self.deposited_btc

    def summary(
        self,
        *,
        horizon_days: float,
        btc_usd_end: float | None = None,
        cash_rate_annual: float = DEFAULT_CASH_RATE_ANNUAL,
    ) -> dict[str, Any]:
        """The campaign's result in BTC and USD, against both benchmarks.

        Two benchmarks, because a rental can win one and lose the other: BTC
        that would have been held anyway (did renting produce more coins than
        simply keeping them?) and cash at the risk-free rate (was the capital
        better off idle?).
        """
        end_rate = self.btc_usd if btc_usd_end is None else btc_usd_end
        net_btc = self.wallet_btc - self.deposited_btc
        spend_btc = -sum(r.btc for r in self.rows if r.btc < 0 and r.event != "deposit")
        # Mined and paid out are the same coins at two different points, so
        # they are reported side by side rather than summed into an "income"
        # figure that would count the payout twice.
        mined_gross_btc = sum(r.btc for r in self.rows if r.event == "mined_gross")
        paid_out_btc = sum(r.btc for r in self.rows if r.event == "payout")
        idle_years = horizon_days / 365.0

        # Three end states for the same starting stack, valued at the same
        # moment. Holding BTC keeps the coins and takes the price move; holding
        # cash sells at the start rate and earns the cash rate; renting ends
        # with the coins plus whatever the campaign netted.
        rented_end_usd = (self.deposited_btc + net_btc) * end_rate
        hold_btc_end_usd = self.deposited_btc * end_rate
        hold_cash_end_usd = (
            self.deposited_btc * self.btc_usd * (1.0 + cash_rate_annual * idle_years)
        )
        return {
            "horizon_days": horizon_days,
            "btc_usd_start": self.btc_usd,
            "btc_usd_end": end_rate,
            "deposited_btc": self.deposited_btc,
            "wallet_btc": self.wallet_btc,
            "pool_balance_btc": self.pool_balance_btc,
            "stranded_btc": self.stranded_btc,
            "withdrawals": self.withdrawals,
            "withdrawn_btc": self.withdrawn_btc,
            "total_spend_btc": spend_btc,
            "mined_gross_btc": mined_gross_btc,
            "paid_out_btc": paid_out_btc,
            "net_btc": net_btc,
            "net_usd_at_start_rate": net_btc * self.btc_usd,
            "net_usd_at_end_rate": net_btc * end_rate,
            "versus_holding_btc_btc": net_btc,
            "versus_holding_btc_usd": rented_end_usd - hold_btc_end_usd,
            "versus_holding_cash_usd": rented_end_usd - hold_cash_end_usd,
            "rows": [r.to_dict() for r in self.rows],
            "problems": list(self.problems),
            "currency_note": (
                "Spend and income are both BTC, so the campaign is a bet on "
                "hashrate against difficulty; the USD columns are a view of the "
                "same BTC rows and do not add a separate currency P&L."
            ),
            "annualization_note": (
                f"Deliberately not annualized. This is a {horizon_days:.3f}-day "
                "opportunity and there is no evidence it repeats."
            ),
        }


def run_campaign(
    orders: list[tuple[HashrateOrder, DeliveryProfile]],
    *,
    deposit_btc: float,
    fees: MarketplaceFees,
    pool: PoolTerms,
    network: NetworkState,
    btc_usd: float,
    btc_usd_end: float | None = None,
    cancel_after_hours: float | None = None,
) -> tuple[MiningLedger, list[OrderOutcome]]:
    """Price a sequence of orders against one accumulating balance."""
    ledger = MiningLedger(btc_usd=btc_usd, fees=fees, pool=pool)
    ledger.deposit(deposit_btc)
    outcomes: list[OrderOutcome] = []
    for order, delivery in orders:
        outcome = run_order(
            order,
            delivery=delivery,
            pool=pool,
            network=network,
            fees=fees,
            cancel_after_hours=cancel_after_hours,
        )
        ledger.apply_order(outcome)
        outcomes.append(outcome)
    ledger.withdraw()
    return ledger, outcomes


__all__ = [
    "B4_CORRECTIONS",
    "DEFAULT_CASH_RATE_ANNUAL",
    "DeliveryProfile",
    "HashrateOrder",
    "LedgerRow",
    "MarketplaceFees",
    "MiningCashFlowError",
    "MiningLedger",
    "NetworkState",
    "OrderOutcome",
    "PoolTerms",
    "run_campaign",
    "run_order",
]
