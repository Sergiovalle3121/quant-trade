"""Dynamic cash-flow economics for a rented-hashrate purchase.

V7 could validate marketplace *evidence* but had no engine to answer the only
question that matters: if you rent this hashrate, do you end up with more
money than you started with? This module is that engine, and it is built
around one definition, applied literally:

    profit = value of coins actually received
             - every cost paid
             - every dollar effectively committed

Three consequences follow, and each is a place where mining calculators
usually flatter themselves:

* **Coins mined are not coins received.** Below the pool's minimum payout,
  the balance is stranded and its value to the buyer is zero. Above it, the
  withdrawal fee comes out first.
* **Committed capital is a cost even when refunded.** Escrowed and unused
  funds sit idle for the duration; the engine charges their opportunity cost
  at the same cash rate the trading side benchmarks against.
* **A short opportunity is not an annual rate.** Nothing here multiplies a
  three-day contract by 121. The result is reported over its own horizon, and
  :meth:`MiningEconomics.to_dict` says so explicitly.

Uncertainty is handled by a seeded Monte Carlo over delivery shortfall, pool
luck, difficulty drift and coin price, producing P05/P50/P95, the probability
of loss, and CVaR95 — the average outcome in the worst 5% of futures, which is
the number that decides whether a bad tail is survivable.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

#: Seconds between blocks, per network. Used to convert difficulty into an
#: expected share of block rewards.
NETWORK_BLOCK_SECONDS = {"bitcoin-mainnet": 600.0}

#: 2^32 — the number of hashes per unit of Bitcoin difficulty.
HASHES_PER_DIFFICULTY = 4_294_967_296.0

#: Opportunity cost charged against committed capital, matching the cash
#: benchmark used on the trading side.
DEFAULT_CASH_RATE_ANNUAL = 0.04

MONTE_CARLO_SAMPLES = 20_000
MONTE_CARLO_SEED = 20260728

PAYOUT_SCHEMES = ("PPS", "PPS_PLUS", "FPPS", "PPLNS")


def _positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0")


def _fraction(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0.0 <= value < 1.0:
        raise ValueError(f"{name} must be in [0, 1)")


@dataclass(frozen=True)
class PurchaseTerms:
    """What the marketplace charges and what it promises to deliver."""

    algorithm_id: str
    coin: str
    network: str
    native_unit: str
    units: float
    price_usd_per_unit_day: float
    duration_hours: float
    buyer_fee_rate: float = 0.03
    min_order_units: float = 0.0
    min_duration_hours: float = 0.0
    escrow_usd: float = 0.0
    deposited_usd: float | None = None
    cancellation_refund_rate: float = 0.0
    cancellation_penalty_usd: float = 0.0

    def __post_init__(self) -> None:
        _positive("units", self.units)
        _positive("price_usd_per_unit_day", self.price_usd_per_unit_day)
        _positive("duration_hours", self.duration_hours)
        _fraction("buyer_fee_rate", self.buyer_fee_rate)
        # A full refund of the unconsumed portion is a real marketplace term,
        # so 1.0 is allowed here even though it is not for a fee rate.
        if (
            not math.isfinite(self.cancellation_refund_rate)
            or not 0.0 <= self.cancellation_refund_rate <= 1.0
        ):
            raise ValueError("cancellation_refund_rate must be in [0, 1]")
        if self.units < self.min_order_units:
            raise ValueError(
                f"{self.units} units is below the marketplace minimum {self.min_order_units}"
            )
        if self.duration_hours < self.min_duration_hours:
            raise ValueError(
                f"{self.duration_hours}h is below the marketplace minimum "
                f"{self.min_duration_hours}h"
            )
        if self.escrow_usd < 0 or self.cancellation_penalty_usd < 0:
            raise ValueError("escrow and penalty must be >= 0")

    @property
    def duration_days(self) -> float:
        return self.duration_hours / 24.0

    @property
    def gross_purchase_usd(self) -> float:
        return self.units * self.price_usd_per_unit_day * self.duration_days

    @property
    def buyer_fee_usd(self) -> float:
        return self.gross_purchase_usd * self.buyer_fee_rate

    @property
    def unused_funds_usd(self) -> float:
        """Deposited but never spent — idle for the whole contract."""
        if self.deposited_usd is None:
            return 0.0
        return max(0.0, self.deposited_usd - self.gross_purchase_usd - self.buyer_fee_usd)


@dataclass(frozen=True)
class DeliveryAssumptions:
    """What actually arrives at the pool, versus what was bought."""

    delivered_ratio: float = 0.97
    delivered_ratio_p05: float = 0.85
    stale_share_rate: float = 0.005
    reject_share_rate: float = 0.005

    def __post_init__(self) -> None:
        for name in ("delivered_ratio", "delivered_ratio_p05"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1]")
        _fraction("stale_share_rate", self.stale_share_rate)
        _fraction("reject_share_rate", self.reject_share_rate)
        if self.delivered_ratio_p05 > self.delivered_ratio:
            raise ValueError("delivered_ratio_p05 cannot exceed delivered_ratio")

    @property
    def accepted_fraction(self) -> float:
        return self.delivered_ratio * (1.0 - self.stale_share_rate - self.reject_share_rate)


@dataclass(frozen=True)
class PoolTerms:
    """Where the hashrate is pointed and what that costs."""

    pool_name: str
    payout_scheme: str
    pool_fee_rate: float
    minimum_payout_coin: float
    withdrawal_cost_coin: float
    expected_luck: float = 1.0
    luck_volatility: float = 0.0

    def __post_init__(self) -> None:
        if self.payout_scheme not in PAYOUT_SCHEMES:
            raise ValueError(f"payout_scheme must be one of {PAYOUT_SCHEMES}")
        _fraction("pool_fee_rate", self.pool_fee_rate)
        if self.minimum_payout_coin < 0 or self.withdrawal_cost_coin < 0:
            raise ValueError("payout minimum and withdrawal cost must be >= 0")
        _positive("expected_luck", self.expected_luck)
        if self.luck_volatility < 0:
            raise ValueError("luck_volatility must be >= 0")

    @property
    def variance_bearing(self) -> bool:
        """PPS-family schemes sell the buyer out of block variance; PPLNS does not."""
        return self.payout_scheme == "PPLNS"


@dataclass(frozen=True)
class NetworkState:
    """Difficulty, reward and coin price, with their drift assumptions."""

    difficulty: float
    block_reward_coin: float
    coin_price_usd: float
    difficulty_drift_per_day: float = 0.0015
    difficulty_drift_volatility: float = 0.002
    price_volatility_daily: float = 0.03

    def __post_init__(self) -> None:
        _positive("difficulty", self.difficulty)
        _positive("block_reward_coin", self.block_reward_coin)
        _positive("coin_price_usd", self.coin_price_usd)
        if self.difficulty_drift_volatility < 0 or self.price_volatility_daily < 0:
            raise ValueError("volatilities must be >= 0")


def expected_coins_per_unit_day(
    *, network: str, difficulty: float, block_reward_coin: float, hashes_per_unit: float
) -> float:
    """Coins a single native unit of hashrate earns per day, in expectation.

    ``share_of_network x blocks_per_day x reward``, written directly in terms
    of difficulty so the number can be checked against any public calculator:
    network hashrate is ``difficulty x 2^32 / block_seconds``.
    """
    block_seconds = NETWORK_BLOCK_SECONDS.get(network)
    if block_seconds is None:
        raise ValueError(
            f"no block interval on record for {network!r}; refusing to guess "
            f"(known: {sorted(NETWORK_BLOCK_SECONDS)})"
        )
    network_hashrate = difficulty * HASHES_PER_DIFFICULTY / block_seconds
    blocks_per_day = 86_400.0 / block_seconds
    return hashes_per_unit / network_hashrate * blocks_per_day * block_reward_coin


@dataclass
class CashFlowLine:
    name: str
    usd: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MiningEconomics:
    """The full result: deterministic centre case plus the distribution."""

    algorithm_id: str
    coin: str
    horizon_days: float
    gross_coins_mined: float
    coins_received: float
    stranded_below_minimum: bool
    revenue_usd: float
    cash_flows: list[CashFlowLine] = field(default_factory=list)
    total_cost_usd: float = 0.0
    committed_capital_usd: float = 0.0
    profit_usd: float = 0.0
    return_on_committed_capital: float = 0.0
    scenarios: dict[str, Any] = field(default_factory=dict)
    loss_probability: float = 0.0
    cvar95_usd: float = 0.0
    versus_holding_coin_usd: float = 0.0
    versus_holding_cash_usd: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def profitable(self) -> bool:
        return self.profit_usd > 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cash_flows"] = [line.to_dict() for line in self.cash_flows]
        payload["profitable"] = self.profitable
        payload["annualized"] = None
        payload["annualization_note"] = (
            f"Deliberately not annualized. This is a {self.horizon_days:.3f}-day "
            "opportunity; there is no evidence it repeats, and multiplying a "
            "short contract up to a yearly rate is the single most common way "
            "rented-hashrate economics are overstated."
        )
        return payload


def evaluate_mining_purchase(
    purchase: PurchaseTerms,
    delivery: DeliveryAssumptions,
    pool: PoolTerms,
    network: NetworkState,
    *,
    hashes_per_unit: float,
    cash_rate_annual: float = DEFAULT_CASH_RATE_ANNUAL,
    samples: int = MONTE_CARLO_SAMPLES,
    seed: int = MONTE_CARLO_SEED,
    coin_price_end_usd: float | None = None,
) -> MiningEconomics:
    """Price one rented-hashrate purchase end to end."""
    import numpy as np

    days = purchase.duration_days
    per_unit_day = expected_coins_per_unit_day(
        network=purchase.network,
        difficulty=network.difficulty,
        block_reward_coin=network.block_reward_coin,
        hashes_per_unit=hashes_per_unit,
    )

    def _mined(
        accepted: np.ndarray | float, luck: np.ndarray | float, drift: np.ndarray | float
    ) -> Any:
        # Difficulty rises through the contract; integrating the daily share
        # over a linear drift is the average of a 1/(1+g*t) path, approximated
        # by its midpoint — accurate to well under a basis point at realistic
        # drift, and conservative in sign because the path is convex.
        average_difficulty_multiple = 1.0 + drift * days / 2.0
        return (
            purchase.units
            * per_unit_day
            * days
            * accepted
            * luck
            / average_difficulty_multiple
            * (1.0 - pool.pool_fee_rate)
        )

    centre_mined = float(
        _mined(delivery.accepted_fraction, pool.expected_luck, network.difficulty_drift_per_day)
    )

    def _received(mined: Any) -> Any:
        below = mined < pool.minimum_payout_coin
        net = np.maximum(0.0, mined - pool.withdrawal_cost_coin)
        return np.where(below, 0.0, net)

    centre_received = float(_received(np.asarray(centre_mined)))
    stranded = centre_mined < pool.minimum_payout_coin

    committed = purchase.gross_purchase_usd + purchase.buyer_fee_usd + purchase.escrow_usd
    committed += purchase.unused_funds_usd
    idle_years = days / 365.0
    escrow_opportunity = purchase.escrow_usd * cash_rate_annual * idle_years
    unused_opportunity = purchase.unused_funds_usd * cash_rate_annual * idle_years
    purchase_opportunity = (
        (purchase.gross_purchase_usd + purchase.buyer_fee_usd) * cash_rate_annual * idle_years
    )

    revenue = centre_received * network.coin_price_usd
    # The decomposition is built so that its lines SUM to profit. Mined coins
    # enter gross, before the pool's cut, and every deduction that stands
    # between "mined" and "in the buyer's wallet" appears as its own line —
    # otherwise the pool fee gets charged twice, once inside the coin figure
    # and once as a cost, and the total stops meaning anything.
    gross_before_pool_fee = centre_mined / max(1e-18, 1.0 - pool.pool_fee_rate)
    lines = [
        CashFlowLine(
            "gross_mining_revenue",
            gross_before_pool_fee * network.coin_price_usd,
            f"{gross_before_pool_fee:.8f} {purchase.coin} mined before the pool's cut",
        ),
        CashFlowLine(
            "pool_fee",
            -gross_before_pool_fee * pool.pool_fee_rate * network.coin_price_usd,
            f"{pool.pool_fee_rate:.2%} of mined coins, {pool.payout_scheme}",
        ),
        CashFlowLine(
            "withdrawal_cost",
            -(0.0 if stranded else pool.withdrawal_cost_coin * network.coin_price_usd),
            "on-chain payout fee",
        ),
        CashFlowLine(
            "stranded_balance",
            -(centre_mined * network.coin_price_usd if stranded else 0.0),
            f"mined {centre_mined:.8f} < pool minimum {pool.minimum_payout_coin:.8f}",
        ),
        CashFlowLine("hashrate_purchase", -purchase.gross_purchase_usd, "units x price x days"),
        CashFlowLine(
            "buyer_service_fee",
            -purchase.buyer_fee_usd,
            f"{purchase.buyer_fee_rate:.2%} of the purchase",
        ),
        CashFlowLine(
            "escrow_opportunity_cost",
            -escrow_opportunity,
            f"{purchase.escrow_usd:.2f} USD locked for {days:.3f}d",
        ),
        CashFlowLine(
            "unused_funds_opportunity_cost",
            -unused_opportunity,
            f"{purchase.unused_funds_usd:.2f} USD deposited but never spent",
        ),
        CashFlowLine(
            "purchase_capital_opportunity_cost",
            -purchase_opportunity,
            "the purchase price itself could have earned the cash rate",
        ),
    ]
    total_cost = -sum(line.usd for line in lines if line.usd < 0)
    profit = sum(line.usd for line in lines)

    # --- distribution -----------------------------------------------------
    rng = np.random.default_rng(seed)
    # Delivery shortfall: a beta-ish draw between the p05 floor and the
    # advertised ratio, so shortfall risk is one-sided (you never get MORE
    # hashrate than you paid for).
    span = delivery.delivered_ratio - delivery.delivered_ratio_p05
    delivered = delivery.delivered_ratio - span * rng.beta(1.5, 3.0, samples)
    accepted = delivered * (1.0 - delivery.stale_share_rate - delivery.reject_share_rate)
    if pool.variance_bearing and pool.luck_volatility > 0:
        luck = np.maximum(0.0, rng.normal(pool.expected_luck, pool.luck_volatility, samples))
    else:
        luck = np.full(samples, pool.expected_luck)
    drift = rng.normal(
        network.difficulty_drift_per_day, network.difficulty_drift_volatility, samples
    )
    drift = np.maximum(drift, -0.9 / max(days, 1e-9))
    price_shock = rng.normal(0.0, network.price_volatility_daily * math.sqrt(days), samples)
    end_price = network.coin_price_usd * np.exp(price_shock)

    mined = _mined(accepted, luck, drift)
    received = _received(mined)
    sample_revenue = received * end_price
    fixed_costs = (
        purchase.gross_purchase_usd
        + purchase.buyer_fee_usd
        + escrow_opportunity
        + unused_opportunity
        + purchase_opportunity
    )
    withdrawal = np.where(received > 0, pool.withdrawal_cost_coin * end_price, 0.0)
    sample_profit = sample_revenue - fixed_costs - withdrawal

    percentiles = np.percentile(sample_profit, [5, 50, 95])
    losses = sample_profit[sample_profit < 0]
    worst = np.sort(sample_profit)[: max(1, int(samples * 0.05))]

    end = coin_price_end_usd if coin_price_end_usd is not None else network.coin_price_usd
    spent = purchase.gross_purchase_usd + purchase.buyer_fee_usd
    hold_coin = spent * (end / network.coin_price_usd) - spent
    hold_cash = spent * cash_rate_annual * idle_years

    result = MiningEconomics(
        algorithm_id=purchase.algorithm_id,
        coin=purchase.coin,
        horizon_days=days,
        gross_coins_mined=centre_mined,
        coins_received=centre_received,
        stranded_below_minimum=stranded,
        revenue_usd=revenue,
        cash_flows=lines,
        total_cost_usd=total_cost,
        committed_capital_usd=committed,
        profit_usd=profit,
        return_on_committed_capital=profit / committed if committed > 0 else 0.0,
        scenarios={
            "samples": samples,
            "seed": seed,
            "p05_profit_usd": float(percentiles[0]),
            "p50_profit_usd": float(percentiles[1]),
            "p95_profit_usd": float(percentiles[2]),
            "mean_profit_usd": float(sample_profit.mean()),
            "stranded_fraction": float((received == 0).mean()),
        },
        loss_probability=float(len(losses) / samples),
        cvar95_usd=float(worst.mean()),
        versus_holding_coin_usd=float(hold_coin),
        versus_holding_cash_usd=float(hold_cash),
    )
    if stranded:
        result.problems.append(
            f"expected mined balance {centre_mined:.8f} {purchase.coin} is below the "
            f"pool minimum payout {pool.minimum_payout_coin:.8f}; the buyer receives "
            "nothing at all"
        )
    if profit <= 0:
        result.problems.append("centre-case profit is not positive")
    if result.loss_probability > 0.5:
        result.problems.append(
            f"loss probability {result.loss_probability:.1%} exceeds a coin flip"
        )
    return result


def cancellation_outcome(
    purchase: PurchaseTerms,
    *,
    elapsed_hours: float,
    cash_rate_annual: float = DEFAULT_CASH_RATE_ANNUAL,
) -> dict[str, Any]:
    """What the buyer gets back if the order is cancelled part-way through.

    Cancelling is not free and is rarely a full refund: the consumed portion
    is gone, the refundable remainder is scaled by the marketplace's refund
    rate, a penalty may apply, and the capital was idle regardless.
    """
    if elapsed_hours < 0:
        raise ValueError("elapsed_hours must be >= 0")
    elapsed = min(elapsed_hours, purchase.duration_hours)
    consumed_fraction = elapsed / purchase.duration_hours
    consumed_usd = purchase.gross_purchase_usd * consumed_fraction
    remaining_usd = purchase.gross_purchase_usd - consumed_usd
    refund = remaining_usd * purchase.cancellation_refund_rate - purchase.cancellation_penalty_usd
    refund = max(0.0, refund)
    idle_years = (elapsed / 24.0) / 365.0
    return {
        "elapsed_hours": elapsed,
        "consumed_fraction": consumed_fraction,
        "consumed_usd": consumed_usd,
        "refundable_usd": remaining_usd,
        "refund_rate": purchase.cancellation_refund_rate,
        "penalty_usd": purchase.cancellation_penalty_usd,
        "refund_received_usd": refund,
        "unrecovered_usd": purchase.gross_purchase_usd + purchase.buyer_fee_usd - refund,
        "idle_capital_opportunity_cost_usd": (
            (purchase.gross_purchase_usd + purchase.escrow_usd) * cash_rate_annual * idle_years
        ),
        "buyer_fee_refundable": False,
    }


__all__ = [
    "DEFAULT_CASH_RATE_ANNUAL",
    "HASHES_PER_DIFFICULTY",
    "MONTE_CARLO_SAMPLES",
    "MONTE_CARLO_SEED",
    "NETWORK_BLOCK_SECONDS",
    "PAYOUT_SCHEMES",
    "CashFlowLine",
    "DeliveryAssumptions",
    "MiningEconomics",
    "NetworkState",
    "PoolTerms",
    "PurchaseTerms",
    "cancellation_outcome",
    "evaluate_mining_purchase",
    "expected_coins_per_unit_day",
]
